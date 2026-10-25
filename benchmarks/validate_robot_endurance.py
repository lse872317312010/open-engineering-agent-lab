"""Fixed longer-duration joint holdouts; preserve failures and full raw evidence."""

import argparse
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from oeal.experiments import run_experiment
from oeal.ir import document_hash
from oeal.studies import recompute, validate_study

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



def run_case(document):
    OUT.mkdir(parents=True, exist_ok=True)
    destination = OUT / document["id"]
    destination.mkdir(exist_ok=True)
    (destination / "input.json").write_text(json.dumps(document, indent=2))
    try:
        if not (ASSETS / "ur5e/ur5e.xml").exists():
            from validate_open_models import upstream_inputs

            upstream_inputs()
        result = run_experiment(document, ASSETS)
        with gzip.open(destination / "result.json.gz", "wt", encoding="utf-8") as handle:
            json.dump(result, handle, allow_nan=False)
        metrics, numeric, goal = recompute(document, validate_study(result))
        item = dict(id=document["id"], input_sha256=document_hash(document),
                    raw_sha256=result["raw_sha256"], metrics=metrics,
                    numeric_passed=numeric, goal_passed=goal, passed=bool(numeric and goal))
    except Exception as error:
        item = dict(id=document["id"], input_sha256=document_hash(document), passed=False,
                    error=f"{type(error).__name__}: {error}")
    (destination / "summary.json").write_text(json.dumps(item, indent=2, allow_nan=False))
    print("robot-endurance-case.json: " + json.dumps(item, allow_nan=False), flush=True)


def collect():
    reports, trajectories = [], {}
    for document in build_cases():
        destination = OUT / document["id"]
        if json.loads((destination / "input.json").read_text()) != document:
            raise AssertionError("fixed robot endurance input differs")
        item = json.loads((destination / "summary.json").read_text())
        if item.get("error"):
            reports.append(item)
            continue
        with gzip.open(destination / "result.json.gz", "rt", encoding="utf-8") as handle:
            result = json.load(handle)
        metrics, numeric, goal = recompute(document, validate_study(result))
        if result["experiment_sha256"] != document_hash(document):
            raise AssertionError("endurance experiment hash mismatch")
        item.update(metrics=metrics, numeric_passed=numeric, goal_passed=goal,
                    passed=bool(numeric and goal))
        joint = result["streams"]["joint"]
        rows = np.asarray(joint["samples"])
        trajectories[document["id"]] = rows[:, [0, joint["columns"].index("joint_angle_rad")]]
        # Display samples only; gate uses full result above.
        reference = rows[:, joint["columns"].index("reference_rad")]
        indices = sorted(set(range(0, len(rows), 10)) | {len(rows) - 1})
        item["display"] = [[float(rows[i, 0]), float(rows[i, 1]), float(reference[i])]
                           for i in indices]
        reports.append(item)
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
                   "original nine cases from PR #15; no new tuning or threshold changes",
                   "2 s robot horizon, separate from one-hour prescribed thermal replay",
                   "step-halving is consistency, not independent robot truth",
                   "full robot energy closure remains diagnostic in these original cases"],
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    print("robot-endurance.json: " + json.dumps(dict(
        passed=passed, cases=len(reports), coarse_fine_difference_rad=difference,
        failed=[c["id"] for c in reports if not c["passed"]]
    )), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=[d["id"] for d in build_cases()])
    parser.add_argument("--collect", action="store_true")
    args = parser.parse_args()
    if args.case:
        run_case(next(d for d in build_cases() if d["id"] == args.case))
    else:
        if not args.collect:
            for document in build_cases():
                run_case(document)
        collect()
