"""Run an external fitted magnetic model with explicit domain and error budgets."""
import argparse
import hashlib
import json
import math
from importlib.metadata import version
from pathlib import Path

import numpy as np

from guarded_magnetic_map import GuardedMagneticMap


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    fit, paths, pole_pairs = validate_fit(args.fit_dir, cfg)
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
    try:
        plant_par = model.SaturatedSynchronousMachinePars(
            n_p=pole_pairs, R_s=params["resistance_ohm"], i_s_dq_fcn=plant_map
        )
        plant = model.Drive(
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
        result = model.Simulation(plant, ctrl, show_progress=False).simulate(
            t_stop=params["duration_s"]
        )
        if not result.success:
            raise RuntimeError("motulator simulation did not complete")
        t = np.asarray(result.mdl.t)
        speed = np.asarray(result.mdl.machine.w_M)
        torque = np.asarray(result.mdl.machine.tau_M)
        if (not len(t) or t[-1] < params["duration_s"] * 0.999
                or not all(np.isfinite(x).all() for x in (t, speed, torque))):
            raise ValueError("simulation result is incomplete or nonfinite")
    except Exception as exc:
        failure = {"error_type": type(exc).__name__, "message": str(exc),
                   "plant_calls": plant_map.evaluations, "plant_rejected": plant_map.rejected,
                   "controller_calls": control_map.evaluations,
                   "controller_rejected": control_map.rejected}
        (args.output / "failure.json").write_text(json.dumps(failure, indent=2), encoding="utf-8")
        raise
    np.savez_compressed(args.output / "trajectory.npz", time_s=t, speed_rad_s=speed,
                        torque_nm=torque)
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
        "model_sha256": {name: sha(path) for name, path in paths.items()},
        "versions": {name: version(name) for name in ("motulator", "numpy", "scipy")},
        "declared_config": cfg, "fit_validation": fit["results"]["validation"],
        "time_end_s": float(t[-1]), "samples": len(t),
        "plant_map_calls": plant_map.evaluations,
        "plant_jacobian_calls": plant_map.jacobian_evaluations,
        "control_map_calls": control_map.evaluations,
        "control_jacobian_calls": control_map.jacobian_evaluations,
        "limitations": [
            "rectangles and validation budgets are user declarations, not physical proof",
            "no independent final holdout or solver-stage trace beyond wrapped map calls",
            "online reference, averaged converter; no inverter device nonlinearity",
            "no losses, temperature dynamics, torque-map accuracy or control optimization",
        ],
    }
    (args.output / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
