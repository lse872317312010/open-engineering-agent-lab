"""Compile a fixed C PI kernel and compare hand vectors and complete state transitions."""

import ctypes
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

from oeal.current_control import CurrentPIParameters, CurrentPIState, current_control_step
from oeal.ir import validate_document

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p4"
OUT.mkdir(parents=True, exist_ok=True)
SOURCE = ROOT / "firmware/oeal_current_pi.c"
LIBRARY = OUT / "liboeal_pi.so"
FLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O2"]
VECTOR_PATH = ROOT / "benchmarks/sil-vectors.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def python_step(p, state, inputs):
    result = current_control_step(
        CurrentPIParameters(*p), CurrentPIState(*state),
        reference_d_a=inputs[0], reference_q_a=inputs[1],
        measured_d_a=inputs[2], measured_q_a=inputs[3], period_s=inputs[4],
        feedforward_d_v=inputs[5], feedforward_q_v=inputs[6],
    )
    return [
        result.vd_v, result.vq_v, result.reference_d_a, result.reference_q_a,
        float(result.voltage_limited), float(result.current_reference_limited),
        result.next_state.integral_d_v, result.next_state.integral_q_v,
    ]


def main():
    command = ["gcc", *FLAGS, "-shared", "-fPIC", str(SOURCE), "-lm", "-o", str(LIBRARY)]
    subprocess.run(command, check=True)
    static = subprocess.run(
        ["gcc", *FLAGS, "-fanalyzer", "-fsyntax-only", str(SOURCE)],
        capture_output=True, text=True, check=True,
    )
    (OUT / "static-check.txt").write_text(static.stdout + static.stderr)
    library = ctypes.CDLL(str(LIBRARY))
    pointer = ctypes.POINTER(ctypes.c_double)
    library.oeal_pi_step.argtypes = [pointer, pointer, pointer, pointer]
    library.oeal_pi_step.restype = ctypes.c_int

    def c_step(p, state, inputs):
        pa = (ctypes.c_double * 7)(*p)
        st = (ctypes.c_double * 2)(*state)
        inp = (ctypes.c_double * 7)(*inputs)
        out = (ctypes.c_double * 8)(*([999.0] * 8))
        before = bytes(st)
        status = library.oeal_pi_step(pa, st, inp, out)
        if bytes(st) != before:
            raise AssertionError("C mutated old state")
        return status, list(out)

    vectors = json.loads(VECTOR_PATH.read_text())
    absolute = vectors["absolute_tolerance"]
    relative = vectors["relative_tolerance"]
    failures = []
    errors = []
    per_vector = []

    def compare(name, actual, expected):
        error = max(abs(a - b) for a, b in zip(actual, expected, strict=True))
        errors.append(error)
        per_vector.append({"name": name, "max_abs_error": error})
        if not all(math.isclose(a, b, abs_tol=absolute, rel_tol=relative)
                   for a, b in zip(actual, expected, strict=True)):
            failures.append({"name": name, "actual": actual, "expected": expected})

    for v in vectors["vectors"]:
        py = python_step(v["p"], v["state"], v["input"])
        status, native = c_step(v["p"], v["state"], v["input"])
        if status:
            failures.append({"name": v["name"], "error": "unexpected C rejection"})
            continue
        compare(v["name"] + "/python-hand", py, v["expected"])
        compare(v["name"] + "/C-hand", native, v["expected"])
        compare(v["name"] + "/python-C", native, py)

    p = [1.6, 600, 1.6, 600, 48 / math.sqrt(3), 10, 2000]
    py_state, c_state = [0.0, 0.0], [0.0, 0.0]
    for tick in range(2000):
        inputs = [
            3 * math.sin(tick * 0.013), 12 * math.cos(tick * 0.009),
            2 * math.sin(tick * 0.02), 3 * math.cos(tick * 0.017), 50e-6,
            5 * math.sin(tick * 0.005), 20 * math.cos(tick * 0.007),
        ]
        py = python_step(p, py_state, inputs)
        status, native = c_step(p, c_state, inputs)
        if status:
            failures.append({"name": f"sequence/{tick}", "error": "C rejection"})
            break
        compare(f"sequence/{tick}", native, py)
        py_state, c_state = py[6:], native[6:]

    invalid = []
    base_input = [1.0, 2.0, 0.0, 0.0, 50e-6, 0.0, 0.0]
    for index in range(7):
        for value in (math.nan, math.inf, -math.inf):
            inp = base_input.copy()
            inp[index] = value
            invalid.append((f"input/{index}/{value}", p, [0, 0], inp))
            parameters = p.copy()
            parameters[index] = value
            invalid.append((f"parameter/{index}/{value}", parameters, [0, 0], base_input))
    invalid.extend([
        ("zero-period", p, [0, 0], [1, 2, 0, 0, 0, 0, 0]),
        ("invalid-state", p, [math.inf, 0], base_input),
        ("zero-ki-state", [1, 0, 1, 0, 10, 10, 20], [1, 0], base_input),
        ("overflow", p, [0, 0], [10, 0, -1.7e308, 0, 50e-6, 0, 0]),
    ])
    for name, parameters, state, inputs in invalid:
        status, out = c_step(parameters, state, inputs)
        try:
            python_step(parameters, state, inputs)
            rejected = False
        except ValueError:
            rejected = True
        if status != 1 or not rejected or any(out):
            failures.append({"name": name, "error": "failure contract mismatch"})

    compiler = subprocess.check_output(["gcc", "--version"], text=True).splitlines()[0]
    report = {
        "evidence_level": "SIL_passed" if not failures else "model_simulated",
        "passed": not failures, "compiler": compiler, "command": command,
        "source_commit": os.environ.get("GITHUB_SHA", "unrecorded"),
        "source_sha256": digest(SOURCE),
        "header_sha256": digest(ROOT / "firmware/oeal_current_pi.h"),
        "binary_sha256": digest(LIBRARY), "vectors_sha256": digest(VECTOR_PATH),
        "absolute_tolerance": absolute, "relative_tolerance": relative,
        "hand_vector_count": len(vectors["vectors"]), "sequence_samples": 2000,
        "invalid_case_count": len(invalid), "max_abs_error": max(errors),
        "per_vector_errors": per_vector, "failures": failures,
        "limitations": ["double PI kernel only", "host SIL, not target timing",
                        "no float32/fixed-point or full FOC firmware equivalence"],
    }
    report_path = OUT / "report.json"
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False))
    artifact = {
        "version": "0.1", "kind": "CodeArtifact", "target": "host", "abi": "IEEE754-double",
        "compiler": compiler, "flags": FLAGS,
        "source_sha256": digest(SOURCE), "binary_sha256": digest(LIBRARY),
        "resource_report_sha256": digest(report_path),
    }
    validate_document(artifact)
    (OUT / "code-artifact.json").write_text(json.dumps(artifact, indent=2))
    print("p4.json: " + json.dumps({
        key: report[key] for key in (
            "passed", "source_commit", "max_abs_error", "hand_vector_count",
            "sequence_samples", "invalid_case_count", "compiler", "failures",
        )
    }, allow_nan=False))
    if failures:
        raise AssertionError("P4 SIL mismatch; see fixed vectors and report")


if __name__ == "__main__":
    main()
