"""Frozen cyclic cases; separate simulation, raw audit and immutable aggregation."""

import argparse
import copy
import gzip
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np

from oeal.experiments import run_experiment
from oeal.ir import document_hash
from oeal.studies import model_parameters, recompute, resolved_settings, validate_study

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/cyclic"
IDS = ("nominal", "resistance", "inductance", "flux", "switching",
       "combined", "combined-fine", "legacy-step")
NOMINAL = dict(stator_resistance_ohm=.3, d_inductance_h=.0008,
               q_inductance_h=.0008, flux_linkage_wb=.03)
UNITS = dict(stator_resistance_ohm="ohm", d_inductance_h="H",
             q_inductance_h="H", flux_linkage_wb="Wb")
NAMES = dict(stator_resistance_ohm="R_s", d_inductance_h="L_d",
             q_inductance_h="L_q", flux_linkage_wb="psi_f")


def quantity(value, unit):
    return dict(value=value, unit=unit)


def specification(name):
    if name not in IDS:
        raise ValueError("unknown frozen cyclic case")
    d = json.loads((ROOT / "examples/studies/ur5e-midpoint.json").read_text())
    d.update(id="cycle-" + name, seed=20261026,
             controller_parameters={k: quantity(v, UNITS[k]) for k, v in NOMINAL.items()},
             budget=dict(control_ticks=25000, solver_evaluations=20000000))
    s = d["settings"]
    s.update(duration_s=quantity(1.22, "s"), position_start_s=quantity(.02, "s"),
             position_step_rad=quantity(.04, "rad"), position_cycle_period_s=quantity(.6, "s"),
             macro_step_s=quantity(.0002, "s"), pwm=False)
    changes = {}
    if name == "resistance" or name.startswith("combined") or name == "legacy-step":
        changes["stator_resistance_ohm"] = .36
    if name == "inductance" or name.startswith("combined") or name == "legacy-step":
        changes.update(d_inductance_h=.00064, q_inductance_h=.00064)
    if name == "flux" or name.startswith("combined") or name == "legacy-step":
        changes["flux_linkage_wb"] = .027
    d["model"]["parameters"] = {k: quantity(v, UNITS[k]) for k, v in changes.items()}
    if name in {"switching", "combined", "combined-fine", "legacy-step"}:
        s["pwm"] = True
    if name.startswith("combined") or name == "legacy-step":
        s.update(payload_kg=quantity(.5, "kg"), vdc_v=quantity(42, "V"), sensors=True)
    if name == "combined-fine":
        s["macro_step_s"] = quantity(.0001, "s")
    if name == "legacy-step":
        s.pop("position_cycle_period_s")
        s.update(duration_s=quantity(.25, "s"), position_step_rad=quantity(.08, "rad"),
                 position_ramp_s=quantity(.12, "s"))
    else:
        d["acceptance"].update(position_peak_error_rad=quantity(.03, "rad"),
                               position_rmse_rad=quantity(.02, "rad"))
    validate_study(d)
    return d


def column(stream, key):
    return np.asarray(stream["samples"], dtype=float)[:, stream["columns"].index(key)]


def verify_parameters(spec, result):
    context = result["context"]
    if context["resolved_settings"] != resolved_settings(spec):
        raise ValueError("actual settings differ from immutable input")
    if context["physical_machine"] != model_parameters(spec["model"]):
        raise ValueError("actual machine metadata differs from declared plant")
    for key, value in NOMINAL.items():
        if context["nominal_machine"][NAMES[key]] != value:
            raise ValueError("plant information leaked into frozen nominal controller")
    physical_r = model_parameters(spec["model"])["stator_resistance_ohm"]
    if context["energy_parameters"]["resistance_at_25c_ohm"] != physical_r:
        raise ValueError("energy used nominal rather than actual resistance")


def ledger_check(result):
    streams = result["streams"]
    joint, energy, ledger = (streams[k] for k in ("joint", "energy", "co_sim_energy"))
    t = column(joint, "time_s")
    if not np.array_equal(t, column(ledger, "time_s")):
        raise ValueError("ledger macro clock differs from actual motion")
    ei = np.round(t / 50e-6).astype(int)
    if not np.allclose(column(energy, "time_s")[ei], t, atol=1e-12, rtol=0):
        raise ValueError("energy clock mismatch")
    spring = column(joint, "elastic_energy_j")
    stiffness = result["context"]["resolved_settings"]["shaft_stiffness_nm_per_rad"]
    if not np.allclose(spring, .5 * stiffness * column(joint, "twist_rad") ** 2,
                       atol=1e-12, rtol=0):
        raise ValueError("spring energy is not actual endpoint storage")
    robot = (column(ledger, "robot_storage_delta_j") - column(ledger, "robot_shaft_work_j")
             - column(ledger, "holding_actuator_work_j") - column(ledger, "passive_work_j"))
    interface = (column(energy, "load_work_j")[ei]
                 - column(energy, "shaft_heat_import_j")[ei]
                 - column(ledger, "robot_shaft_work_j") - (spring - spring[0]))
    extended = column(energy, "local_residual_j")[ei] + interface - robot
    for values, key in ((interface, "interface_residual_j"), (extended, "extended_residual_j"),
                        (robot, "robot_balance_residual_j")):
        if not np.allclose(values, column(ledger, key), atol=1e-10, rtol=0):
            raise ValueError("independent energy ledger mismatch")
    return float(max(np.abs(interface).max(), np.abs(extended).max()))


def run(name):
    path = OUT / name
    path.mkdir(parents=True, exist_ok=True)
    document = specification(name)
    (path / "input.json").write_text(json.dumps(document, indent=2))
    try:
        from validate_open_models import upstream_inputs

        assets = ROOT / "outputs/open-models"
        if not (assets / "ur5e/ur5e.xml").exists():
            upstream_inputs()
        result = run_experiment(document, assets)
        with gzip.open(path / "result.json.gz", "wt", encoding="utf-8") as handle:
            json.dump(result, handle, allow_nan=False)
    except Exception as error:
        (path / "error.json").write_text(json.dumps(dict(error=str(error))))
        print("simulation-error: " + str(error), flush=True)


def audit(name):
    started = time.monotonic()
    path = OUT / name
    document = specification(name)
    summary = dict(id=name, input=document, passed=False, failure_reasons=[], streams={})
    try:
        if json.loads((path / "input.json").read_text()) != document:
            raise ValueError("worker input drift")
        with gzip.open(path / "result.json.gz", "rt", encoding="utf-8") as handle:
            result = json.load(handle)
        validate_study(result)
        if result["experiment_sha256"] != document_hash(document):
            raise ValueError("input attestation mismatch")
        verify_parameters(document, result)
        metrics, numeric, goal = recompute(document, result)
        peak = ledger_check(result)
        budget = .001 + 1e-4 * metrics["source_abs_energy_j"]
        if not numeric or not goal:
            summary["failure_reasons"].append("original numeric/physical or cyclic goals")
        if peak > budget:
            summary["failure_reasons"].append("interface/extended energy budget")
        # Change a physical reference and re-attest the complete altered stream.
        wrong = dict(result, streams=dict(result["streams"]))
        wrong["streams"]["joint"] = copy.deepcopy(result["streams"]["joint"])
        index = wrong["streams"]["joint"]["columns"].index("reference_rad")
        wrong["streams"]["joint"]["samples"][1][index] += .01
        wrong["raw_sha256"] = document_hash(wrong["streams"])
        detected = False
        try:
            recompute(document, wrong)
        except ValueError:
            detected = True
        leaked = dict(result, context=copy.deepcopy(result["context"]))
        leaked["context"]["nominal_machine"]["R_s"] = .36
        nominal_fault = False
        try:
            verify_parameters(document, leaked)
        except ValueError:
            nominal_fault = True
        if not detected or not nominal_fault:
            summary["failure_reasons"].append("independent fault detection")
        chosen = {}
        for key, stride in (("joint", 1), ("control", 20), ("co_sim_energy", 5)):
            stream = result["streams"][key]
            indices = sorted(set(range(0, len(stream["samples"]), stride))
                             | {len(stream["samples"]) - 1})
            chosen[key] = dict(stream, samples=[stream["samples"][i] for i in indices])
        joint = result["streams"]["joint"]
        np.savetxt(path / "joint.csv", np.asarray(joint["samples"]), delimiter=",",
                   header=",".join(joint["columns"]), comments="")
        summary.update(metrics=metrics, streams=chosen, context=result["context"],
                       raw_sha256=result["raw_sha256"], input_sha256=result["experiment_sha256"],
                       coupling_energy_limit_j=budget, reference_fault_detected=detected,
                       nominal_fault_detected=nominal_fault)
        summary["passed"] = not summary["failure_reasons"]
    except Exception as error:
        summary["failure_reasons"].append(type(error).__name__ + ": " + str(error))
    summary.update(audit_elapsed_s=time.monotonic() - started,
                   source_commit=os.environ.get("GITHUB_SHA", "unrecorded"),
                   evidence_level="model_simulated",
                   audit_stage="separate process, full serialized raw result re-read")
    (path / "audit.json").write_text(json.dumps(summary, allow_nan=False, ensure_ascii=False))
    files = [p for p in path.iterdir() if p.is_file() and p.name != "manifest.json"]
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (path / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("cycle-audit.json: " + json.dumps(dict(
        id=name, passed=summary["passed"], metrics=summary.get("metrics"),
        failure_reasons=summary["failure_reasons"], elapsed_s=summary["audit_elapsed_s"]
    )), flush=True)


def collect():
    cases = []
    for name in IDS:
        path = OUT / name
        manifest = json.loads((path / "manifest.json").read_text())
        for file, digest in manifest.items():
            if Path(file).name != file:
                raise ValueError("invalid manifest path")
            if hashlib.sha256((path / file).read_bytes()).hexdigest() != digest:
                raise ValueError("artifact changed after independent raw audit")
        item = json.loads((path / "audit.json").read_text())
        if item["input"] != specification(name):
            raise ValueError("frozen specification drift")
        cases.append(item)
    by_id = {case["id"]: case for case in cases}
    difference = None
    if all(by_id[n]["passed"] for n in ("combined", "combined-fine")):
        left, right = (by_id[n]["streams"]["joint"] for n in ("combined", "combined-fine"))
        difference = float(np.max(np.abs(column(left, "joint_angle_rad") - np.interp(
            column(left, "time_s"), column(right, "time_s"), column(right, "joint_angle_rad")
        ))))
    passed = all(c["passed"] for c in cases) and difference is not None and difference <= .001
    report = dict(passed=passed, cases=cases, difference_rad=difference,
                  source_commit=os.environ.get("GITHUB_SHA", "unrecorded"),
                  audit_policy="full raw audit per case; aggregate verifies immutable file hashes",
                  scope="two cycles; frozen nominal electrical parameters; one driven joint")
    (OUT / "report-data.json").write_text(json.dumps(report, ensure_ascii=False, allow_nan=False))
    print("cycle-campaign.json: " + json.dumps(dict(
        passed=passed, cases=len(cases), difference_rad=difference,
        failed=[c["id"] for c in cases if not c["passed"]]
    )), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=IDS)
    parser.add_argument("--audit", choices=IDS)
    args = parser.parse_args()
    if args.case:
        run(args.case)
    elif args.audit:
        audit(args.audit)
    else:
        collect()
