"""Bounded optimizer proposals; frozen goals; independent switching/payload validation."""

import copy
import json
from pathlib import Path

import mujoco
import numpy as np
import optuna

from oeal.agent_tools import create_experiment_tools
from oeal.backends.robot import load_robot
from oeal.design_analysis import (
    analyze_design,
    independent_checks,
    screen_designs,
    sensitivity,
)
from oeal.ir import document_hash
from oeal.studies import resolve_assets

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/design"
ASSETS = ROOT / "outputs/open-models"


def change(spec, key, value):
    result = copy.deepcopy(spec)
    result["settings"][key] = value if type(value) is bool else {
        "value": value, "unit": {
            "backlash_rad": "rad", "payload_kg": "kg", "macro_step_s": "s"
        }[key],
    }
    return result


def preview(result):
    stream = result["streams"]["joint"]
    rows = np.asarray(stream["samples"])
    keep = np.unique(np.r_[np.arange(0, len(rows), 4), len(rows) - 1])
    return {"columns": stream["columns"], "units": stream["units"],
            "samples": rows[keep].tolist(), "raw_sha256": result["raw_sha256"]}


def compact(result, verification, label, gains):
    return {
        "label": label, "gains": gains, "verification": verification,
        "experiment_sha256": result["experiment_sha256"],
        "trace": preview(result),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    reference_checks = independent_checks()
    source = ROOT / "examples/studies/ur5e_joint_v1.json"
    goal = json.loads(source.read_text())
    assets = resolve_assets("ur5e_joint_v1", ASSETS)
    robot, data, _ = load_robot(assets["ur5e/ur5e.xml"])
    matrix = np.zeros((robot.nv, robot.nv))
    mujoco.mj_fullM(robot, matrix, data.qM)
    index = int(robot.joint("shoulder_lift_joint").dofadr[0])
    inertia = float(matrix[index, index])
    screening = screen_designs(inertia)
    training_goal = change(goal, "pwm", False)
    training_goal["id"] = "joint-pd-training-average"
    tools = create_experiment_tools(training_goal, OUT / "training-ledger", ASSETS)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    sampler = optuna.samplers.TPESampler(seed=20261023, n_startup_trials=5)
    study = optuna.create_study(direction="minimize", sampler=sampler)
    study.enqueue_trial({"kp": 150.0, "kd": 20.0})
    seeds = []
    for item in screening:
        pair = (float(item["kp"]), float(item["kd"]))
        if pair != (150.0, 20.0) and item["stable"] and pair not in seeds:
            seeds.append(pair)
        if len(seeds) == 4:
            break
    for kp, kd in seeds:
        study.enqueue_trial({"kp": kp, "kd": kd})
    trials = []

    def objective(trial):
        kp = trial.suggest_float("kp", 50, 1200)
        kd = trial.suggest_float("kd", 5, 100)
        candidate = tools.propose_change({
            "outer_kp_nm_per_rad": kp, "outer_kd_nms_per_rad": kd,
        })
        try:
            result = tools.run_experiment(candidate)
            verification = tools.verify_change(candidate, result)
        except (ValueError, RuntimeError, FloatingPointError) as error:
            failure = {
                "trial": trial.number, "gains": {"kp": kp, "kd": kd},
                "score": 1e6, "failure": str(error), "verification": {"passed": False},
            }
            trials.append(failure)
            tools.record_evidence(failure)
            print("design-trial-failed.json: " + json.dumps(failure), flush=True)
            return 1e6
        metrics = verification["metrics"]
        penalty = max(metrics["current_peak_a"] - 20, 0) * 0.1
        penalty += max(metrics["shaft_torque_peak_nm"] - 100, 0) * 0.01
        score = metrics["position_tail_error_rad"] + penalty
        entry = compact(result, verification, f"trial-{trial.number}", {"kp": kp, "kd": kd})
        entry["score"] = score
        entry["trial"] = trial.number
        trials.append(entry)
        print("design-trial.json: " + json.dumps({
            "trial": trial.number, "kp": kp, "kd": kd, "score": score,
            "passed": verification["passed"], "metrics": metrics,
        }), flush=True)
        return score

    study.optimize(objective, n_trials=8, n_jobs=1)
    best = study.best_params
    selected = {"outer_kp_nm_per_rad": best["kp"], "outer_kd_nms_per_rad": best["kd"]}
    validations = []
    for label, fixed in (
        ("switching-baseline", goal),
        ("switching-backlash", change(goal, "backlash_rad", 0.001)),
        ("switching-payload-holdout", change(goal, "payload_kg", 0.5)),
    ):
        fixed["id"] = label
        session = create_experiment_tools(fixed, OUT / (label + "-ledger"), ASSETS)
        baseline_candidate = session.propose_change({
            "outer_kp_nm_per_rad": 150.0, "outer_kd_nms_per_rad": 20.0,
        })
        baseline_result = session.run_experiment(baseline_candidate)
        baseline_check = session.verify_change(baseline_candidate, baseline_result)
        candidate = session.propose_change(selected)
        result = session.run_experiment(candidate)
        verification = session.verify_change(candidate, result)
        pair = {
            "id": label, "goal_sha256": document_hash(fixed),
            "fixed_settings": fixed["settings"],
            "baseline": compact(baseline_result, baseline_check, "original",
                                {"kp": 150, "kd": 20}),
            "optimized": compact(result, verification, "optimized", best),
            "comparison": session.compare_results(baseline_check, verification),
            "scope": "payload holdout excluded from training" if "payload" in label
            else "original high-fidelity switching/deadtime model",
        }
        validations.append(pair)
        print("design-validation.json: " + json.dumps({
            "id": label, "baseline": baseline_check["metrics"],
            "optimized": verification["metrics"], "passed": verification["passed"],
        }), flush=True)
    initial_error = validations[0]["baseline"]["verification"]["metrics"]["position_tail_error_rad"]
    final_error = validations[0]["optimized"]["verification"]["metrics"]["position_tail_error_rad"]
    improvement = 1 - final_error / initial_error
    report = {
        "passed": bool(validations[0]["optimized"]["verification"]["passed"]
                       and improvement >= 0.2),
        "scope": "optimizer-assisted offline design; not a hosted autonomous LLM",
        "optimizer": {"library": "Optuna 4.5.0", "sampler": "seeded TPE",
                      "seed": 20261023, "trials": 8, "n_jobs": 1},
        "training_fidelity": "average inverter, original robot mechanics, same 0.25 s target",
        "validation_fidelity": "switching PWM + dead time + voltage drop; frozen target/limits",
        "reference_checks": reference_checks, "training_goal": training_goal,
        "training_goal_sha256": document_hash(training_goal),
        "trials": trials, "best_gains": best, "validations": validations,
        "baseline_improvement_fraction": improvement,
        "linear_screening": screening,
        "linear_analysis": {
            "baseline": analyze_design(inertia, 150, 20),
            "optimized": analyze_design(inertia, best["kp"], best["kd"]),
        },
        "sensitivity": sensitivity(inertia, best["kp"], best["kd"]),
        "limits": [
            "linear analysis and Morris use a reduced equilibrium model",
            "one joint, fixed trajectory and bounded training search",
            "payload is one synthetic holdout, not a general robustness certificate",
            "all original model and device-heat limitations remain",
        ],
    }
    (OUT / "report-data.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    if not report["passed"]:
        raise AssertionError("fixed high-fidelity goal or improvement gate failed")
    print("design.json: " + json.dumps({
        "passed": report["passed"], "best_gains": best, "improvement": improvement,
        "holdout_passed": [p["optimized"]["verification"]["passed"] for p in validations],
    }), flush=True)


if __name__ == "__main__":
    main()
