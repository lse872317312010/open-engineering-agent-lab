"""Open JSON/CSV interface to the native FOC benchmark."""

import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from oeal import __version__
from oeal.foc import FOCConfig, simulate_foc
from oeal.metrics import b1_passes, current_step_metrics
from oeal.models import MotorParameters, PMSMState

COLUMNS = [
    "time_s", "id_a", "iq_a", "mechanical_speed_rad_s", "mechanical_angle_rad",
    "vd_v", "vq_v", "duty_a", "duty_b", "duty_c", "id_reference_a",
    "iq_reference_a", "voltage_limited",
]


def run_foc(config_path: Path, output_dir: Path):
    raw = config_path.read_bytes()
    config = json.loads(raw)
    unknown = set(config) - {"model", "control", "initial_state", "load_torque_nm"}
    if unknown:
        raise ValueError(f"unknown config fields: {sorted(unknown)}")
    motor = MotorParameters(**config["model"])
    settings = FOCConfig(**config["control"])
    initial = PMSMState(**config.get("initial_state", {}))
    trace = simulate_foc(motor, settings, initial, config.get("load_torque_nm", 0.0))
    metrics = current_step_metrics(
        trace.samples, settings.step_time_s, settings.iq_reference_a,
        settings.vdc_v / (3 ** 0.5),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_path = output_dir / "trace.csv"
    with trace_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        writer.writerows(trace.samples)
    summary = {
        "evidence_level": "model_simulated",
        "run_metadata": {
            "oeal_version": __version__, "config_sha256": hashlib.sha256(raw).hexdigest(),
            "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
            "integrator": "rk4_stationary_voltage_hold",
        },
        "model": asdict(motor), "control": asdict(settings),
        "metrics": metrics, "b1_acceptance_passed": b1_passes(metrics),
        "limitations": "Synthetic parameters; ideal average inverter; no hardware measurement.",
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    return trace_path, summary_path
