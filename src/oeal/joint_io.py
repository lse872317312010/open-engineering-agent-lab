"""Versioned JSON/CSV entry point for synthetic multi-physics joint studies."""

import csv
import hashlib
import json
from pathlib import Path

import numpy as np

from oeal.foc import FOCConfig
from oeal.models import MotorParameters
from oeal.multiphysics import InverterParameters, JointParameters, ThermalParameters, run_joint


def run_joint_file(config_path: Path, output_dir: Path):
    raw = config_path.read_bytes()
    config = json.loads(raw)
    allowed = {
        "version", "parameter_source", "motor", "control", "joint", "thermal",
        "inverter", "initial_temperature_c", "load_nm",
    }
    if set(config) - allowed or config.get("version") != "p6-0.1":
        raise ValueError("unsupported P6 config version or fields")
    if config.get("parameter_source") != "synthetic_research":
        raise ValueError("this example entry point expects explicit synthetic provenance")
    result = run_joint(
        MotorParameters(**config["motor"]), FOCConfig(**config["control"]),
        JointParameters(**config.get("joint", {})), ThermalParameters(**config.get("thermal", {})),
        InverterParameters(**config.get("inverter", {})), config.get("initial_temperature_c"),
        config.get("load_nm", 0.0),
    )
    data = result.pop("samples")
    output_dir.mkdir(parents=True, exist_ok=True)
    trace = output_dir / "trace.csv"
    with trace.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(result["columns"])
        writer.writerows(data)
    summary = {
        **result, "config_sha256": hashlib.sha256(raw).hexdigest(),
        "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
        "sample_count": len(data),
        "metrics": {"peak_winding_c": float(np.max(data[:, 7])),
                    "peak_board_c": float(np.max(data[:, 9])),
                    "peak_shaft_torque_nm": float(np.max(np.abs(data[:, 10]))),
                    "command_stopped": bool(data[:, -1].any())},
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False))
    return trace, output_dir / "summary.json"
