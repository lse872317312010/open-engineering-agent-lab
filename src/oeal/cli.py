"""Command-line interface designed for scripts and tool-using agents."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from oeal import __version__
from oeal.experiments import run_experiment
from oeal.foc_io import run_foc
from oeal.ir import validate_document
from oeal.joint_io import run_joint_file
from oeal.models import MotorParameters, PMSMInput, PMSMState, simulate


def run_simulation(config_path: Path, output_dir: Path) -> tuple[Path, Path]:
    config_text = config_path.read_text(encoding="utf-8")
    config: dict[str, Any] = json.loads(config_text)
    model = MotorParameters(**config["model"])
    command = PMSMInput(**config["input"])
    sim_config = config["simulation"]
    initial_state = PMSMState(**sim_config.get("initial_state", {}))
    trace = simulate(
        model,
        command,
        duration_s=float(sim_config["duration_s"]),
        step_s=float(sim_config["step_s"]),
        initial_state=initial_state,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    trace_path = output_dir / "trace.csv"
    summary_path = output_dir / "summary.json"
    with trace_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "time_s",
                "id_a",
                "iq_a",
                "mechanical_speed_rad_s",
                "mechanical_angle_rad",
                "electromagnetic_torque_nm",
            ]
        )
        for time_s, state, torque in zip(
            trace.times_s, trace.states, trace.torque_nm, strict=True
        ):
            writer.writerow([time_s, *state, torque])

    final = PMSMState.from_array(trace.states[-1])
    summary = {
        "run_metadata": {
            "oeal_version": __version__,
            "config_sha256": hashlib.sha256(config_text.encode("utf-8")).hexdigest(),
            "integrator": "fixed_step_rk4",
        },
        "model": asdict(model),
        "input": asdict(command),
        "simulation": {
            "duration_s": float(trace.times_s[-1]),
            "nominal_step_s": float(sim_config["step_s"]),
            "sample_count": int(trace.times_s.size),
        },
        "final_state": asdict(final),
        "metrics": {
            "peak_abs_id_a": float(abs(trace.states[:, 0]).max()),
            "peak_abs_iq_a": float(abs(trace.states[:, 1]).max()),
            "peak_abs_torque_nm": float(abs(trace.torque_nm).max()),
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return trace_path, summary_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oeal", description="Engineering simulation tools")
    commands = parser.add_subparsers(dest="command", required=True)
    simulation = commands.add_parser("simulate", help="run a JSON-defined PMSM simulation")
    simulation.add_argument("config", type=Path, help="path to a simulation JSON file")
    simulation.add_argument(
        "--output",
        type=Path,
        required=True,
        help="directory for CSV and JSON outputs",
    )
    foc = commands.add_parser("simulate-foc", help="run sampled FOC from JSON")
    foc.add_argument("config", type=Path)
    foc.add_argument("--output", type=Path, required=True)
    experiment = commands.add_parser("run-experiment", help="run a validated IR experiment")
    experiment.add_argument("config", type=Path)
    experiment.add_argument("--output", type=Path, required=True)
    validation = commands.add_parser("validate-spec", help="validate an IR document")
    validation.add_argument("config", type=Path)
    joint = commands.add_parser("simulate-joint", help="run a P6 coupled joint study")
    joint.add_argument("config", type=Path)
    joint.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "simulate":
        trace_path, summary_path = run_simulation(args.config, args.output)
        print(f"trace: {trace_path}")
        print(f"summary: {summary_path}")
        return 0
    if args.command == "simulate-foc":
        trace_path, summary_path = run_foc(args.config, args.output)
        print(f"trace: {trace_path}")
        print(f"summary: {summary_path}")
        return 0
    if args.command == "validate-spec":
        validate_document(json.loads(args.config.read_text(encoding="utf-8")))
        print("valid")
        return 0
    if args.command == "run-experiment":
        result = run_experiment(json.loads(args.config.read_text(encoding="utf-8")))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        return 0
    if args.command == "simulate-joint":
        trace_path, summary_path = run_joint_file(args.config, args.output)
        print(f"trace: {trace_path}")
        print(f"summary: {summary_path}")
        return 0
    return 2

