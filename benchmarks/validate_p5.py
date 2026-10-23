"""Cross-compile only. Never flash, power or communicate with hardware."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from oeal.ir import validate_document

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p5"
OUT.mkdir(parents=True, exist_ok=True)
SOURCE = ROOT / "firmware/oeal_current_pi.c"
OBJECT = OUT / "oeal_current_pi.o"
FLAGS = [
    "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O2",
    "-mcpu=cortex-m4", "-mthumb", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard",
    "-ffunction-sections", "-fdata-sections", "-fstack-usage",
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


command = ["arm-none-eabi-gcc", *FLAGS, "-c", str(SOURCE), "-o", str(OBJECT)]
subprocess.run(command, check=True)
compiler = subprocess.check_output(["arm-none-eabi-gcc", "--version"], text=True).splitlines()[0]
size = subprocess.check_output(["arm-none-eabi-size", "-A", str(OBJECT)], text=True)
symbols = subprocess.check_output(["arm-none-eabi-nm", "-u", str(OBJECT)], text=True)
disassembly = subprocess.check_output(["arm-none-eabi-objdump", "-d", str(OBJECT)], text=True)
(OUT / "object-size.txt").write_text(size)
(OUT / "undefined-symbols.txt").write_text(symbols)
(OUT / "disassembly.txt").write_text(disassembly)
report = {
    "target": "STM32G474 Cortex-M4F", "source_commit": os.environ.get("GITHUB_SHA"),
    "compiler": compiler, "command": command, "cross_compile_passed": True,
    "source_sha256": digest(SOURCE), "object_sha256": digest(OBJECT),
    "object_size_report": size, "undefined_symbols": symbols,
    "p5_gate_passed": False, "pil_status": "not_run",
    "hardware_measurements": None,
    "ti_c2000_status": "not_run: target SDK/compiler/project not supplied",
    "blockers": [
        "board and existing firmware/HAL integration not supplied",
        "separate flashing/power authorization not supplied",
        "target execution/jitter/stack and linked Flash/RAM logs absent",
        "TI C2000 target and licensed toolchain configuration absent",
    ],
    "limitations": [
        "relocatable object, not a bootable or linked firmware image",
        "size is not final linked Flash/RAM; stack .su omits external libm/call chain",
        "double operations may use software helpers on Cortex-M4F",
        "host SIL and cross compilation cannot establish a 50 us target deadline",
    ],
}
report_path = OUT / "report.json"
report_path.write_text(json.dumps(report, indent=2, allow_nan=False))
artifact = {
    "version": "0.1", "kind": "CodeArtifact", "target": "STM32G474",
    "abi": "ARM EABI hard-float; IEEE754 double control kernel",
    "compiler": compiler, "flags": FLAGS, "source_sha256": digest(SOURCE),
    "binary_sha256": digest(OBJECT), "resource_report_sha256": digest(report_path),
}
validate_document(artifact)
(OUT / "code-artifact.json").write_text(json.dumps(artifact, indent=2))
print("p5.json: " + json.dumps(report, allow_nan=False))
