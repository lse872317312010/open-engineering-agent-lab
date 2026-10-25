"""Fixed longer-duration joint holdouts; preserve failures and full raw evidence."""

import copy
import gzip
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from oeal.experiments import run_experiment
from oeal.ir import document_hash
from oeal.studies import validate_study

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/robot-endurance"
ASSETS = ROOT / "outputs/open-models"
POSITION_DIFFERENCE_LIMIT_RAD = 0.001


def quantity(value, unit):
    return {"value": value, "unit": unit}


def build_cases():
    base = json.loads((ROOT / "examples/studies/ur5e_joint_v1.json").read_text())
    base["budget"] = {"control_ticks": 50000, "solver_evaluations": 20000000}
    base["settings"].update({
        "energy_consistent": True, "coupling_method": "midpoint_predictor",
        "robot_integrator": "rk4", "macro_step_s": quantity(0.0002, "s"),
        "outer_kp_nm_per_rad": quantity(779.266681952671, "N*m/rad"),
        "outer_kd_nms_per_rad": quantity(56.608067569927684, "N*m*s/rad"),
        "position_step_rad": quantity(0.08, "rad"),
        "position_start_s": quantity(0.02, "s"),
        "position_ramp_s": quantity(0.12, "s"),
        "duration_s": quantity(2.0, "s"),
    })
    variations = [
        ("baseline-1s", {"duration_s": quantity(1.0, "s")}),
        ("baseline-2s", {}),
        ("reverse-2s", {"position_step_rad": quantity(-0.08, "rad")}),
        ("payload-half-2s", {"payload_kg": quantity(0.5, "kg")}),
        ("payload-one-2s", {"payload_kg": quantity(1.0, "kg")}),
        ("soft-2s", {"shaft_stiffness_nm_per_rad": quantity(400, "N*m/rad")}),
        ("stiff-2s", {"shaft_stiffness_nm_per_rad": quantity(600, "N*m/rad")}),
        ("combined-2s", {"payload_kg": quantity(0.5, "kg"),
                         "shaft_stiffness_nm_per_rad": quantity(400, "N*m/rad")}),
        ("baseline-fine-2s", {"macro_step_s": quantity(0.0001, "s")}),
    ]
    cases = []
    for name, settings in variations:
        document = copy.deepcopy(base)
        document["id"] = "endurance-" + name
        document["settings"].update(settings)
        validate_study(document)
        cases.append(document)
    return cases


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if not (ASSETS / "ur5e/ur5e.xml").exists():
        from validate_open_models import upstream_inputs

        upstream_inputs()
    reports, trajectories = [], {}
    for document in build_cases():
        destination = OUT / document["id"]
        destination.mkdir(exist_ok=True)
        (destination / "input.json").write_text(json.dumps(document, indent=2))
        try:
            result = run_experiment(document, ASSETS)
            # Keep complete raw streams, units, provenance and independent metrics.
            with gzip.open(destination / "result.json.gz", "wt", encoding="utf-8") as handle:
                json.dump(result, handle, allow_nan=False)
            joint = result["streams"]["joint"]
            rows = np.asarray(joint["samples"])
            trajectories[document["id"]] = rows[:, [0, joint["columns"].index(
                "joint_angle_rad"
            )]]
            item = {"id": document["id"], "input_sha256": document_hash(document),
                    "raw_sha256": result["raw_sha256"], "metrics": result["metrics"],
                    "numeric_passed": result["numeric_passed"],
                    "goal_passed": result["goal_passed"],
                    "passed": bool(result["numeric_passed"] and result["goal_passed"])}
        except Exception as error:
            # Finish independent cases and upload failure evidence before failing CI.
            item = {"id": document["id"], "input_sha256": document_hash(document),
                    "passed": False, "error": f"{type(error).__name__}: {error}"}
        reports.append(item)
        print(json.dumps(item, allow_nan=False), flush=True)
    coarse = trajectories.get("endurance-baseline-2s")
    fine = trajectories.get("endurance-baseline-fine-2s")
    difference = None
    if coarse is not None and fine is not None:
        difference = float(np.max(np.abs(coarse[:, 1] - np.interp(
            coarse[:, 0], fine[:, 0], fine[:, 1]
        ))))
    passed = (all(case["passed"] for case in reports) and difference is not None
              and difference <= POSITION_DIFFERENCE_LIMIT_RAD)
    report = {
        "passed": passed, "cases": reports, "evidence_level": "model_simulated",
        "source_commit": os.environ.get("GITHUB_SHA", "unrecorded"),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "coarse_fine_max_position_difference_rad": difference,
        "coarse_fine_position_limit_rad": POSITION_DIFFERENCE_LIMIT_RAD,
        "limits": ["synthetic fixed plant; one driven joint and no contact/backlash",
                   "existing gain proposal frozen; no new tuning on holdout results",
                   "2 s robot horizon, separate from one-hour prescribed thermal replay",
                   "step-halving is a consistency check, not an independent robot truth",
                   "local drive energy only; full robot energy closure remains diagnostic"],
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    if not passed:
        raise AssertionError("fixed robot endurance holdout gate failed; see report.json")


if __name__ == "__main__":
    main()
