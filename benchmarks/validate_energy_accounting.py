"""Fixed-port energy cases; preserve raw streams and expose co-simulation defects."""

import copy
import json
import os
from pathlib import Path

import numpy as np

from oeal.energy import ENERGY_COLUMNS, recompute_balances
from oeal.experiments import run_experiment
from oeal.ir import document_hash
from oeal.studies import export_streams

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/energy"
ASSETS = ROOT / "outputs/open-models"


def quantity(value, unit):
    return {"value": value, "unit": unit}


def drive_case(name, **settings):
    base = json.loads((ROOT / "examples/studies/motulator_pmsm_v1.json").read_text())
    base["id"] = name
    base["settings"]["energy_consistent"] = True
    base["settings"].update(settings)
    return base


def robot_case(macro):
    base = json.loads((ROOT / "examples/studies/ur5e_joint_v1.json").read_text())
    base["id"] = "energy-robot-" + str(round(macro * 1e6))
    base["settings"].update({
        "energy_consistent": True, "duration_s": quantity(0.04, "s"),
        "position_step_rad": quantity(0.008, "rad"),
        "position_start_s": quantity(0.002, "s"), "position_ramp_s": quantity(0.012, "s"),
        "macro_step_s": quantity(macro, "s"),
    })
    return base


def compact(spec, result, title):
    keep = {name: result["streams"][name]
            for name in ("energy", "co_sim_energy") if name in result["streams"]}
    return {
        "id": spec["id"], "title": title, "input": spec,
        "input_sha256": result["experiment_sha256"], "raw_sha256": result["raw_sha256"],
        "numeric_passed": result["numeric_passed"], "goal_passed": result["goal_passed"],
        "metrics": result["metrics"], "streams": keep,
        "scope": "local drive + thermal boundary; robot interface is diagnostic",
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if not (ASSETS / "ur5e/ur5e.xml").exists():
        from validate_open_models import upstream_inputs

        upstream_inputs()
    cases = [
        ("平均逆变器", drive_case("energy-average", pwm=False)),
        ("PWM 开关", drive_case("energy-switching", pwm=True)),
        ("死区与阈值压降", drive_case(
            "energy-deadtime", pwm=True, deadtime_s=quantity(1e-6, "s"),
            device_drop_v=quantity(0.4, "V"),
        )),
        ("电容母线与额外器件支路", drive_case(
            "energy-capacitor", pwm=True, dc_bus="capacitor",
        )),
        ("外部负载驱动 / 回馈", drive_case(
            "energy-regeneration", pwm=False, duration_s=quantity(0.06, "s"),
            iq_reference_a=quantity(-2, "A"), load_nm=quantity(-2, "N*m"),
        )),
        *[("UR5e 宏步 " + str(round(m * 1e6)) + " μs", robot_case(m))
          for m in (0.0002, 0.0001, 0.00005)],
    ]
    reports, results = [], []
    for title, spec in cases:
        result = run_experiment(spec, ASSETS)
        destination = OUT / spec["id"]
        export_streams(result, destination)
        (destination / "input.json").write_text(json.dumps(spec, indent=2))
        (destination / "result.json").write_text(json.dumps(result, allow_nan=False))
        reports.append(compact(spec, result, title))
        results.append(result)
        print("energy-case.json: " + json.dumps({
            "id": spec["id"], "numeric_passed": result["numeric_passed"],
            "goal_passed": result["goal_passed"], "metrics": result["metrics"],
        }), flush=True)
        if not result["numeric_passed"]:
            raise AssertionError("fixed local energy gate failed: " + spec["id"])
    regen = np.asarray(results[4]["streams"]["energy"]["samples"])
    if regen[:, ENERGY_COLUMNS.index("source_w")].min() >= -0.1:
        raise AssertionError("regeneration case did not exercise negative source power")

    # Deliberate ledger fault, not a claimed physical simulation case. The source
    # branch remains measured in the original case; subtract its work in a copy.
    fault = copy.deepcopy(results[0]["streams"]["energy"])
    rows = np.asarray(fault["samples"])
    rows[:, ENERGY_COLUMNS.index("source_j")] -= rows[:, ENERGY_COLUMNS.index(
        "auxiliary_device_j"
    )]
    local, thermal, fault_metrics = recompute_balances(fault["columns"], rows)
    rows[:, ENERGY_COLUMNS.index("local_residual_j")] = local
    rows[:, ENERGY_COLUMNS.index("thermal_residual_j")] = thermal
    fault["samples"] = rows.tolist()
    if fault_metrics["energy_balance_abs_j"] <= fault_metrics["energy_balance_limit_j"]:
        raise AssertionError("missing DC-branch work was not detected")
    np.savetxt(OUT / "fault-missing-device-branch.csv", rows, delimiter=",",
               header=",".join(fault["columns"]), comments="")
    fault_demo = {
        "id": "fault-missing-device-branch", "title": "账本故障注入：漏记器件直流耗能",
        "source_raw_sha256": results[0]["raw_sha256"],
        "raw_sha256": document_hash(fault), "metrics": fault_metrics,
        "expected_passed": False, "streams": {"energy": fault},
        "scope": "post-processing fault injection; not a physical-model run",
    }
    report = {
        "passed": True, "source_commit": os.environ.get("GITHUB_SHA", "unrecorded"),
        "cases": reports, "fault_demo": fault_demo,
        "boundary": "DC feed port + linear PMSM + rotor + six thermal nodes",
        "local_gate": "max residual <= 2e-5 J + 2e-4 * absolute source work",
        "robot_scope": "200/100/50 us explicit torque exchange; residuals diagnostic",
        "parameters": {
            "additional_device_on_resistance_ohm": 0.02,
            "switching_energy_coefficient_j_per_a": 20e-6,
            "thermal_ambient_c": 25.0,
        },
        "limits": [
            "opt-in mode only; legacy sampled-heat cases retain their old semantics",
            "linear magnetic map, no core-loss or diode-front-end branch in this mode",
            "additional device loss is an equivalent DC shunt, not transistor physics",
            "robot interface and actuator-work quadrature defects are reported, not zeroed",
            "one joint, no fixture contact; no full-system conservation certificate",
            "synthetic parameters and simulation evidence; hardware is user-owned",
        ],
        "command": "python benchmarks/validate_energy_accounting.py",
    }
    (OUT / "report-data.json").write_text(json.dumps(report, ensure_ascii=False,
                                                   indent=2, allow_nan=False))
    print("energy.json: " + json.dumps({
        "passed": True, "cases": len(reports),
        "worst_local_residual_j": max(c["metrics"]["energy_balance_abs_j"] for c in reports),
        "robot_interface_residual_j": [
            c["metrics"]["interface_residual_j"] for c in reports if "robot" in c["id"]
        ],
        "negative_fault_detected": True,
    }), flush=True)


if __name__ == "__main__":
    main()
