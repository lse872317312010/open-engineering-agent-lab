"""Predeclared independent P6 references, holdout calibration and bounded uncertainty."""

import hashlib
import json
import math
import os
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.linalg import expm

from oeal.calibration import fit_rc, simulate_rc
from oeal.foc import FOCConfig
from oeal.models import MotorParameters
from oeal.multiphysics import (
    InverterParameters,
    JointParameters,
    ThermalParameters,
    coupled_rhs,
    joint_energy,
    joint_rhs,
    losses,
    rk4,
    run_joint,
    thermal_rhs,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p6"
MOTOR = MotorParameters(0.3, 0.0008, 0.0008, 0.03, 7, 0.002, 1e-5)


def save(name, document):
    (OUT / name).write_text(json.dumps(document, indent=2, allow_nan=False) + "\n")


def references():
    motor = replace(MOTOR, viscous_friction_nms=0)
    joint = JointParameters(
        damping_nms=0, motor_coulomb_nm=0, load_coulomb_nm=0,
        load_viscous_nms=0, transmission_error_rad=0,
    )
    x0 = np.array([0.02, 0.2, 0.0, -0.01])
    x = x0.copy()
    for tick in range(1000):
        x = rk4(lambda t, s: joint_rhs(s, motor, joint, 0, 0), tick * 1e-4, x, 1e-4)
    energy_error = abs(joint_energy(x, motor, joint) - joint_energy(x0, motor, joint))
    # Independent linear mechanical A matrix, not the implementation's RHS.
    n, k = joint.ratio, joint.stiffness_nm_per_rad
    jm, jl = motor.inertia_kg_m2, joint.load_inertia_kg_m2
    matrix = np.array([[0, 1, 0, 0], [-k / n**2 / jm, 0, k / n / jm, 0],
                       [0, 0, 0, 1], [k / n / jl, 0, -k / jl, 0]])
    mechanical_error = float(np.max(np.abs(x - expm(matrix * 0.1) @ x0)))

    thermal = ThermalParameters()
    cw, cc, cb = thermal.winding_j_per_k, thermal.case_j_per_k, thermal.board_j_per_k
    gw = 1 / thermal.winding_case_k_per_w
    gc = 1 / thermal.case_ambient_k_per_w
    gb = 1 / thermal.board_case_k_per_w
    ga = 1 / thermal.board_ambient_k_per_w
    augmented = np.zeros((4, 4))
    augmented[:3, :3] = [
        [-gw / cw, gw / cw, 0],
        [gw / cc, -(gw + gb + gc) / cc, gb / cc],
        [0, gb / cb, -(gb + ga) / cb],
    ]
    augmented[:3, 3] = [
        10 / cw, (2 + gc * thermal.ambient_c) / cc,
        (5 + ga * thermal.ambient_c) / cb,
    ]
    temperatures = np.full(3, 25.0)
    for tick in range(1000):
        temperatures = rk4(
            lambda t, s: thermal_rhs(s, thermal, 10, 5, 2), tick * 0.1, temperatures, 0.1
        )
    exact = (expm(augmented * 100) @ np.array([25, 25, 25, 1]))[:3]
    thermal_error = float(np.max(np.abs(temperatures - exact)))

    # Independent nine-state transcription for constant stationary 0+j3 V.
    jp = JointParameters()
    tp = ThermalParameters()
    def independent(t, y):
        d, q, theta, wm, theta_l, wl, tw, tc, tb = y
        a = 1 / jp.ratio - jp.transmission_error_rad * math.cos(theta)
        strain = theta / jp.ratio - theta_l - jp.transmission_error_rad * math.sin(theta)
        strain_rate = a * wm - wl
        torque = jp.stiffness_nm_per_rad * strain + jp.damping_nms * strain_rate
        mf = MOTOR.viscous_friction_nms * wm + jp.motor_coulomb_nm * math.tanh(wm / 0.1)
        lf = jp.load_viscous_nms * wl + jp.load_coulomb_nm * math.tanh(wl / 0.1)
        te = 1.5 * 7 * 0.03 * q
        resistance = 0.3 * (1 + 0.00393 * (tw - 25))
        copper = 1.5 * resistance * (d*d + q*q)
        board = 1.5 * 0.02 * (d*d + q*q) + 0.00002 * 120000 * math.hypot(d, q)
        friction = mf * wm + lf * wl + jp.damping_nms * strain_rate**2
        vd, vq = 3 * math.sin(7 * theta), 3 * math.cos(7 * theta)
        return [
            (vd - resistance * d + 7 * wm * 0.0008 * q) / 0.0008,
            (vq - resistance * q - 7 * wm * (0.0008 * d + 0.03)) / 0.0008,
            wm, (te - a * torque - mf) / 0.002, wl, (torque - lf) / 0.02,
            (copper - (tw - tc) / 0.8) / 60,
            ((tw - tc) / 0.8 + (tb - tc) / 1.2 + friction - (tc - 25) / 2) / 200,
            (board - (tb - tc) / 1.2 - (tb - 25) / 4) / 25,
        ]
    initial = np.array([0.0] * 6 + [25.0] * 3)
    reference = solve_ivp(independent, (0, 0.005), initial, method="DOP853",
                          rtol=1e-12, atol=1e-13)
    native = initial.copy()
    for tick in range(500):
        native = rk4(
            lambda t, y: coupled_rhs(
                t, y, MOTOR, jp, tp, FOCConfig(), InverterParameters(), 0, 3, 0
            ), tick * 1e-5, native, 1e-5,
        )
    coupled_error = float(np.max(np.abs(native - reference.y[:, -1])))
    passed = (energy_error < 1e-6 and mechanical_error < 1e-6
              and thermal_error < 1e-6 and coupled_error < 2e-5 and reference.success)
    result = {"passed": bool(passed), "mechanical_energy_error_j": energy_error,
              "mechanical_matrix_error": mechanical_error, "thermal_expm_error_k": thermal_error,
              "coupled_dop853_error": coupled_error}
    save("references.json", result)
    if not passed:
        raise AssertionError("independent P6 reference failed")
    return result


def thermal_experiment(current_a, ambient_c=25.0, resistance_factor=1.0):
    p = ThermalParameters(
        ambient_c=ambient_c, winding_case_k_per_w=0.8 * resistance_factor,
        case_ambient_k_per_w=2 * resistance_factor,
    )
    dt = 0.05
    state = np.full(3, ambient_c)
    rows = []
    for tick in range(2401):
        t = tick * dt
        current = current_a if (tick // 400) % 3 != 2 else current_a * 0.2
        _, copper, board = losses(MOTOR, p, state[0], 0, current)
        rows.append([t, *state, current, copper, board])
        if tick == 2400:
            break
        state = rk4(
            lambda time, s, held=current: thermal_rhs(s, p, *losses(MOTOR, p, s[0], 0, held)[1:]),
            t, state, dt,
        )
    return np.asarray(rows)


def calibration():
    rng = np.random.default_rng(20261023)
    train_power = np.tile(np.repeat([0, 5, 20, 3, 12, 0], 50), 6).astype(float)
    clean = simulate_rc(train_power, 1, 1.5, 80)
    measured = clean + rng.normal(0, 0.02, len(clean))
    fit = fit_rc(measured, train_power, 1)
    holdout_power = 10 + 7 * np.sin(np.arange(1200) / 53) + 2 * np.sin(np.arange(1200) / 11)
    actual = simulate_rc(holdout_power, 1, 1.5, 80)
    prediction = simulate_rc(holdout_power, 1, fit["resistance_k_per_w"], fit["capacity_j_per_k"])
    rmse = float(np.sqrt(np.mean((actual - prediction)**2)))
    repeated = []
    for seed in range(20):
        data = clean + np.random.default_rng(seed).normal(0, 0.02, len(clean))
        repeated.append(fit_rc(data, train_power, 1))
    r_error = abs(fit["resistance_k_per_w"] / 1.5 - 1)
    c_error = abs(fit["capacity_j_per_k"] / 80 - 1)
    passed = r_error < 0.05 and c_error < 0.05 and rmse < 0.15
    report = {
        "passed": passed, "source": "synthetic analytic RC; not real measurements",
        "seed": 20261023, "noise_std_k": 0.02, "fit": fit, "true_r": 1.5, "true_c": 80,
        "r_relative_error": r_error, "c_relative_error": c_error, "holdout_rmse_k": rmse,
        "train_samples": len(train_power), "holdout_samples": len(holdout_power),
        "noise_repetitions": repeated,
        "holdout": np.column_stack((np.arange(len(actual)), actual, prediction)).tolist(),
    }
    np.savetxt(OUT / "calibration-training.csv",
               np.column_stack((np.arange(len(clean)), measured, np.r_[train_power, 0.0])),
               delimiter=",", header="time_s,synthetic_temperature_c,power_w")
    np.savetxt(OUT / "calibration-holdout.csv",
               np.column_stack((np.arange(len(actual)), actual, prediction)),
               delimiter=",", header="time_s,analytic_c,predicted_c")
    save("calibration.json", report)
    if not passed:
        raise AssertionError("synthetic holdout calibration failed")
    return report


def scenarios():
    control = FOCConfig(duration_s=0.08)
    cases = [
        ("baseline", "基准关节", control, JointParameters(), ThermalParameters(),
         InverterParameters(), [25, 25, 25], 0.0),
        ("inverter", "母线纹波与平均死区", control, JointParameters(), ThermalParameters(),
         InverterParameters(0.08, 200, 1e-6, 0.4), [25, 25, 25], 0.0),
        ("hot", "热启动与阻值漂移", control, JointParameters(), ThermalParameters(ambient_c=45),
         InverterParameters(), [90, 70, 80], 1.0),
        ("compliant", "柔性传动与负载", control, JointParameters(stiffness_nm_per_rad=40),
         ThermalParameters(), InverterParameters(), [25, 25, 25], 2.0),
        ("low-bus", "低母线不可达目标",
         replace(control, vdc_v=4, iq_reference_a=12, current_limit_a=15),
         JointParameters(), ThermalParameters(),
         InverterParameters(), [25, 25, 25], 0.0),
        ("stop", "热阈值命令停机", control, JointParameters(), ThermalParameters(),
         InverterParameters(), [130, 60, 60], 0.0),
    ]
    reports = []
    baseline = None
    for key, title, settings, joint, thermal, inverter, initial, load in cases:
        result = run_joint(MOTOR, settings, joint, thermal, inverter, initial, load)
        data = result.pop("samples")
        np.savetxt(OUT / (key + ".csv"), data, delimiter=",", header=",".join(result["columns"]))
        finite = bool(np.all(np.isfinite(data)))
        violations = int(np.count_nonzero(data[:, 14] > data[:, 13] / math.sqrt(3) + 1e-9))
        tail_error = float(abs(data[-80:, 2].mean() - settings.iq_reference_a))
        result.update({
            "id": key, "title": title, "samples": data[::4].tolist(),
            "inputs": {"initial_temperature_c": initial, "load_nm": load},
            "metrics": {
                "q_tail_error_a": tail_error, "peak_winding_c": float(data[:, 7].max()),
                "peak_board_c": float(data[:, 9].max()),
                "peak_shaft_torque_nm": float(np.abs(data[:, 10]).max()),
                "voltage_violations": violations, "command_stopped": bool(data[:, -1].any()),
            },
            "numeric_passed": finite and violations == 0,
            "tracking_goal_passed": tail_error < 0.1 and not bool(data[:, -1].any()),
        })
        reports.append(result)
        if key == "baseline":
            baseline = data
    fine = run_joint(
        MOTOR, replace(control, integration_step_s=2.5e-6)
    )["samples"]
    convergence = float(np.max(np.abs(baseline[:, :10] - fine[:, :10])))
    passed = all(r["numeric_passed"] for r in reports) and convergence < 2e-4
    passed = passed and not next(r for r in reports if r["id"] == "low-bus")["tracking_goal_passed"]
    passed = passed and next(r for r in reports if r["id"] == "stop")["metrics"]["command_stopped"]
    thermal_cases = []
    for factor in (0.8, 1.0, 1.2):
        data = thermal_experiment(5, resistance_factor=factor)
        thermal_cases.append({"resistance_factor": factor, "samples": data.tolist()})
    stress = thermal_experiment(12, ambient_c=40)
    np.savetxt(OUT / "thermal-stress.csv", stress, delimiter=",",
               header="time_s,winding_c,case_c,board_c,current_a,copper_w,board_w")
    result = {
        "passed": bool(passed), "step_halving_max_state_difference": convergence,
        "cases": reports, "thermal_cases": thermal_cases,
        "thermal_stress": {"samples": stress.tolist(),
                           "within_illustrative_limits": bool(stress[:, 1].max() < 120
                                                             and stress[:, 3].max() < 100)},
        "thermal_scope": "120 s prescribed ideal-current envelope; not full 20 kHz FOC",
        "uncertainty_scope": "bounded +/-20% resistance scenarios, not confidence intervals",
    }
    save("inputs.json", {
        "parameter_source": "synthetic_research",
        "scenarios": [{"id": item["id"], "parameters": item["parameters"],
                       **item["inputs"]} for item in reports],
        "thermal_envelope": {"duration_s": 120, "step_s": 0.05,
                             "high_current_a": [5, 12], "ambient_c": [25, 40],
                             "high_duration_s": 40, "low_duration_s": 20,
                             "low_current_fraction": 0.2,
                             "correlated_resistance_factors": [0.8, 1.0, 1.2]},
        "calibration": {"source": "analytic single-node RC", "true_r": 1.5, "true_c": 80,
                        "step_s": 1, "ambient_c": 25, "seed": 20261023},
    })
    save("scenarios.json", result)
    if not passed:
        raise AssertionError("P6 scenario or convergence validation failed")
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    refs = references()
    fit = calibration()
    cases = scenarios()
    report = {
        "passed": bool(refs["passed"] and fit["passed"] and cases["passed"]),
        "source_commit": os.environ.get("GITHUB_SHA", "unrecorded"),
        "parameter_source": "synthetic_research", "evidence_level": "model_simulated",
        "elapsed_s": time.perf_counter() - start, "model": asdict(MOTOR),
        "inputs": "outputs/p6/inputs.json",
        "inputs_sha256": hashlib.sha256((OUT / "inputs.json").read_bytes()).hexdigest(),
        "command": "python benchmarks/validate_p6.py",
    }
    save("run.json", report)
    print("p6.json: " + json.dumps({**report, "references": refs,
                                    "holdout_rmse_k": fit["holdout_rmse_k"]}, allow_nan=False))


if __name__ == "__main__":
    main()
