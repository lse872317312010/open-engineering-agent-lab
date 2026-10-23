"""Run ARM ELF in QEMU and independently verify raw target outputs."""

import hashlib
import json
import math
import os
import struct
import subprocess
from pathlib import Path

from validate_p4 import python_step
from validate_p4_f32 import ABSOLUTE, RELATIVE, f32

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/qemu-arm"
FLAGS = [
    "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
    "-Wdouble-promotion", "-Wconversion", "-ffp-contract=off",
    "-mcpu=cortex-m4", "-mthumb", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard",
    "-ffunction-sections", "-fdata-sections", "-fno-common",
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def value(word):
    return struct.unpack("<f", struct.pack("<I", word))[0]


def make_cases():
    vectors = json.loads((ROOT / "benchmarks/sil-vectors.json").read_text())["vectors"]
    cases = []
    def add(name, p, state, inputs, mode=0, expected=None, status=0):
        cases.append({
            "name": name, "p": f32(p), "state": f32(state), "input": f32(inputs),
            "mode": mode, "hand_expected": expected, "expected_status": status,
        })
    for v in vectors:
        add(v["name"], v["p"], v["state"], v["input"], expected=v["expected"])
    p = [1.6, 600, 1.6, 600, 48 / math.sqrt(3), 10, 2000]
    for tick in range(2000):
        add(f"sequence/{tick}", p, [0, 0], [
            3 * math.sin(tick * 0.013), 12 * math.cos(tick * 0.009),
            2 * math.sin(tick * 0.02), 3 * math.cos(tick * 0.017), 50e-6,
            5 * math.sin(tick * 0.005), 20 * math.cos(tick * 0.007),
        ], mode=1 if tick == 0 else 2)
    sat_p = [0, 10, 0, 10, 2, 10, 1e6]
    for tick in range(100):
        add(f"saturation/{tick}", sat_p, [0, 0], [10, 0, 0, 0, 0.1, 0, 0],
            mode=1 if tick == 0 else 2, expected=[2, 0, 10, 0, 1, 0, 2, 0])
    for tick, expected in enumerate((1.0, 0.0)):
        add(f"recovery/{tick}", sat_p, [0, 0], [-1, 0, 0, 0, 0.1, 0, 0],
            mode=2, expected=[expected, 0, -1, 0, 0, 0, expected, 0])
    base = [1, 2, 0, 0, 50e-6, 0, 0]
    for group, count in (("p", 7), ("input", 7), ("state", 2)):
        for index in range(count):
            for bad in (math.nan, math.inf, -math.inf):
                data = {"p": p.copy(), "input": base.copy(), "state": [0, 0]}
                data[group][index] = bad
                add(f"invalid/{group}/{index}/{bad}", data["p"], data["state"],
                    data["input"], status=1)
    for index in range(7):
        parameters = p.copy()
        parameters[index] = -1
        add(f"negative-p/{index}", parameters, [0, 0], base, status=1)
        if index >= 4:
            parameters = p.copy()
            parameters[index] = 0
            add(f"zero-p/{index}", parameters, [0, 0], base, status=1)
    add("zero-period", p, [0, 0], [1, 2, 0, 0, 0, 0, 0], status=1)
    add("negative-period", p, [0, 0], [1, 2, 0, 0, -1, 0, 0], status=1)
    add("zero-ki-state", [1, 0, 1, 0, 10, 10, 20], [1, 0], base, status=1)
    add("binary32-overflow", p, [0, 0], [10, 0, -3e38, 0, 50e-6, 0, 0], status=1)
    add("null-output", p, [0, 0], base, mode=3, status=1)
    return cases


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cases = make_cases()
    encoded = [{
        "name": c["name"], "p": list(map(bits, c["p"])),
        "state": list(map(bits, c["state"])), "input": list(map(bits, c["input"])),
        "mode": c["mode"], "expected_status": c["expected_status"],
    } for c in cases]
    (OUT / "input-bits.json").write_text(json.dumps(encoded, indent=2))
    rows = []
    for c in encoded:
        groups = [
            "{" + ",".join(f"0x{x:08x}U" for x in c[key]) + "}"
            for key in ("p", "state", "input")
        ]
        rows.append("{" + ",".join(groups + [str(c["mode"]) + "U"]) + "}")
    header = (
        "#include <stdint.h>\n"
        "struct qemu_vector { uint32_t p[7], state[2], input[7], chain; };\n"
        f"#define QEMU_VECTOR_COUNT {len(cases)}U\n"
        "static const struct qemu_vector qemu_vectors[] = {\n"
        + ",\n".join(rows) + "\n};\n"
    )
    (OUT / "qemu_vectors.h").write_text(header)
    elf = OUT / "pi-qemu.elf"
    sources = [
        ROOT / "firmware/qemu/startup.S", ROOT / "firmware/qemu/pi_runner.c",
        ROOT / "firmware/oeal_current_pi_f32.c",
    ]
    linker = ROOT / "firmware/qemu/mps2.ld"
    build = [
        "arm-none-eabi-gcc", *FLAGS, "-nostartfiles", "--specs=nosys.specs",
        "-I", str(OUT), *map(str, sources), "-T", str(linker),
        "-Wl,--gc-sections", "-Wl,-Map=" + str(OUT / "pi-qemu.map"),
        "-lm", "-o", str(elf),
    ]
    subprocess.run(build, check=True)
    (OUT / "elf-size.txt").write_text(subprocess.check_output(
        ["arm-none-eabi-size", "-A", str(elf)], text=True
    ))
    command = [
        "qemu-system-arm", "-M", "mps2-an386", "-cpu", "cortex-m4",
        "-nographic", "-monitor", "none", "-serial", "none",
        "-semihosting-config", "enable=on,target=native", "-kernel", str(elf),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired as error:
        (OUT / "timeout.txt").write_text(str(error))
        raise AssertionError("QEMU timeout; missing target completion") from error
    (OUT / "stdout.txt").write_text(result.stdout)
    (OUT / "stderr.txt").write_text(result.stderr)
    raw = result.stdout + result.stderr
    lines = raw.splitlines()
    if result.returncode or "FAULT" in lines or "DONE" not in lines:
        raise AssertionError(f"target did not complete successfully: {result.returncode}")
    records = [line.split() for line in lines if line.startswith("V ")]
    if len(records) != len(cases):
        raise AssertionError("missing/extra target records")
    modes = [line.split()[-1] for line in lines if line.startswith("FPSCR ")]
    if len(modes) != 1:
        raise AssertionError("missing target FPU mode")
    failures, errors = [], []
    previous = [0.0, 0.0]
    worst = {"max_abs_error": 0.0}
    def compare(name, actual, expected):
        nonlocal worst
        finite = all(math.isfinite(x) for x in actual)
        error = max(abs(a - b) for a, b in zip(actual, expected, strict=True)) if finite else None
        errors.append({"name": name, "max_abs_error": error})
        if error is not None and error > worst["max_abs_error"]:
            worst = {"name": name, "max_abs_error": error}
        if not finite or not all(
            a == b if col in (4, 5) else math.isclose(
                a, b, abs_tol=ABSOLUTE, rel_tol=RELATIVE
            ) for col, (a, b) in enumerate(zip(actual, expected, strict=True))
        ):
            failures.append({"name": name, "reason": "numeric/flag mismatch"})
    for index, (case, fields) in enumerate(zip(cases, records, strict=True)):
        if len(fields) != 11 or int(fields[1], 16) != index:
            raise AssertionError("bad, duplicate or reordered target record")
        status = int(fields[2], 16)
        actual = [value(int(word, 16)) for word in fields[3:]]
        if status != case["expected_status"]:
            failures.append({"name": case["name"], "reason": "status mismatch"})
            continue
        if status:
            if any(actual):
                failures.append({"name": case["name"], "reason": "error output not zero"})
            continue
        state = previous if case["mode"] == 2 else case["state"]
        reference = python_step(case["p"], state, case["input"])
        compare(case["name"] + "/python", actual, reference)
        if case["hand_expected"] is not None:
            compare(case["name"] + "/hand", actual, case["hand_expected"])
        previous = reference[6:]
    report = {
        "evidence_kind": "processor_emulated", "processor_validation_passed": not failures,
        "hardware_measured": False, "machine": "mps2-an386", "cpu": "cortex-m4",
        "fpscr_hex": modes[0], "source_commit": os.environ.get("GITHUB_SHA"),
        "qemu_version": subprocess.check_output(
            ["qemu-system-arm", "--version"], text=True
        ).splitlines()[0],
        "compiler": subprocess.check_output(
            ["arm-none-eabi-gcc", "--version"], text=True
        ).splitlines()[0],
        "build_command": build, "run_command": command,
        "absolute_tolerance": ABSOLUTE, "relative_tolerance": RELATIVE,
        "vector_count": len(cases), "invalid_count": sum(c["expected_status"] for c in cases),
        "worst": worst, "failures": failures, "per_sample_errors": errors,
        "artifact_hashes": {
            str(p.relative_to(ROOT)): digest(p)
            for p in [*sources, linker, elf, OUT / "qemu_vectors.h",
                      OUT / "input-bits.json", OUT / "stdout.txt", OUT / "stderr.txt",
                      ROOT / "benchmarks/sil-vectors.json"]
        },
        "limitations": ["virtual MPS2, not STM32 peripherals",
                        "no actual MCU execution time/WCET or hardware PIL evidence"],
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    print("qemu-arm.json: " + json.dumps({
        key: report[key] for key in (
            "processor_validation_passed", "source_commit", "vector_count",
            "invalid_count", "fpscr_hex", "worst", "failures",
        )
    }, allow_nan=False))
    if failures:
        raise AssertionError("ARM processor emulation verification failed")


if __name__ == "__main__":
    main()
