"""Fair integrator/coupler comparisons with fixed energy and tracking goals."""

import json
import math
import os
from pathlib import Path

import numpy as np
from scipy.linalg import expm

from oeal.coupling import path_midpoint_exchange
from oeal.experiments import run_experiment
from oeal.studies import export_streams

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/coupling"
ASSETS = ROOT / "outputs/open-models"


def quantity(value, unit):
    return {"value": value, "unit": unit}


def spec(name, method, macro, *, integrator="rk4", payload=0.0, long=False):
    source = ROOT / "examples/studies/ur5e_joint_v1.json"
    result = json.loads(source.read_text())
    result["id"] = name
    result["settings"].update({
        "energy_consistent": True, "coupling_method": method,
        "robot_integrator": integrator, "macro_step_s": quantity(macro, "s"),
        "duration_s": quantity(0.25 if long else 0.04, "s"),
        "position_step_rad": quantity(0.08 if long else 0.008, "rad"),
        "position_start_s": quantity(0.02 if long else 0.002, "s"),
        "position_ramp_s": quantity(0.12 if long else 0.012, "s"),
        "payload_kg": quantity(payload, "kg"),
    })
    if long:
        result["settings"]["outer_kp_nm_per_rad"] = quantity(779.266681952671, "N*m/rad")
        result["settings"]["outer_kd_nms_per_rad"] = quantity(56.608067569927684, "N*m*s/rad")
    return result


def references():
    matrix = np.array([
        [0, 1, 0, 0], [-4000, -8, 4000, 8],
        [0, 0, 0, 1], [250, 0.5, -250, -0.5],
    ])
    initial = np.array([0.02, 0.1, 0, 0])
    exact = expm(matrix * 0.01) @ initial

    def stored(x):
        return 0.5 * 0.125 * x[1] ** 2 + x[3] ** 2 + 250 * (x[0] - x[2]) ** 2

    errors, balances = [], []
    for h in (0.001, 0.0005, 0.00025):
        x, heat = initial.copy(), 0.0
        for _ in range(round(0.01 / h)):
            q, v, ql, vl = x
            exchange = path_midpoint_exchange(q - ql, v - vl, 0, 8.5, h)
            if exchange.fallback:
                raise AssertionError("reference unexpectedly crossed an excluded branch")
            torque = exchange.torque_nm
            x = np.array([
                q + h * v - h * h * torque / (2 * 0.125), v - h * torque / 0.125,
                ql + h * vl + h * h * torque / 4, vl + h * torque / 2,
            ])
            heat += h * exchange.damping_power_w
        errors.append(float(np.linalg.norm(x - exact)))
        balances.append(abs(stored(x) + heat - stored(initial)))
    ratios = [errors[0] / errors[1], errors[1] / errors[2]]
    if max(balances) >= 1e-10 or not all(3.8 <= r <= 4.2 for r in ratios):
        raise AssertionError("independent two-mass midpoint reference failed")
    return {"passed": True, "state_errors": errors, "halving_error_ratios": ratios,
            "energy_identity_errors_j": balances,
            "scope": "isolated constant-inertia two-mass reference, not full robot truth"}


def compact(document, result):
    streams = {key: value for key, value in result["streams"].items()
               if key in {"joint", "co_sim_energy", "coupling"}}
    joint = streams["joint"]
    rows = np.asarray(joint["samples"])
    k = result["context"]["resolved_settings"]["shaft_stiffness_nm_per_rad"]
    actual = 0.5 * k * rows[:, joint["columns"].index("twist_rad")] ** 2
    observed = rows[:, joint["columns"].index("elastic_energy_j")]
    if not np.allclose(actual, observed, rtol=0, atol=1e-12):
        raise AssertionError("reported spring energy is not the actual endpoint storage")
    audit = streams["co_sim_energy"]
    values = np.asarray(audit["samples"])
    peak = int(np.argmax(np.abs(values[:, audit["columns"].index("interface_residual_j")])))
    diagnostic = {"interface_peak_time_s": float(values[peak, 0])}
    if "coupling" in streams:
        prediction = streams["coupling"]
        diagnostic["predictor_at_interface_peak"] = dict(zip(
            prediction["columns"], prediction["samples"][peak], strict=True
        ))
    return {
        "diagnostic": diagnostic,
        "id": document["id"], "input": document,
        "raw_sha256": result["raw_sha256"], "input_sha256": result["experiment_sha256"],
        "metrics": result["metrics"], "numeric_passed": result["numeric_passed"],
        "goal_passed": result["goal_passed"], "streams": streams,
        "coupling_parameters": result["context"]["coupling_parameters"],
        "energy_parameters": result["context"]["energy_parameters"],
    }


def comparison(left, right, label):
    old, new = left["metrics"], right["metrics"]
    interface = 1 - new["interface_residual_j"] / old["interface_residual_j"]
    extended = 1 - new["extended_residual_j"] / old["extended_residual_j"]
    return {"label": label, "baseline": left["id"], "predictor": right["id"],
            "interface_improvement_fraction": interface,
            "extended_improvement_fraction": extended,
            "passed": interface >= 0.75 and extended >= 0.75}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if not (ASSETS / "ur5e/ur5e.xml").exists():
        from validate_open_models import upstream_inputs

        upstream_inputs()
    checks = references()
    documents = [
        spec(method + "-" + str(round(h * 1e6)), method, h)
        for h in (0.0002, 0.0001, 0.00005)
        for method in ("jacobi", "midpoint_predictor")
    ]
    documents += [
        spec("legacy-implicitfast", "jacobi", 0.0002, integrator="implicitfast"),
        spec("payload-jacobi", "jacobi", 0.0002, payload=0.5),
        spec("payload-midpoint", "midpoint_predictor", 0.0002, payload=0.5),
        spec("long-jacobi", "jacobi", 0.0002, long=True),
        spec("long-midpoint", "midpoint_predictor", 0.0002, long=True),
    ]
    cases = []
    for document in documents:
        result = run_experiment(document, ASSETS)
        path = OUT / document["id"]
        export_streams(result, path)
        (path / "input.json").write_text(json.dumps(document, indent=2))
        (path / "result.json").write_text(json.dumps(result, allow_nan=False))
        item = compact(document, result)
        cases.append(item)
        print("coupling-case.json: " + json.dumps({
            "id": item["id"], "numeric_passed": item["numeric_passed"],
            "goal_passed": item["goal_passed"], "metrics": item["metrics"],
            "diagnostic": item["diagnostic"],
        }), flush=True)
        if not result["numeric_passed"] or not result["goal_passed"]:
            raise AssertionError("fixed coupling, energy or tracking goal failed")
    by_id = {c["id"]: c for c in cases}
    pairs = [
        comparison(by_id["jacobi-200"], by_id["midpoint_predictor-200"], "short-same-rk4"),
        comparison(by_id["payload-jacobi"], by_id["payload-midpoint"], "payload-holdout"),
        comparison(by_id["long-jacobi"], by_id["long-midpoint"], "long-frozen-gains"),
    ]
    errors = [by_id["midpoint_predictor-" + str(h)]["metrics"]["interface_residual_j"]
              for h in (200, 100, 50)]
    ratios = [errors[0] / errors[1], errors[1] / errors[2]]
    fine = by_id["midpoint_predictor-50"]["streams"]["joint"]
    fine_rows = np.asarray(fine["samples"])
    qindex = fine["columns"].index("joint_angle_rad")
    for item in cases[:6]:
        trace = item["streams"]["joint"]
        rows = np.asarray(trace["samples"])
        item["difference_to_fine_predictor_rad"] = float(np.max(np.abs(
            rows[:, trace["columns"].index("joint_angle_rad")]
            - np.interp(rows[:, 0], fine_rows[:, 0], fine_rows[:, qindex])
        )))
    passed = all(p["passed"] for p in pairs) and errors[2] <= 0.4 * errors[0]
    report = {
        "passed": passed, "source_commit": os.environ.get("GITHUB_SHA", "unrecorded"),
        "reference_checks": checks, "cases": cases, "comparisons": pairs,
        "predictor_interface_peak_j": errors,
        "observed_halving_orders": [math.log2(r) for r in ratios],
        "fixed_gate": "same-RK4 interface and extended peak reductions >=75%; fine/coarse <=0.4",
        "scope": "causal torque means and path-averaged prediction; no implicit system solve",
        "limits": [
            "no backlash, fixture or active constraints in the certified predictor cases",
            "unresolved fallbacks fail certification; resolved law transitions are recorded",
            "spring storage always uses actual endpoint deflection",
            "robot actuator-work quadrature and interface residuals remain explicit",
            "same-RK4 comparisons separate the integrator contribution",
            "short study 40 ms/+0.008 rad; long study 250 ms/+0.08 rad with frozen gains",
            "synthetic research parameters; no exact global conservation or hardware evidence",
        ],
    }
    (OUT / "report-data.json").write_text(json.dumps(report, ensure_ascii=False,
                                                   indent=2, allow_nan=False))
    print("coupling.json: " + json.dumps({
        "passed": passed, "cases": len(cases), "comparisons": pairs,
        "interface_peaks_j": errors, "observed_orders": report["observed_halving_orders"],
    }), flush=True)
    if not passed:
        raise AssertionError("predeclared predictor improvement or convergence gate failed")


if __name__ == "__main__":
    main()
