"""Orchestrate upstream motulator / Optuna with a SyR-e-format magnetic model."""
import argparse
import hashlib
import json
import math
from importlib.metadata import version
from pathlib import Path

import matplotlib.pyplot as plt
import motulator.drive.control.sm as control
import numpy as np
import optuna
from motulator.drive import model, utils


def run(model_map, nominal, cfg, bandwidth_hz, scenario, out):
    current_map = model_map.invert(num=512)
    plant_par = model.SaturatedSynchronousMachinePars(
        n_p=cfg["pole_pairs"], R_s=cfg["resistance_ohm"], i_s_dq_fcn=current_map
    )
    plant = model.Drive(
        model.SynchronousMachine(plant_par),
        model.MechanicalSystem(J=cfg["inertia_kg_m2"]),
        model.VoltageSourceConverter(u_dc=cfg["dc_voltage_v"]),
    )
    est_par = control.SaturatedSynchronousMachinePars(
        n_p=cfg["pole_pairs"], R_s=cfg["resistance_ohm"], psi_s_dq_fcn=model_map
    )
    controller_cfg = control.CurrentVectorControllerCfg(
        i_s_max=cfg["current_max_a"], J=cfg["inertia_kg_m2"], sensorless=True
    )
    ctrl = control.VectorControlSystem(
        control.CurrentVectorController(est_par, controller_cfg),
        control.SpeedController(J=cfg["inertia_kg_m2"], alpha_s=2 * math.pi * bandwidth_hz),
    )
    ctrl.set_speed_ref(lambda t: cfg["speed_reference_rad_s"] if t > .2 else 0.)
    plant.mechanics.set_external_load_torque(
        lambda t: cfg[scenario + "_load_nm"] if t > .5 else 0.
    )
    result = model.Simulation(plant, ctrl, show_progress=False).simulate(t_stop=1.0)
    if not result.success or result.mdl.t[-1] < .999:
        raise RuntimeError("motulator simulation did not complete")
    time = np.asarray(result.mdl.t)
    speed = np.asarray(result.mdl.machine.w_M)
    torque = np.asarray(result.mdl.machine.tau_M)
    flux = np.asarray(result.mdl.machine.psi_s_dq)
    current = np.asarray(result.mdl.machine.i_s_dq)
    if not all(np.isfinite(x).all() for x in (time, speed, torque, flux, current)):
        raise ValueError("nonfinite simulation result")
    # Score equally spaced controller sample times; no adaptive-integrator sampling bias.
    score_time = np.arange(.25, 1.0, .001)
    error = cfg["speed_reference_rad_s"] - np.interp(score_time, time, speed)
    rms = float(np.sqrt(np.mean(error**2)))
    # motulator's inverse map extrapolates. This only audits saved output endpoints.
    grid = current_map.psi_s_dq
    outside = ((flux.real < np.min(grid.real)) | (flux.real > np.max(grid.real))
               | (flux.imag < np.min(grid.imag)) | (flux.imag > np.max(grid.imag)))
    record = dict(scenario=scenario, speed_bandwidth_hz=bandwidth_hz,
                  speed_rmse_rad_s=rms, output_samples=len(time),
                  inverse_map_endpoint_outside=int(np.count_nonzero(outside)),
                  inverse_map_endpoint_fraction=float(np.mean(outside)))
    stem = f"{scenario}-{bandwidth_hz:g}hz"
    np.savez_compressed(out / (stem + ".npz"), time_s=time, speed_rad_s=speed,
                        torque_nm=torque, flux_dq=flux, current_dq=current,
                        score_time_s=score_time, score_error_rad_s=error)
    utils.plot(result, nominal, save_path=out / (stem + ".png"))
    plt.close("all")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, type=Path, help="SyR-e MAT flux map")
    parser.add_argument("--config", required=True, type=Path, help="motor and experiment JSON")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    flux = utils.import_syre_data(args.map)
    # Compare the imported FE torque against motulator's own average-torque model.
    # Results only cover original data points inside the inverse map rectangle.
    baseline_inverse = flux.invert()
    inverse = flux.invert(num=512)
    inverse_grid = inverse.psi_s_dq
    valid = (np.isfinite(flux.i_s_dq) & np.isfinite(flux.psi_s_dq)
             & np.isfinite(flux.tau_M)
             & (flux.psi_s_dq.real >= np.min(inverse_grid.real))
             & (flux.psi_s_dq.real <= np.max(inverse_grid.real))
             & (flux.psi_s_dq.imag >= np.min(inverse_grid.imag))
             & (flux.psi_s_dq.imag <= np.max(inverse_grid.imag)))
    if not np.any(valid):
        raise ValueError("no finite source points in inverse-map domain")
    machine_par = model.SaturatedSynchronousMachinePars(
        n_p=cfg["pole_pairs"], R_s=cfg["resistance_ohm"], i_s_dq_fcn=inverse
    )
    baseline_par = model.SaturatedSynchronousMachinePars(
        n_p=cfg["pole_pairs"], R_s=cfg["resistance_ohm"], i_s_dq_fcn=baseline_inverse
    )
    baseline_i, baseline_tau_per_pole = baseline_par.magnetic_map(flux.psi_s_dq[valid])
    predicted_i, predicted_tau_per_pole = machine_par.magnetic_map(flux.psi_s_dq[valid])
    predicted_tau = cfg["pole_pairs"] * np.asarray(predicted_tau_per_pole)
    source_tau = np.asarray(flux.tau_M[valid])
    original_i = np.asarray(flux.i_s_dq[valid])
    if not np.isfinite(predicted_i).all() or not np.isfinite(predicted_tau).all():
        raise ValueError("nonfinite inverse-map comparison")
    comparison = dict(
        original_inverse_grid=256, refined_inverse_grid=512,
        source_points=int(flux.i_s_dq.size), valid_points=int(np.count_nonzero(valid)),
        valid_fraction=float(np.mean(valid)),
        inverse_current_max_error_a=float(np.max(abs(predicted_i-original_i))),
        source_torque_max_error_nm=float(np.max(abs(predicted_tau-source_tau))),
        source_torque_rmse_nm=float(np.sqrt(np.mean((predicted_tau-source_tau)**2))),
        original_inverse_current_max_error_a=float(np.max(abs(baseline_i-original_i))),
        original_source_torque_max_error_nm=float(np.max(abs(
            cfg["pole_pairs"] * baseline_tau_per_pole-source_tau))),
        original_source_torque_rmse_nm=float(np.sqrt(np.mean((
            cfg["pole_pairs"] * baseline_tau_per_pole-source_tau)**2))),
    )
    np.savez_compressed(out / "source-map.npz", current_dq=flux.i_s_dq,
                        flux_dq=flux.psi_s_dq, torque_nm=flux.tau_M,
                        comparison_valid=valid)
    fig, ax = plt.subplots(figsize=(7, 5))
    source_valid = (np.isfinite(flux.i_s_dq) & np.isfinite(flux.tau_M))
    source_i = flux.i_s_dq[source_valid]
    plot = ax.scatter(source_i.real, source_i.imag, c=flux.tau_M[source_valid],
                      s=2, rasterized=True)
    ax.set(xlabel="d-axis current (A)", ylabel="q-axis current (A)",
           title="Source electromagnetic torque (Nm)")
    fig.colorbar(plot, ax=ax, label="Torque (Nm)")
    fig.tight_layout()
    fig.savefig(out / "source-torque-map.png", dpi=160)
    plt.close(fig)
    nominal = utils.NominalValues(U=cfg["nominal_voltage_v"], I=cfg["nominal_current_a"],
                                  f=cfg["nominal_frequency_hz"], P=cfg["nominal_power_w"],
                                  tau=cfg["nominal_torque_nm"])
    base = utils.BaseValues.from_nominal(nominal, n_p=cfg["pole_pairs"])
    for component in ("d", "q"):
        utils.plot_map(flux, component, base, save_path=out / f"flux-{component}.png")
        plt.close("all")
    par = control.SaturatedSynchronousMachinePars(
        n_p=cfg["pole_pairs"], R_s=cfg["resistance_ohm"], psi_s_dq_fcn=flux
    )
    characteristics = utils.MachineCharacteristics(par)
    for name in ("current_loci", "flux_loci", "current_vs_torque", "flux_vs_torque"):
        getattr(characteristics, "plot_" + name)(
            cfg["characteristic_current_pu"], base, save_path=out / (name + ".png")
        )
        plt.close("all")
    records = []
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    sampler = optuna.samplers.GridSampler({"bandwidth_hz": [2., 4.]}, seed=1)
    study = optuna.create_study(direction="minimize", sampler=sampler)

    def objective(trial):
        hz = trial.suggest_categorical("bandwidth_hz", [2., 4.])
        result = run(flux, base, cfg, hz, "train", out)
        records.append(result)
        return result["speed_rmse_rad_s"]

    study.optimize(objective, n_trials=2)
    best = float(study.best_params["bandwidth_hz"])
    for hz in (2., 4.):
        records.append(run(flux, base, cfg, hz, "holdout", out))
    summary = dict(
        input_map_sha256=hashlib.sha256(args.map.read_bytes()).hexdigest(),
        input_config_sha256=hashlib.sha256(args.config.read_bytes()).hexdigest(),
        tool_versions={name: version(name) for name in ("motulator", "optuna", "numpy", "scipy")},
        map_shape=list(flux.i_s_dq.shape), source_map_comparison=comparison,
        selected_bandwidth_hz=best,
        fixed_baseline_bandwidth_hz=4., records=records,
        source="SyR-e MAT flux map; motulator import_syre_data",
        inverter="averaged ZOH, u_th=0, no dead time; one-sample delay and voltage limits",
        extrapolation="endpoint rectangle only; internal solver stages not checked",
        missing=["iron loss", "efficiency map", "spatial harmonics",
                 "independent physical accuracy", "full torque-speed envelope"],
    )
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("open-motor-lab:", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
