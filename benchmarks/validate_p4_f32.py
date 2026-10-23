"""Binary32 PI host SIL with an error budget fixed before execution."""

import ctypes
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

from validate_p4 import python_step

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p4-f32"
ABSOLUTE = 2e-4
RELATIVE = 2e-5
FLAGS = [
    "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
    "-Wdouble-promotion", "-Wconversion", "-ffp-contract=off",
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def f32(values):
    return [ctypes.c_float(value).value for value in values]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = ROOT / "firmware/oeal_current_pi_f32.c"
    library_path = OUT / "liboeal_pi_f32.so"
    command = ["gcc", *FLAGS, "-shared", "-fPIC", str(source), "-lm", "-o", str(library_path)]
    subprocess.run(command, check=True)
    static = subprocess.run(
        ["gcc", *FLAGS, "-fanalyzer", "-fsyntax-only", str(source)],
        capture_output=True, text=True, check=True,
    )
    (OUT / "static-check.txt").write_text(static.stdout + static.stderr)
    library = ctypes.CDLL(str(library_path))
    pointer = ctypes.POINTER(ctypes.c_float)
    library.oeal_pi_step_f32.argtypes = [pointer] * 4
    library.oeal_pi_step_f32.restype = ctypes.c_int

    def step(p, state, inputs):
        pa = (ctypes.c_float * 7)(*p)
        st = (ctypes.c_float * 2)(*state)
        inp = (ctypes.c_float * 7)(*inputs)
        out = (ctypes.c_float * 8)(*([999.0] * 8))
        before = (bytes(pa), bytes(st), bytes(inp))
        status = library.oeal_pi_step_f32(pa, st, inp, out)
        if before != (bytes(pa), bytes(st), bytes(inp)):
            raise AssertionError("C modified read-only input/state buffers")
        return status, list(out)

    failures, errors = [], []
    worst = {"max_abs_error": 0.0}
    def compare(name, actual, expected):
        nonlocal worst
        if not all(math.isfinite(value) for value in actual):
            failures.append({"name": name, "reason": "nonfinite output"})
            return
        error = max(abs(a - b) for a, b in zip(actual, expected, strict=True))
        errors.append({"name": name, "max_abs_error": error})
        if error > worst["max_abs_error"]:
            worst = {"name": name, "max_abs_error": error}
        valid = all(
            a == b if index in (4, 5)
            else math.isclose(a, b, abs_tol=ABSOLUTE, rel_tol=RELATIVE)
            for index, (a, b) in enumerate(zip(actual, expected, strict=True))
        )
        if not valid:
            failures.append({"name": name, "actual": actual, "expected": expected})

    vector_path = ROOT / "benchmarks/sil-vectors.json"
    vectors = json.loads(vector_path.read_text())["vectors"]
    for vector in vectors:
        p, state, inputs = map(f32, (vector["p"], vector["state"], vector["input"]))
        status, actual = step(p, state, inputs)
        if status:
            failures.append({"name": vector["name"], "reason": "unexpected rejection"})
        else:
            compare(vector["name"] + "/hand", actual, vector["expected"])
            compare(vector["name"] + "/double", actual, python_step(p, state, inputs))

    p = f32([1.6, 600, 1.6, 600, 48 / math.sqrt(3), 10, 2000])
    reference_state, target_state = [0.0, 0.0], [0.0, 0.0]
    for tick in range(2000):
        inputs = f32([
            3 * math.sin(tick * 0.013), 12 * math.cos(tick * 0.009),
            2 * math.sin(tick * 0.02), 3 * math.cos(tick * 0.017), 50e-6,
            5 * math.sin(tick * 0.005), 20 * math.cos(tick * 0.007),
        ])
        reference = python_step(p, reference_state, inputs)
        status, actual = step(p, target_state, inputs)
        if status:
            failures.append({"name": f"sequence/{tick}", "reason": "unexpected rejection"})
            break
        compare(f"sequence/{tick}", actual, reference)
        if math.hypot(*actual[:2]) > p[4] + 2e-5:
            failures.append({"name": f"sequence/{tick}", "reason": "voltage bound"})
        reference_state, target_state = reference[6:], actual[6:]

    # Independent exact saturated integrator and reversal recurrence.
    sat_p = f32([0, 10, 0, 10, 2, 10, 1e6])
    state = [0.0, 0.0]
    for tick in range(100):
        status, actual = step(sat_p, state, f32([10, 0, 0, 0, 0.1, 0, 0]))
        if status:
            raise AssertionError("saturation sequence rejected")
        compare(f"saturation/{tick}", actual, [2, 0, 10, 0, 1, 0, 2, 0])
        state = actual[6:]
    for tick, expected in enumerate((1.0, 0.0)):
        status, actual = step(sat_p, state, f32([-1, 0, 0, 0, 0.1, 0, 0]))
        if status:
            raise AssertionError("recovery sequence rejected")
        compare(f"recovery/{tick}", actual, [expected, 0, -1, 0, 0, 0, expected, 0])
        state = actual[6:]

    base_input = f32([1, 2, 0, 0, 50e-6, 0, 0])
    invalid = []
    for group, count in (("parameter", 7), ("input", 7), ("state", 2)):
        for index in range(count):
            for value in (math.nan, math.inf, -math.inf):
                values = {"parameter": p.copy(), "input": base_input.copy(), "state": [0, 0]}
                values[group][index] = value
                invalid.append((f"{group}/{index}/{value}", values["parameter"],
                                values["state"], values["input"]))
    for index in range(7):
        parameters = p.copy()
        parameters[index] = -1
        invalid.append((f"negative-parameter/{index}", parameters, [0, 0], base_input))
        if index >= 4:
            parameters = p.copy()
            parameters[index] = 0
            invalid.append((f"zero-limit-rate/{index}", parameters, [0, 0], base_input))
    invalid.extend([
        ("zero-period", p, [0, 0], [1, 2, 0, 0, 0, 0, 0]),
        ("negative-period", p, [0, 0], [1, 2, 0, 0, -1, 0, 0]),
        ("zero-ki-state", [1, 0, 1, 0, 10, 10, 20], [1, 0], base_input),
        ("binary32-overflow", p, [0, 0], [10, 0, -3e38, 0, 50e-6, 0, 0]),
    ])
    for name, parameters, state, inputs in invalid:
        status, out = step(parameters, state, inputs)
        if status != 1 or any(out):
            failures.append({"name": name, "reason": "error contract mismatch"})
    null_output = library.oeal_pi_step_f32(None, None, None, None)
    if null_output != 1:
        failures.append({"name": "null-output", "reason": "null not rejected"})

    compiler = subprocess.check_output(["gcc", "--version"], text=True).splitlines()[0]
    report = {
        "passed": not failures,
        "evidence_level": "SIL_passed" if not failures else "model_simulated",
        "source_commit": os.environ.get("GITHUB_SHA", "unrecorded"),
        "compiler": compiler, "command": command, "flags": FLAGS,
        "source_sha256": digest(source),
        "header_sha256": digest(ROOT / "firmware/oeal_current_pi_f32.h"),
        "binary_sha256": digest(library_path), "vectors_sha256": digest(vector_path),
        "absolute_tolerance": ABSOLUTE, "relative_tolerance": RELATIVE,
        "hand_vector_count": len(vectors), "sequence_samples": 2000,
        "saturation_recovery_samples": 102, "invalid_case_count": len(invalid) + 1,
        "worst": worst, "errors": errors, "failures": failures,
        "limitations": [
            "binary32 host libm; target libm/FPU mode still needs PIL",
            "PI kernel only, not full FOC firmware or hard real-time validation",
        ],
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    print("p4-f32.json: " + json.dumps({
        key: report[key] for key in (
            "passed", "source_commit", "worst", "hand_vector_count",
            "sequence_samples", "invalid_case_count", "failures",
        )
    }, allow_nan=False))
    if failures:
        raise AssertionError("float32 SIL failed; retain the predeclared error budget")


if __name__ == "__main__":
    main()
