"""Compile the float PI for Cortex-M4F and inspect direct precision dependencies."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p5-f32"
OUT.mkdir(parents=True, exist_ok=True)
SOURCE = ROOT / "firmware/oeal_current_pi_f32.c"
OBJECT = OUT / "oeal_current_pi_f32.o"
FLAGS = [
    "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
    "-Wdouble-promotion", "-Wconversion", "-ffp-contract=off",
    "-mcpu=cortex-m4", "-mthumb", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard",
    "-ffunction-sections", "-fdata-sections", "-fstack-usage",
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


command = ["arm-none-eabi-gcc", *FLAGS, "-c", str(SOURCE), "-o", str(OBJECT)]
subprocess.run(command, check=True)
compiler = subprocess.check_output(["arm-none-eabi-gcc", "--version"], text=True).splitlines()[0]
size = subprocess.check_output(["arm-none-eabi-size", "-A", str(OBJECT)], text=True)
symbols_text = subprocess.check_output(["arm-none-eabi-nm", "-u", str(OBJECT)], text=True)
symbols = [line.split()[-1] for line in symbols_text.splitlines() if line.split()]
forbidden = [
    symbol for symbol in symbols
    if symbol.startswith("__aeabi_d") or symbol in {"expm1", "hypot", "fmax", "fabs"}
]
disassembly = subprocess.check_output(["arm-none-eabi-objdump", "-d", str(OBJECT)], text=True)
(OUT / "object-size.txt").write_text(size)
(OUT / "undefined-symbols.txt").write_text(symbols_text)
(OUT / "disassembly.txt").write_text(disassembly)
double_report = ROOT / "outputs/p5/report.json"
comparison = None
if double_report.exists():
    comparison = {
        "double_object_size_report": json.loads(double_report.read_text())["object_size_report"],
        "float_object_size_report": size,
        "meaning": "relocatable object sections only; excludes linked libraries and startup",
    }
report = {
    "target": "STM32G474 Cortex-M4F", "source_commit": os.environ.get("GITHUB_SHA"),
    "compiler": compiler, "command": command, "cross_compile_passed": not forbidden,
    "source_sha256": digest(SOURCE),
    "header_sha256": digest(ROOT / "firmware/oeal_current_pi_f32.h"),
    "object_sha256": digest(OBJECT), "object_size_report": size,
    "undefined_symbols": symbols, "forbidden_double_dependencies": forbidden,
    "double_float_comparison": comparison,
    "p5_gate_passed": False, "pil_status": "not_run", "hardware_measurements": None,
    "limitations": [
        "direct object dependencies checked; libm internals are not inspected",
        "not linked firmware, no target execution, no 50 us guarantee",
        "target FPU rounding/flush mode and libm still require independent PIL",
    ],
}
(OUT / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
print("p5-f32.json: " + json.dumps(report, allow_nan=False))
if forbidden:
    raise AssertionError("unexpected direct double precision dependency in float PI")
