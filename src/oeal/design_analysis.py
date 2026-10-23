"""Optional linear perturbation analysis and reproducible Morris screening.

This reduced model starts at a gravity-compensated equilibrium. It is a screening
model, not a substitute for the nonlinear switching/robot validation.
"""

import control
import numpy as np
from SALib.analyze import morris as morris_analyze
from SALib.sample import morris as morris_sample


def joint_system(load_inertia, stiffness=500.0, bandwidth=1000.0, kp=150.0, kd=20.0):
    ratio, kt, motor_j, motor_b = 50.0, 0.315, 5e-5, 1e-5
    jm, jl, damping = motor_j * ratio ** 2, load_inertia, 1.0
    a = np.array([
        [0, 1, 0, 0, 0],
        [-stiffness / jm, -(damping + motor_b * ratio ** 2) / jm,
         stiffness / jm, damping / jm, ratio * kt / jm],
        [0, 0, 0, 1, 0],
        [stiffness / jl, damping / jl, -stiffness / jl, -damping / jl, 0],
        [0, 0, 0, 0, -bandwidth],
    ])
    b = np.array([[0], [0], [0], [0], [bandwidth / (ratio * kt)]])
    c = np.array([[0, 0, 1, 0, 0]])
    feedback = np.array([[0, 0, kp, kd, 0]])
    plant = control.ss(a, b, c, 0)
    closed = control.ss(a - b @ feedback, b * kp, c, 0)
    return plant, closed


def evaluate_reduced(load_inertia, kp, kd, stiffness=500.0, bandwidth=1000.0):
    _, closed = joint_system(load_inertia, stiffness, bandwidth, kp, kd)
    t = np.linspace(0, 0.25, 1001)
    reference = 0.08 * np.clip((t - 0.02) / 0.12, 0, 1)
    response = control.forced_response(closed, T=t, U=reference)
    values = np.asarray(response.outputs).reshape(-1)
    poles = np.asarray(control.poles(closed))
    error = float(np.mean(np.abs(values[t >= 0.225] - reference[t >= 0.225])))
    return {
        "tail_error_rad": error, "stable": bool(np.all(poles.real < 0)),
        "rightmost_pole_per_s": float(poles.real.max()),
        "poles": [[float(p.real), float(p.imag)] for p in poles],
        "samples": np.column_stack((t, values, reference)).tolist(),
    }


def independent_checks():
    time = np.linspace(0, 2, 201)
    response = control.step_response(control.tf([1], [1, 2]), T=time)
    error = float(np.max(np.abs(response.outputs - 0.5 * (1 - np.exp(-2 * time)))))
    problem = {"num_vars": 2, "names": ["x", "y"], "bounds": [[0, 1], [0, 1]]}
    samples = morris_sample.sample(problem, N=4, num_levels=4, seed=20261023)
    response = samples[:, 0] + 10 * samples[:, 1]
    analyzed = morris_analyze.analyze(
        problem, samples, response, num_levels=4, seed=20261023, print_to_console=False
    )
    effects = np.asarray(analyzed["mu_star"])
    effect_error = float(np.max(np.abs(effects - [1, 10])))
    report = {
        "step_reference_error": error, "morris_linear_effects": effects.tolist(),
        "morris_reference_error": effect_error,
        "passed": error < 1e-8 and effect_error < 1e-9,
    }
    if not report["passed"]:
        raise AssertionError(report)
    return report


def screen_designs(load_inertia):
    candidates = []
    for kp in (150, 300, 450, 600, 900, 1200):
        for kd in (5, 10, 15, 20, 35, 50, 75, 100):
            result = evaluate_reduced(load_inertia, kp, kd)
            candidates.append({
                "kp": kp, "kd": kd, "tail_error_rad": result["tail_error_rad"],
                "stable": result["stable"],
                "rightmost_pole_per_s": result["rightmost_pole_per_s"],
            })
    return sorted(candidates, key=lambda r: (not r["stable"], r["tail_error_rad"]))


def analyze_design(load_inertia, kp, kd):
    plant, _ = joint_system(load_inertia, kp=kp, kd=kd)
    loop = control.tf(plant) * control.tf([kd, kp], [1])
    gain_margin, phase_margin, _, crossover = control.margin(loop)
    omega = np.logspace(-1, 4, 250)
    response = control.frequency_response(loop, omega)
    return {
        "scope": "linear two-mass + first-order current loop about compensated equilibrium",
        "load_inertia_kg_m2": load_inertia,
        "gain_margin": float(gain_margin) if np.isfinite(gain_margin) else None,
        "phase_margin_deg": float(phase_margin) if np.isfinite(phase_margin) else None,
        "crossover_rad_s": float(crossover) if np.isfinite(crossover) else None,
        "frequency_columns": ["omega_rad_s", "magnitude_db", "phase_deg"],
        "frequency": np.column_stack((
            omega, 20 * np.log10(np.maximum(np.asarray(response.magnitude).squeeze(), 1e-15)),
            np.rad2deg(np.asarray(response.phase).squeeze()),
        )).tolist(),
        "response": evaluate_reduced(load_inertia, kp, kd),
    }


def sensitivity(load_inertia, kp, kd):
    problem = {
        "num_vars": 3, "names": ["shaft_stiffness_nm_per_rad", "load_inertia_kg_m2",
                                "bandwidth_per_s"],
        "bounds": [[400, 600], [0.8 * load_inertia, 1.2 * load_inertia], [800, 1200]],
    }
    x = morris_sample.sample(problem, N=4, num_levels=4, seed=20261023)
    y = np.array([
        evaluate_reduced(j, kp, kd, stiffness=k, bandwidth=bw)["tail_error_rad"]
        for k, j, bw in x
    ])
    si = morris_analyze.analyze(
        problem, x, y, num_levels=4, seed=20261023, print_to_console=False
    )
    return {
        "scope": "Morris on reduced model only; not a calibrated uncertainty interval",
        "problem": problem, "seed": 20261023, "num_levels": 4,
        "samples": x.tolist(), "response_rad": y.tolist(),
        "mu_star": np.asarray(si["mu_star"]).tolist(),
        "sigma": np.asarray(si["sigma"]).tolist(),
    }
