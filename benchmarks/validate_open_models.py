"""Execute pinned upstream models and fixed physical limits; retain negative cases."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import mujoco
import numpy as np
from motulator.common.model import CarrierComparison
from motulator.common.model._simulation import SolverCfg
from motulator.common.utils import abc2complex, complex2abc
from motulator.drive import model
from PIL import Image
from scipy.integrate import solve_ivp

from oeal.backends.motulator import CONTROL_COLUMNS, load_magnetic_map, run_drive
from oeal.backends.robot import (
    ROBOT_COLUMNS,
    RobotLoad,
    load_robot,
    prepare_ur5e,
    robot_reference_checks,
    transmission,
)
from oeal.refined_thermal import CAPACITIES, NAMES, ThermalNetwork

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/refined"
MODELS = ROOT / "outputs/open-models"
CONFIG = json.loads((ROOT / "examples/p6-open-models.json").read_text())
MOT = CONFIG["sources"]["motulator_commit"]
MAP_PATH = "examples/drive/data/baldor_400rpm_map.npz"


def save(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def csv(name, columns, rows):
    np.savetxt(OUT / name, rows, delimiter=",", header=",".join(columns), comments="")


def preview(rows, stride):
    """Decimate for browsing while retaining both real endpoint samples."""
    indices = np.unique(np.r_[np.arange(0, len(rows), stride), len(rows) - 1])
    return rows[indices].tolist()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def upstream_inputs():
    MODELS.mkdir(parents=True, exist_ok=True)
    magnetic = MODELS / "baldor_400rpm_map.npz"
    urllib.request.urlretrieve(
        f"https://raw.githubusercontent.com/Aalto-Electric-Drives/motulator/{MOT}/{MAP_PATH}",
        magnetic,
    )
    raw = magnetic.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    assert blob == CONFIG["sources"]["magnetic_map_blob"], "upstream data changed"
    ur5e = prepare_ur5e(
        ROOT / "vendor/menagerie/universal_robots_ur5e", MODELS
    )
    actual = subprocess.check_output(
        ["git", "-C", str(ROOT / "vendor/menagerie"), "rev-parse", "HEAD"], text=True
    ).strip()
    assert actual == CONFIG["sources"]["menagerie_commit"]
    assert mujoco.__version__ == CONFIG["sources"]["mujoco_version"]
    for name in ("motulator", "mujoco", "ur5e"):
        source = ROOT / f"research/licenses/{name}-refinement.txt"
        shutil.copyfile(source, MODELS / (name + "-LICENSE.txt"))
    return magnetic, ur5e


def references():
    class ConstantVoltage:
        t = 0.0

        def get_enable(self):
            return True

        def __call__(self, mdl):
            self.t += 50e-6
            phases = np.asarray(complex2abc(3 + 0j))
            return 50e-6, 0.5 + phases / 48

        def post_process(self):
            return SimpleNamespace()

    par = model.SynchronousMachinePars(n_p=7, R_s=0.3, L_d=0.0008,
                                      L_q=0.0008, psi_f=0.03)
    mechanics = model.ExternalRotorSpeed()
    mechanics.set_external_rotor_speed(0.0)
    drive = model.Drive(
        model.SynchronousMachine(par), mechanics,
        model.VoltageSourceConverter(u_dc=48), pwm=False, delay=0,
    )
    sim = model.Simulation(drive, ConstantVoltage(), show_progress=False,
                           cfg=SolverCfg(method="DOP853", rtol=1e-10, atol=1e-12))
    result = sim.simulate(t_stop=0.01, N_eval=2)
    expected = 10 * (1 - np.exp(-0.3 * result.mdl.t / 0.0008))
    rl_error = float(np.max(np.abs(result.mdl.machine.i_s_dq.real - expected)))

    converter = model.VoltageSourceConverter(u_dc=48)
    converter.inp.i_c_ab = abc2complex([2, -0.7, -1.3])
    power_errors = []
    for value in range(8):
        q = np.array([(value >> bit) & 1 for bit in range(3)])
        converter.set_gate_signals(q, np.zeros(3))
        converter.set_outputs(0)
        ac = 1.5 * (converter.out.u_c_ab * converter.inp.i_c_ab.conjugate()).real
        dc = 48 * converter.compute_internal_dc_current(converter.inp)
        power_errors.append(abs(ac - dc))
    pwm = CarrierComparison(t_d=1e-6)
    period_errors = []
    for _ in range(2):
        duration, _, blanking = pwm(25e-6, [0.2, 0.5, 0.8])
        assert np.all(duration >= 0) and np.any(blanking > 0)
        period_errors.append(abs(duration.sum() - 25e-6))

    load_converter = model.VoltageSourceConverter()
    load_converter.inp.q_c_ab = 1 + 0j
    load_converter.inp.i_c_ab = 2 + 0j
    bus = model.DCBus(0.002, 48, [load_converter])
    bus.set_external_dc_current(lambda t: (48 - bus.state.u_dc.real) / 0.15)

    def bus_rhs(t, y):
        bus.state.u_dc = y[0]
        return bus.rhs(t)

    times = np.linspace(0, 0.005, 101)
    solved = solve_ivp(bus_rhs, (0, times[-1]), [48], t_eval=times,
                       rtol=1e-10, atol=1e-12, method="DOP853", max_step=1e-5)
    expected_bus = 48 - 0.45 * (1 - np.exp(-times / (0.15 * 0.002)))
    bus_error = float(np.max(np.abs(solved.y[0] - expected_bus)))

    network = ThermalNetwork(period_s=0.1)
    powers = np.array([20, 5, 2, 15, 0, 0])
    initial = np.array([90, 80, 50, 110, 60, 40], dtype=float)
    network.temperatures = initial.copy()
    balance = abs(network.balance_error_w(initial, powers))
    for _ in range(1000):
        network.advance(powers)
    independent = solve_ivp(
        lambda t, x: (-network.conductance @ (x - 25) + powers) / CAPACITIES,
        (0, 100), initial, rtol=1e-11, atol=1e-12, method="DOP853",
    )
    thermal_error = float(np.max(np.abs(network.temperatures - independent.y[:, -1])))
    for delta in (-0.002, -0.0005, 0, 0.0005, 0.002):
        for speed in (-0.2, 0, 0.2):
            torque, energy, dissipated = transmission(delta, speed, backlash=0.001)
            assert energy >= 0 and dissipated >= 0
            if abs(delta) <= 0.001:
                assert torque == 0 and energy == 0
    report = {
        "rl_error_a": rl_error, "ideal_bridge_power_error_w": max(power_errors),
        "carrier_period_error_s": max(period_errors), "bus_reference_error_v": bus_error,
        "thermal_balance_error_w": balance, "thermal_reference_error_k": thermal_error,
    }
    report["passed"] = bool(
        rl_error < 1e-5 and max(power_errors) < 1e-8
        and max(period_errors) < 1e-12 and bus_error < 1e-5
        and balance < 1e-8 and thermal_error < 1e-6
    )
    save("references.json", report)
    assert report["passed"], report
    return report


def electrical_cases(magnetic_path):
    magnetic, flux, current = load_magnetic_map(magnetic_path)
    current_domain, _ = current.get_input_output()
    bounds = {
        "psi_d_min": float(np.real(current_domain).min()),
        "psi_d_max": float(np.real(current_domain).max()),
        "psi_q_min": float(np.imag(current_domain).min()),
        "psi_q_max": float(np.imag(current_domain).max()),
    }
    reports = []
    for spec in CONFIG["electrical"]:
        config = CONFIG["base"] | spec
        result, controller = run_drive(config, magnetic if spec.get("magnetic") else None)
        rows = np.asarray(controller.rows)
        full_time = result.mdl.t
        in_scope = full_time <= config["duration_s"] + 1e-12
        time = full_time[in_scope]
        iq = result.mdl.machine.i_s_dq.imag[in_scope]
        tail = time >= config["duration_s"] - 0.005
        mean_q = float(np.trapezoid(iq[tail], time[tail]) / np.ptp(time[tail]))
        last_cycle = time >= config["duration_s"] - config["period_s"]
        ripple = float(np.ptp(iq[last_cycle]))
        error = abs(mean_q - config["iq_reference_a"])
        sample_error = float(np.sqrt(np.mean((rows[:, 4] - rows[:, 2]) ** 2)))
        extrapolation = 0
        if spec.get("nonlinear"):
            psi = result.mdl.machine.psi_s_dq
            outside = (
                (psi.real < bounds["psi_d_min"] - 1e-10)
                | (psi.real > bounds["psi_d_max"] + 1e-10)
                | (psi.imag < bounds["psi_q_min"] - 1e-10)
                | (psi.imag > bounds["psi_q_max"] + 1e-10)
            )
            extrapolation = int(outside.sum())
        phase_i = np.asarray(complex2abc(result.mdl.machine.i_s_ab)).T
        phase_u = np.asarray(complex2abc(result.mdl.converter.u_c_ab)).T
        waves = np.column_stack((
            full_time, phase_i, phase_u, result.mdl.converter.u_dc,
            result.mdl.converter.i_dc_int, result.mdl.machine.i_s_dq.real,
            result.mdl.machine.i_s_dq.imag,
            result.mdl.machine.tau_M, result.mdl.converter.enabled,
        ))[in_scope]
        csv(spec["id"] + "-control.csv", CONTROL_COLUMNS, rows)
        wave_columns = [
            "time_s", "ia_a", "ib_a", "ic_a", "ua_v", "ub_v", "uc_v",
            "bus_v", "dc_current_a", "id_a", "iq_a", "torque_nm", "enabled",
        ]
        csv(spec["id"] + "-waveforms.csv", wave_columns, waves)
        events = np.asarray(controller.drive.oeal_pwm_records)
        events = events[events[:, 0] < config["duration_s"] - 1e-12].copy()
        events[:, 1] = np.minimum(events[:, 1], config["duration_s"] - events[:, 0])
        csv(spec["id"] + "-gates.csv",
            ["time_s", "duration_s", "qa", "qb", "qc", "blank_a", "blank_b", "blank_c",
             "enabled"], events)
        # Retain a full-resolution final 0.5 ms window for offline inspection.
        window = waves[time >= config["duration_s"] - 0.0005]
        valid = bool(np.all(np.isfinite(waves)) and np.all(np.isfinite(rows))
                     and rows[:, 9].min() > 0 and extrapolation == 0)
        reports.append({
            "id": spec["id"], "title": spec["title"], "config": config,
            "backend": "motulator", "numeric_passed": valid,
            "tracking_goal_passed": error < 0.1,
            "metrics": {
                "tail_q_mean_a": mean_q, "tail_q_error_a": error, "q_ripple_pp_a": ripple,
                "sensor_q_rmse_a": sample_error,
                "voltage_limited_ticks": int(rows[:, 12].sum()),
                "gate_intervals": len(events), "map_extrapolation_samples": extrapolation,
                "bus_min_v": float(rows[:, 9].min()), "bus_max_v": float(rows[:, 9].max()),
                "peak_junction_c": float(rows[:, 20].max()),
            },
            "control_columns": CONTROL_COLUMNS, "control": preview(rows, 4),
            "wave_columns": wave_columns, "wave_window": window.tolist(),
            "gate_columns": ["time_s", "duration_s", "qa", "qb", "qc", "blank_a",
                             "blank_b", "blank_c", "enabled"],
            "gate_window": events[events[:, 0] >= config["duration_s"] - 0.0005].tolist(),
        })
        print("electrical-case.json: " + json.dumps({
            "id": spec["id"], "numeric_passed": valid, "q_error_a": error
        }), flush=True)
    iq_values = np.linspace(0, min(15, float(flux.i_s_dq.imag.max()) * 0.8), 31)
    points = 1j * iq_values
    psi = np.asarray(flux(points))
    reconstructed = np.asarray(current(psi))
    nominal = magnetic[0]
    map_report = {
        "source": "upstream packaged measured-map example; not user motor measurements",
        "sha256": sha256(magnetic_path), "git_blob_sha1": CONFIG["sources"]["magnetic_map_blob"],
        "domain": bounds, "roundtrip_max_error_a": float(np.abs(reconstructed - points).max()),
        "curve_columns": ["iq_a", "psi_q_nonlinear_wb", "psi_q_tangent_wb", "psi_d_wb"],
        "curve": np.column_stack((
            iq_values, psi.imag, nominal.L_q * iq_values, psi.real
        )).tolist(),
        "nominal_tangent": {"pole_pairs": nominal.n_p, "resistance_ohm": nominal.R_s,
                            "ld_h": nominal.L_d, "lq_h": nominal.L_q,
                            "pm_flux_wb": nominal.psi_f},
    }
    save("electrical.json", {"cases": reports, "magnetic_map": map_report})
    assert all(c["numeric_passed"] for c in reports), "invalid or out-of-domain model result"
    assert not next(c for c in reports if c["id"] == "low-bus")["tracking_goal_passed"]
    return reports, map_report


def robot_cases(path):
    checks = robot_reference_checks(path)
    checks["passed"] = bool(
        checks["gravity_gradient_error_nm"] < 1e-4
        and checks["forward_inverse_error_rad_s2"] < 1e-7
        and checks["mass_min_eigenvalue_kg_m2"] > 0
    )
    save("robot-references.json", checks)
    assert checks["passed"], checks
    reports = []
    final_model = final_data = None
    specs = CONFIG["robot"] + [{
        "id": "robot-fine", "title": "UR5e 宏步减半参考", "backlash_rad": 0,
        "macro_step_s": CONFIG["robot_base"]["macro_step_s"] / 2,
    }]
    for spec in specs:
        config = CONFIG["base"] | CONFIG["robot_base"] | spec
        robot_model, data, xml = load_robot(
            path, config["macro_step_s"], fixture=config.get("fixture", False)
        )
        # Preserve the exact actuator change and portable asset paths in the export.
        xml.find("compiler").set("meshdir", "ur5e/assets")
        exported = MODELS / (config["id"] + ".xml")
        ET.ElementTree(xml).write(exported, encoding="unicode", xml_declaration=True)
        mujoco.MjModel.from_xml_path(str(exported))
        robot = RobotLoad(robot_model, data, config)
        _, controller = run_drive(config, robot=robot)
        rows = np.asarray(robot.rows)
        assert abs(rows[-1, 0] - config["duration_s"]) < 1e-12
        control = np.asarray(controller.rows)
        csv(spec["id"] + ".csv", ROBOT_COLUMNS, rows)
        csv(spec["id"] + "-control.csv", CONTROL_COLUMNS, control)
        error = float(np.mean(np.abs(rows[-max(1, len(rows) // 10):, 1]
                                     - rows[-max(1, len(rows) // 10):, 3])))
        contact_count = int(rows[:, 8].max())
        valid = bool(np.all(np.isfinite(rows)) and np.all(np.isfinite(control)))
        if config.get("fixture"):
            valid = valid and contact_count > 0
        reports.append({
            "id": spec["id"], "title": spec["title"], "backend": "motulator + MuJoCo UR5e",
            "config": config, "columns": ROBOT_COLUMNS, "samples": preview(rows, 4),
            "control_columns": CONTROL_COLUMNS, "control": preview(control, 20),
            "numeric_passed": valid, "position_goal_passed": error < 0.03,
            "metrics": {
                "tail_position_error_rad": error, "peak_contacts": contact_count,
                "peak_fixture_force_n": float(rows[:, 9].max()),
                "peak_shaft_torque_nm": float(np.abs(rows[:, 6]).max()),
                "peak_gravity_bias_nm": float(np.abs(rows[:, 7]).max()),
            },
        })
        if spec["id"] == "robot-elastic":
            final_model, final_data = robot_model, data
        print("robot-case.json: " + json.dumps(reports[-1]["metrics"] | {
            "id": spec["id"], "numeric_passed": valid
        }), flush=True)
    baseline, fine = reports[0], reports[-1]
    base_rows, fine_rows = np.array(baseline["samples"]), np.array(fine["samples"])
    convergence = float(np.max(np.abs(
        base_rows[:, 1] - np.interp(base_rows[:, 0], fine_rows[:, 0], fine_rows[:, 1])
    )))
    assert convergence < 0.02, convergence
    assert all(c["numeric_passed"] for c in reports)
    with mujoco.Renderer(final_model, height=480, width=640) as renderer:
        camera = mujoco.MjvCamera()
        camera.lookat[:] = [0, 0, 0.4]
        camera.distance = 2.1
        camera.azimuth = 130
        camera.elevation = -25
        renderer.update_scene(final_data, camera=camera)
        Image.fromarray(renderer.render()).save(OUT / "ur5e-model.png")
    report = {"cases": reports, "references": checks,
              "macro_step_halving_error_rad": convergence}
    save("robot.json", report)
    return report


def thermal_replay(electrical):
    """Replay measured simulation heat rates, without claiming 120 s full-switching FOC."""
    source = next(c for c in electrical if c["id"] == "core-loss")
    data = np.asarray(source["control"])
    tail = data[data[:, 0] >= 0.02]
    heat = tail[:, [16, 17, 18]].mean(axis=0)
    rows = []
    network = ThermalNetwork(period_s=0.1)
    for i in range(1201):
        power = heat * (1 if (i // 200) % 3 != 2 else 0.2)
        rows.append([i * 0.1, *network.temperatures, *power])
        if i < 1200:
            network.advance([power[0], power[1], 0, power[2], 0, 0])
    columns = ["time_s", *[name + "_c" for name in NAMES], "copper_w", "core_w", "device_w"]
    csv("six-node-thermal.csv", columns, rows)
    return {
        "columns": columns, "samples": rows, "source_case": source["id"],
        "scope": "120 s multi-node heat replay from short switching run; not full long FOC",
        "source_mean_powers_w": heat.tolist(),
        "parameters": {"capacities_j_per_k": CAPACITIES.tolist(),
                       "ambient_c": network.ambient_c,
                       "conductance_w_per_k": network.conductance.tolist()},
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "examples/p6-open-models.json", OUT / "inputs.json")
    magnetic, robot_path = upstream_inputs()
    reference = references()
    electrical, magnetic_map = electrical_cases(magnetic)
    robot = robot_cases(robot_path)
    thermal = thermal_replay(electrical)
    report = {
        "passed": True, "source_commit": os.environ.get("GITHUB_SHA", "unrecorded"),
        "inputs_sha256": sha256(OUT / "inputs.json"), "sources": CONFIG["sources"],
        "parameter_source": CONFIG["parameter_source"], "references": reference,
        "electrical": electrical, "magnetic_map": magnetic_map, "robot": robot,
        "thermal": thermal,
        "limits": [
            "upstream example magnetic map is not the user's motor calibration",
            "synthetic motor/gear/thermal/sensor parameters are not UR5e actuator parameters",
            "one robot joint electrical co-simulation; other axes use upstream holding servos",
            "ideal switch events with dead time; no semiconductor parasitics, recovery or EMI",
            "short switching-coupled thermal feedback; long thermal plot is heat replay",
            "sampled thermal heat rates; extra device heat has no matching DC loss branch",
            "fixed macro-step torque exchange; report convergence and interface approximation",
        ],
        "command": "python benchmarks/validate_open_models.py",
        "environment": {
            "python": sys.version, "mujoco": mujoco.__version__,
            "packages": subprocess.check_output(
                [sys.executable, "-m", "pip", "freeze"], text=True
            ),
        },
    }
    save("report-data.json", report)
    print("open-models.json: " + json.dumps({
        "passed": True, "electrical_cases": len(electrical),
        "robot_cases": len(robot["cases"]), "references": reference,
        "robot_convergence_rad": robot["macro_step_halving_error_rad"],
    }), flush=True)


if __name__ == "__main__":
    main()
