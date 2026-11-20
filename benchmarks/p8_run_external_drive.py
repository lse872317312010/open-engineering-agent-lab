"""Run an external fitted magnetic model with explicit domain and error budgets."""
import argparse
import hashlib
import json
import math
from importlib.metadata import version
from pathlib import Path

import numpy as np
from guarded_magnetic_map import GuardedMagneticMap
from p8_evaluate_final_holdout import HOLDOUT_METRICS
from p8_fit_external import check_source_compatibility, load_points, load_source_manifest


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def positive(cfg, name):
    value = cfg[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return float(value)


def bounds(cfg, name):
    value = cfg[name]
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"{name} must contain [d_min, d_max, q_min, q_max]")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in value):
        raise ValueError(f"{name} entries must be numeric")
    if not all(math.isfinite(x) for x in value) or value[0] >= value[1] or value[2] >= value[3]:
        raise ValueError(f"{name} bounds must be finite and ascending")
    return value


def rectangle(limits):
    def contains(z):
        z = np.asarray(z)
        return ((z.real >= limits[0]) & (z.real <= limits[1])
                & (z.imag >= limits[2]) & (z.imag <= limits[3]))
    return contains


def validate_fit(folder, cfg):
    summary_path = folder / "summary.json"
    fit = json.loads(summary_path.read_text(encoding="utf-8"))
    paths = {name: folder / (name + "-model.npz") for name in ("flux", "current")}
    for name, path in paths.items():
        if sha(path) != fit["model_sha256"][name]:
            raise ValueError(f"{name} model hash does not match fit summary")
    gates = (("flux_error_wb", "max_validation_flux_rmse_wb"),
             ("current_error_a", "max_validation_current_rmse_a"))
    for result_name, config_name in gates:
        budget = positive(cfg, config_name)
        observed = fit["results"]["validation"][result_name]["rmse"]
        if (isinstance(observed, bool) or not isinstance(observed, (int, float))
                or not math.isfinite(observed) or observed < 0 or observed > budget):
            raise ValueError(f"validation budget failed: {result_name}")
    pole_pairs = fit["nominal"]["pole_pairs"]
    if isinstance(pole_pairs, bool) or not isinstance(pole_pairs, int) or pole_pairs < 1:
        raise ValueError("invalid fit pole_pairs")
    return fit, paths, pole_pairs


def validate_final_evidence(fit_dir, fit, holdout, budget, evidence):
    """Verify evidence identity and all four declared holdout metrics and limits."""
    report = json.loads(evidence.read_text(encoding="utf-8"))
    limits = json.loads(budget.read_text(encoding="utf-8"))
    if report.get("passed") is not True:
        raise ValueError("final holdout did not pass")
    expected = {
        "train": fit["input_sha256"]["train"],
        "validation": fit["input_sha256"]["validation"],
        "holdout": sha(holdout),
        "budget": sha(budget),
    }
    if report.get("input_sha256") != expected:
        raise ValueError("final holdout inputs do not match fit and supplied files")
    if (report.get("fit_summary_sha256") != sha(fit_dir / "summary.json")
            or report.get("model_sha256") != fit["model_sha256"]):
        raise ValueError("final evidence does not match fit summary or models")
    source_manifests = fit.get("source_manifests")
    if (not isinstance(source_manifests, dict)
            or report.get("source_manifests") != source_manifests):
        raise ValueError("final evidence source manifests do not match fit")
    holdout_manifest = load_source_manifest(holdout)
    if report.get("holdout_source_manifest") != holdout_manifest:
        raise ValueError("final evidence source manifest does not match the holdout file")
    pole_pairs = fit["nominal"]["pole_pairs"]
    train_manifest = source_manifests["train"]
    check_source_compatibility(train_manifest, source_manifests["validation"], pole_pairs)
    check_source_compatibility(train_manifest, holdout_manifest, pole_pairs)
    current, _ = load_points(holdout)
    points = report.get("points")
    if type(points) is not int or points != len(current):
        raise ValueError("final evidence point count does not match the holdout file")
    checks = report.get("checks", {})
    recorded = report.get("budgets", {})
    for key, (quantity, metric) in HOLDOUT_METRICS.items():
        limit = positive(limits, key)
        recorded_limit = recorded.get(key)
        value = report["errors"][quantity][metric]
        if (isinstance(recorded_limit, bool) or recorded_limit != limit
                or checks.get(key) is not True
                or isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0 or value > limit):
            raise ValueError(f"final holdout budget mismatch or failure: {key}")
    return report


def save_solver_flux_audit(output, rhs_calls, flux_bounds):
    trace = np.array(rhs_calls, dtype=[
        ("time_s", "f8"), ("flux_dq_wb", "c16"),
        ("map_calls", "i8"), ("map_rejections", "i8"),
    ])
    flux = trace["flux_dq_wb"]
    d_min, d_max, q_min, q_max = flux_bounds
    # Check the recorded machine states independently of the map's runtime predicate.
    dq = np.column_stack((flux.real, flux.imag))
    inside_rectangle = (dq >= [d_min, q_min]) & (dq <= [d_max, q_max])
    in_domain = np.isfinite(flux) & np.all(inside_rectangle, axis=1)
    guard_matches = ((trace["map_calls"] == in_domain)
                     & (trace["map_rejections"] == ~in_domain))
    path = output / "solver-flux-audit.npz"
    np.savez_compressed(path, rhs=trace, in_domain=in_domain, guard_matches=guard_matches)
    outside = np.flatnonzero(~in_domain)
    invalid_times = int(np.count_nonzero(~np.isfinite(trace["time_s"])))
    mismatches = int(np.count_nonzero(~guard_matches))
    return {"file": path.name, "sha256": sha(path), "rhs_calls": len(trace),
            "outside_flux_domain": int(outside.size),
            "first_outside_call_index": int(outside[0]) if outside.size else None,
            "guard_mismatches": mismatches, "invalid_times": invalid_times,
            "passed": bool(len(trace) and not (outside.size or mismatches or invalid_times))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--holdout-budget", type=Path, required=True)
    parser.add_argument("--final-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    fit, paths, pole_pairs = validate_fit(args.fit_dir, cfg)
    final = validate_final_evidence(
        args.fit_dir, fit, args.holdout, args.holdout_budget, args.final_evidence
    )
    flux_bounds = bounds(cfg, "flux_domain_wb")
    current_bounds = bounds(cfg, "current_domain_a")
    params = {name: positive(cfg, name) for name in (
        "resistance_ohm", "inertia_kg_m2", "dc_voltage_v", "current_limit_a",
        "speed_bandwidth_hz", "duration_s",
    )}
    speed_ref = cfg["speed_reference_rad_s"]
    if (isinstance(speed_ref, bool) or not isinstance(speed_ref, (int, float))
            or not math.isfinite(speed_ref)):
        raise ValueError("speed_reference_rad_s must be finite")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("output directory must be empty")
    args.output.mkdir(parents=True, exist_ok=True)
    import matplotlib.pyplot as plt
    import motulator.drive.control.sm as control
    import motulator.drive.gradnet as gn
    from motulator.drive import model

    plant_map = GuardedMagneticMap(
        gn.CurrentMap(gn.load_gradnet(paths["current"])), rectangle(flux_bounds)
    )
    control_map = GuardedMagneticMap(
        gn.FluxMap(gn.load_gradnet(paths["flux"])), rectangle(current_bounds)
    )
    rhs_calls = []

    class AuditedDrive(model.Drive):
        def rhs(self, t, state_list):
            calls_before = plant_map.evaluations
            rejections_before = plant_map.rejected
            try:
                return super().rhs(t, state_list)
            finally:
                rhs_calls.append((t, self.machine.state.psi_s_dq,
                                  plant_map.evaluations - calls_before,
                                  plant_map.rejected - rejections_before))

    solver_cfg = model.SolverCfg()
    audit = None
    try:
        plant_par = model.SaturatedSynchronousMachinePars(
            n_p=pole_pairs, R_s=params["resistance_ohm"], i_s_dq_fcn=plant_map
        )
        plant = AuditedDrive(
            model.SynchronousMachine(plant_par),
            model.MechanicalSystem(J=params["inertia_kg_m2"]),
            model.VoltageSourceConverter(u_dc=params["dc_voltage_v"]),
            sensors=model.DriveSensors(theta_M=model.Sensor()),
        )
        estimated = control.SaturatedSynchronousMachinePars(
            n_p=pole_pairs, R_s=params["resistance_ohm"],
            i_s_dq_fcn=plant_map, psi_s_dq_fcn=control_map
        )
        ctrl_cfg = control.FluxVectorControllerCfg(
            i_s_max=params["current_limit_a"], J=params["inertia_kg_m2"], alpha_i=0,
            alpha_o=2 * math.pi * 8, sensorless=False, online_ref=True
        )
        ctrl = control.VectorControlSystem(
            control.FluxVectorController(estimated, ctrl_cfg),
            control.SpeedController(J=params["inertia_kg_m2"],
                                    alpha_s=2 * math.pi * params["speed_bandwidth_hz"]),
        )
        ctrl.set_speed_ref(lambda t: speed_ref if t > 0.01 else 0.0)
        result = model.Simulation(plant, ctrl, show_progress=False, cfg=solver_cfg).simulate(
            t_stop=params["duration_s"]
        )
        if not result.success:
            raise RuntimeError("motulator simulation did not complete")
        t = np.asarray(result.mdl.t)
        speed = np.asarray(result.mdl.machine.w_M)
        torque = np.asarray(result.mdl.machine.tau_M)
        flux = np.asarray(result.mdl.machine.psi_s_dq)
        if (not len(t) or t[-1] < params["duration_s"] * 0.999
                or not all(np.isfinite(x).all() for x in (t, speed, torque, flux))):
            raise ValueError("simulation result is incomplete or nonfinite")
        audit = save_solver_flux_audit(args.output, rhs_calls, flux_bounds)
        if not audit["passed"]:
            raise RuntimeError("solver flux audit failed")
    except Exception as exc:
        if audit is None:
            audit = save_solver_flux_audit(args.output, rhs_calls, flux_bounds)
        failure = {"error_type": type(exc).__name__, "message": str(exc),
                   "plant_calls": plant_map.evaluations, "plant_rejected": plant_map.rejected,
                   "controller_calls": control_map.evaluations,
                   "controller_rejected": control_map.rejected,
                   "solver": solver_cfg.solver, "flux_domain_wb": flux_bounds,
                   "drive_config_sha256": sha(args.config),
                   "final_evidence_sha256": sha(args.final_evidence),
                   "model_sha256": fit["model_sha256"], "solver_flux_audit": audit}
        (args.output / "failure.json").write_text(json.dumps(failure, indent=2), encoding="utf-8")
        raise
    np.savez_compressed(args.output / "trajectory.npz", time_s=t, speed_rad_s=speed,
                        torque_nm=torque, flux_dq_wb=flux)
    fig, axes = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
    axes[0].plot(t, speed)
    axes[0].set_ylabel("Mechanical speed (rad/s)")
    axes[1].plot(t, torque)
    axes[1].set(xlabel="Time (s)", ylabel="Electromagnetic torque (Nm)")
    fig.tight_layout()
    fig.savefig(args.output / "trajectory.png", dpi=150)
    plt.close(fig)
    report = {
        "fit_summary_sha256": sha(args.fit_dir / "summary.json"),
        "drive_config_sha256": sha(args.config),
        "final_evidence_sha256": sha(args.final_evidence),
        "final_holdout_sha256": sha(args.holdout),
        "final_budget_sha256": sha(args.holdout_budget),
        "final_holdout_checks": final["checks"],
        "model_sha256": {name: sha(path) for name, path in paths.items()},
        "versions": {name: version(name) for name in ("motulator", "numpy", "scipy")},
        "declared_config": cfg, "fit_validation": fit["results"]["validation"],
        "time_end_s": float(t[-1]), "samples": len(t),
        "plant_map_calls": plant_map.evaluations,
        "plant_jacobian_calls": plant_map.jacobian_evaluations,
        "control_map_calls": control_map.evaluations,
        "control_jacobian_calls": control_map.jacobian_evaluations,
        "solver": solver_cfg.solver,
        "solver_flux_audit": audit,
        "limitations": [
            "rectangles and validation budgets are user declarations, not physical proof",
            "source checks compare user-declared metadata",
            "holdout provenance and independence require external evidence",
            "evidence JSON is unsigned",
            "RHS trace covers magnetic flux states evaluated by the solver",
            "online reference, averaged converter; no inverter device nonlinearity",
            "no losses, temperature dynamics, torque-map accuracy or control optimization",
        ],
    }
    (args.output / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
