"""Fixed one-second joint campaign; raw streams independently re-audited."""

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
from oeal.robustness import aligned_difference, tracking_metrics
from oeal.studies import export_streams, recompute, validate_study

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/joint-robustness"
ASSETS = ROOT / "outputs/open-models"
IDS = ("nominal", "reverse", "payload", "compliant", "electrical",
       "combined-holdout", "combined-fine")


def quantity(value, unit):
    return dict(value=value, unit=unit)


def specification(name):
    if name not in IDS:
        raise ValueError("unknown fixed campaign case")
    spec = json.loads((ROOT / "examples/studies/ur5e-midpoint.json").read_text())
    spec["id"], spec["seed"] = name, 20261026
    spec["budget"] = dict(control_ticks=20001, solver_evaluations=10000000)
    settings = spec["settings"]
    settings.update(duration_s=quantity(1.0, "s"), pwm=False,
                    macro_step_s=quantity(.0002, "s"),
                    position_step_rad=quantity(.08, "rad"),
                    position_start_s=quantity(.02, "s"), position_ramp_s=quantity(.12, "s"))
    if name in {"reverse", "electrical"}:
        settings["position_step_rad"] = quantity(-.08, "rad")
    if name == "payload" or name.startswith("combined"):
        settings["payload_kg"] = quantity(1.0, "kg")
    if name == "compliant":
        settings.update(position_step_rad=quantity(.12, "rad"),
                        shaft_stiffness_nm_per_rad=quantity(350, "N*m/rad"))
    if name in {"electrical", "combined-holdout", "combined-fine"}:
        settings.update(pwm=True, vdc_v=quantity(42, "V"))
        spec["model"]["parameters"].update(
            stator_resistance_ohm=quantity(.36, "ohm"),
            d_inductance_h=quantity(.00064, "H"), q_inductance_h=quantity(.00064, "H"))
    if name == "electrical":
        spec["model"]["parameters"]["flux_linkage_wb"] = quantity(.027, "Wb")
    if name == "compliant" or name.startswith("combined"):
        spec["model"]["parameters"]["inertia_kg_m2"] = quantity(6e-5, "kg*m^2")
    if name.startswith("combined"):
        settings.update(sensors=True, shaft_stiffness_nm_per_rad=quantity(750, "N*m/rad"))
    if name == "combined-fine":
        settings["macro_step_s"] = quantity(.0001, "s")
    return spec


def column(stream, name):
    return np.asarray(stream["samples"], dtype=float)[:, stream["columns"].index(name)]


def audit(spec, result):
    validate_study(result)
    metrics, numeric, goal = recompute(spec, result)
    streams = result["streams"]
    joint, energy, ledger = (streams[k] for k in ("joint", "energy", "co_sim_energy"))
    t = column(joint, "time_s")
    lt = column(ledger, "time_s")
    if not np.array_equal(t, lt):
        raise ValueError("robot ledger clock differs from actual joint clock")
    eindex = np.round(t / 50e-6).astype(int)
    if not np.allclose(column(energy, "time_s")[eindex], t, atol=1e-12, rtol=0):
        raise ValueError("energy clock mismatch")
    spring = column(joint, "elastic_energy_j")
    k = result["context"]["resolved_settings"]["shaft_stiffness_nm_per_rad"]
    if not np.allclose(spring, .5 * k * column(joint, "twist_rad") ** 2, atol=1e-12, rtol=0):
        raise ValueError("actual endpoint spring energy mismatch")
    robot_balance = (column(ledger, "robot_storage_delta_j")
                     - column(ledger, "robot_shaft_work_j")
                     - column(ledger, "holding_actuator_work_j")
                     - column(ledger, "passive_work_j"))
    interface = (column(energy, "load_work_j")[eindex]
                 - column(energy, "shaft_heat_import_j")[eindex]
                 - column(ledger, "robot_shaft_work_j") - (spring - spring[0]))
    extended = column(energy, "local_residual_j")[eindex] + interface - robot_balance
    for actual, name in ((robot_balance, "robot_balance_residual_j"),
                         (interface, "interface_residual_j"),
                         (extended, "extended_residual_j")):
        if not np.allclose(actual, column(ledger, name), atol=1e-10, rtol=0):
            raise ValueError("independent ledger mismatch: " + name)
    metrics.update(tracking_metrics(t, column(joint, "joint_angle_rad"),
                                    column(joint, "reference_rad"), duration_s=1.0))
    limit = .001 + 1e-4 * metrics["source_abs_energy_j"]
    reasons = []
    if not numeric:
        reasons.append("original numeric/local-energy/predictor gate")
    if not goal:
        reasons.append("original position/current/shaft goals")
    if metrics["hold_max_error_rad"] > .03:
        reasons.append("last 0.5 s maximum position error >0.03 rad")
    if max(np.abs(interface).max(), np.abs(extended).max()) > limit:
        reasons.append("extended/interface energy budget")
    return dict(passed=not reasons, failure_reasons=reasons, metrics=metrics,
                coupling_energy_limit_j=limit)


def fault_checks(spec, result):
    checks = {}
    for name in ("clock", "ledger"):
        corrupted = copy.deepcopy(result)
        stream = corrupted["streams"]["joint" if name == "clock" else "co_sim_energy"]
        if name == "clock":
            stream["samples"].pop()
        else:
            index = stream["columns"].index("interface_residual_j")
            stream["samples"][-1][index] += 10
        # Re-attest the changed data: verify semantics, not only a broken checksum.
        corrupted["raw_sha256"] = document_hash(corrupted["streams"])
        try:
            verdict = audit(spec, corrupted)
            checks[name] = not verdict["passed"]
        except ValueError:
            checks[name] = True
    return checks


def run(name):
    path = OUT / name
    path.mkdir(parents=True, exist_ok=True)
    spec = specification(name)
    (path / "input.json").write_text(json.dumps(spec, indent=2))
    if not (ASSETS / "ur5e/ur5e.xml").exists():
        from validate_open_models import upstream_inputs

        upstream_inputs()
    result = run_experiment(spec, ASSETS)
    with gzip.open(path / "result.json.gz", "wt", encoding="utf-8") as handle:
        json.dump(result, handle, allow_nan=False)
    export_streams(result, path / "raw")
    summary = dict(id=name, **audit(spec, result),
                   input_sha256=result["experiment_sha256"], raw_sha256=result["raw_sha256"],
                   context=result["context"], fault_detection=fault_checks(spec, result))
    summary["passed"] = summary["passed"] and all(summary["fault_detection"].values())
    (path / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False))
    print("joint-case.json: " + json.dumps(summary, allow_nan=False), flush=True)


def collect():
    summaries, series = [], {}
    for name in IDS:
        path = OUT / name
        spec = json.loads((path / "input.json").read_text())
        # Ensure matrix inputs cannot drift from the predeclared design.
        if spec != specification(name):
            raise AssertionError("campaign input changed: " + name)
        with gzip.open(path / "result.json.gz", "rt", encoding="utf-8") as handle:
            result = json.load(handle)
        verdict = audit(spec, result)
        original = json.loads((path / "summary.json").read_text())
        if original["raw_sha256"] != result["raw_sha256"]:
            raise AssertionError("matrix artifact provenance mismatch")
        summary = dict(original, **verdict)
        summary["passed"] &= all(original["fault_detection"].values())
        summaries.append(summary)
        chosen = {}
        for stream_name, stride in (("joint", 1), ("control", 20), ("co_sim_energy", 5)):
            stream = result["streams"][stream_name]
            samples = stream["samples"]
            indices = sorted(set(range(0, len(samples), stride)) | {len(samples) - 1})
            chosen[stream_name] = dict(stream, samples=[samples[i] for i in indices])
        series[name] = chosen
        if name.startswith("combined"):
            trace = result["streams"]["joint"]
            series[name]["alignment"] = np.column_stack((
                column(trace, "time_s"), column(trace, "joint_angle_rad")
            )).tolist()
    difference = aligned_difference(series["combined-holdout"].pop("alignment"),
                                    series["combined-fine"].pop("alignment"))
    passed = all(s["passed"] for s in summaries) and difference <= .001
    report = dict(passed=passed, source_commit=os.environ.get("GITHUB_SHA", "unrecorded"),
                  evidence_level="model_simulated", cases=summaries, series=series,
                  common_time_difference_rad=difference, common_time_limit_rad=.001,
                  sampling_note="display decimation only; all gates use full raw streams",
                  scope="known-parameter variants; frozen position PD; one driven joint",
                  limits=["not unknown motor-parameter mismatch robustness",
                          "one-second electromechanical study, not one-hour coupled simulation",
                          "no contact/backlash predictor certification or physical calibration"])
    (OUT / "report-data.json").write_text(json.dumps(report, ensure_ascii=False,
                                                   allow_nan=False))
    manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (Path(__file__), ROOT / "src/oeal/robustness.py",
                          ROOT / "docs/joint-robustness-contract.md")}
    (OUT / "source-manifest.json").write_text(json.dumps(manifest, indent=2))
    print("joint-campaign.json: " + json.dumps(dict(
        passed=passed, cases=len(summaries), common_time_difference_rad=difference,
        failed=[s["id"] for s in summaries if not s["passed"]]
    )), flush=True)
    # Build the failure report too; workflow enforces this stored verdict afterwards.


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=IDS)
    args = parser.parse_args()
    run(args.case) if args.case else collect()
