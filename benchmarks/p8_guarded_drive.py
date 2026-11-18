"""Exercise a declared-domain adapter through upstream motulator drive calls."""
import hashlib
import json
from importlib.metadata import version
from pathlib import Path

import matplotlib.pyplot as plt
import motulator.drive.control.sm as control
import motulator.drive.gradnet as gn
import numpy as np
from guarded_magnetic_map import GuardedMagneticMap, MagneticDomainError
from motulator.drive import model, utils


def execute(flux_radius):
    """Use deliberately synthetic limits to exercise routing, not certify validity."""
    folder = Path("upstream-motulator/examples/drive/flux_vector/trained_models")
    current_path = folder / "baldor_meas_curr_map_squareplus_d12_sub10.npz"
    flux_path = folder / "baldor_meas_flux_map_pnorm_d6_sub10.npz"
    plant_map = GuardedMagneticMap(
        gn.CurrentMap(gn.load_gradnet(current_path)),
        lambda psi: np.abs(psi) <= flux_radius,
    )
    control_map = GuardedMagneticMap(
        gn.FluxMap(gn.load_gradnet(flux_path)),
        lambda current: np.abs(current) <= 100.0,
    )
    nominal = utils.NominalValues(U=460, I=8.8, f=60, P=5.6e3, tau=29.7)
    base = utils.BaseValues.from_nominal(nominal, n_p=2)
    par = model.SaturatedSynchronousMachinePars(n_p=2, R_s=0.63, i_s_dq_fcn=plant_map)
    plant = model.Drive(
        model.SynchronousMachine(par),
        model.MechanicalSystem(J=0.05),
        model.VoltageSourceConverter(u_dc=540),
        sensors=model.DriveSensors(theta_M=model.Sensor()),
    )
    estimated = control.SaturatedSynchronousMachinePars(
        n_p=2, R_s=0.63, psi_s_dq_fcn=control_map
    )
    cfg = control.FluxVectorControllerCfg(
        i_s_max=2 * base.i, alpha_i=0, alpha_o=2 * np.pi * 8, J=0.05, sensorless=False
    )
    ctrl = control.VectorControlSystem(
        control.FluxVectorController(estimated, cfg),
        control.SpeedController(J=0.05, alpha_s=2 * np.pi * 4),
    )
    ctrl.set_speed_ref(lambda t: 50.0 if t > 0.01 else 0.0)
    result = model.Simulation(plant, ctrl, show_progress=False).simulate(t_stop=0.1)
    return result, plant_map, control_map, current_path, flux_path


def main():
    out = Path("outputs/p8-domain-integration")
    out.mkdir(parents=True, exist_ok=True)
    result, plant_map, control_map, current_path, flux_path = execute(5.0)
    if not result.success or result.mdl.t[-1] < 0.099:
        raise RuntimeError("wide-domain demonstration did not complete")
    t = np.asarray(result.mdl.t)
    speed = np.asarray(result.mdl.machine.w_M)
    torque = np.asarray(result.mdl.machine.tau_M)
    if not all(np.isfinite(x).all() for x in (t, speed, torque)):
        raise ValueError("nonfinite trajectory")
    if min(plant_map.evaluations, control_map.evaluations) < 1:
        raise RuntimeError("both plant and control must call their guarded maps")
    np.savez_compressed(out / "trajectory.npz", time_s=t, speed_rad_s=speed, torque_nm=torque)
    fig, ax = plt.subplots()
    ax.plot(t, speed)
    ax.set(xlabel="Time (s)", ylabel="Mechanical speed (rad/s)",
           title="Guarded upstream magnetic-map control demonstration")
    fig.tight_layout()
    fig.savefig(out / "speed.png", dpi=150)
    plt.close(fig)
    try:
        execute(0.0)
    except MagneticDomainError as exc:
        rejected = str(exc)
    else:
        raise RuntimeError("narrow-domain negative case failed to reject")
    report = {
        "source": "motulator v0.25.0 upstream measured GradNet models",
        "input_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (current_path, flux_path)},
        "versions": {n: version(n) for n in ("motulator", "numpy", "scipy")},
        "wide_case": {"end_time_s": float(t[-1]), "samples": len(t),
                      "plant_calls": plant_map.evaluations,
                      "controller_calls": control_map.evaluations,
                      "plant_rejections": plant_map.rejected,
                      "controller_rejections": control_map.rejected},
        "negative_case": {"flux_radius_wb": 0.0, "rejected": rejected},
        "limitations": [
            "radii 5 Wb and 100 A are synthetic and do not define physical validity",
            "upper and lower model limits are not inferred from measured source data",
            "instrumented calls cover these two guarded interfaces in this example only",
            "no solver-stage independent trace, optimization, or physical validation",
        ],
    }
    (out / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
