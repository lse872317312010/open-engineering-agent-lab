"""Orchestrate upstream motulator / Optuna with a SyR-e-format magnetic model."""
import argparse
import hashlib
import json
import math
from importlib.metadata import version
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import optuna
import motulator.drive.control.sm as control
from motulator.drive import model, utils


def run(model_map, nominal, cfg, bandwidth_hz, scenario, out):
    current_map = model_map.invert()
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
    for hz in sorted({4., best}):
        records.append(run(flux, base, cfg, hz, "holdout", out))
    summary = dict(
        input_map_sha256=hashlib.sha256(args.map.read_bytes()).hexdigest(),
        input_config_sha256=hashlib.sha256(args.config.read_bytes()).hexdigest(),
        tool_versions={name: version(name) for name in ("motulator", "optuna", "numpy", "scipy")},
        map_shape=list(flux.i_s_dq.shape), selected_bandwidth_hz=best,
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
