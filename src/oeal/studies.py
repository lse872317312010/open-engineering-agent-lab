"""IR 0.2 fixed model registry, shared SI streams, execution and raw-data verification."""

import copy
import hashlib
import json
import math
import os
import sys
from importlib.resources import files
from pathlib import Path

import numpy as np
from jsonschema import Draft202012Validator

from oeal.foc import FOCConfig, simulate_foc
from oeal.foc_io import COLUMNS
from oeal.ir import document_hash
from oeal.models import MotorParameters

SCHEMA = json.loads(files("oeal").joinpath("schemas/ir-0.2.json").read_text())
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA)
ASSET_LOCK = json.loads(files("oeal").joinpath("schemas/asset-lock.json").read_text())
MOTOR = dict(stator_resistance_ohm=0.3, d_inductance_h=0.0008, q_inductance_h=0.0008,
             flux_linkage_wb=0.03, pole_pairs=7, inertia_kg_m2=0.002, viscous_friction_nms=1e-5)
DEFAULT = dict(
    duration_s=0.03, control_period_s=50e-6, integration_step_s=5e-6, step_time_s=0.005,
    id_reference_a=0.0, iq_reference_a=5.0, vdc_v=48.0, current_limit_a=15.0,
    bandwidth_per_s=1000.0, tracking_rate_per_s=1000.0, delay_samples=1,
)
FOC_FIELDS = frozenset(DEFAULT)
EXTERNAL = frozenset({
    "pwm", "sensors", "thermal_feedback", "dc_bus", "deadtime_s", "device_drop_v",
    "core_conductance_s", "energy_consistent",
})
ROBOT_FIELDS = frozenset({
    "macro_step_s", "backlash_rad", "fixture", "outer_kp_nm_per_rad",
    "outer_kd_nms_per_rad", "gravity_feedforward_gain", "position_step_rad",
    "position_start_s", "position_ramp_s", "payload_kg", "shaft_stiffness_nm_per_rad",
    "coupling_method", "robot_integrator", "position_cycle_period_s",
})
REGISTRY = {
    "native_foc_v1": dict(backend="native", fields=FOC_FIELDS | {"load_nm"},
                          description="native sampled PMSM FOC"),
    "native_joint_v1": dict(
        backend="native", fields=FOC_FIELDS | {
            "load_nm", "shaft_stiffness_nm_per_rad", "ambient_c", "deadtime_s",
            "device_drop_v", "ripple_fraction",
        }, description="native nine-state coupled joint",
    ),
    "motulator_pmsm_v1": dict(
        backend="motulator", fields=FOC_FIELDS | EXTERNAL | {"load_nm"},
        description="upstream switching PMSM drive",
    ),
    "baldor_map_v1": dict(
        backend="motulator", fields=FOC_FIELDS | EXTERNAL | {"load_nm"},
        description="pinned upstream nonlinear magnetic-map example",
    ),
    "ur5e_joint_v1": dict(
        backend="mujoco_motulator",
        fields=(FOC_FIELDS - {"iq_reference_a", "step_time_s"}) | EXTERNAL | ROBOT_FIELDS,
        description="one electrically driven UR5e shoulder joint",
    ),
}


def model_parameters(model):
    defaults = MOTOR | ({
        "ur5e_joint_v1": {"inertia_kg_m2": 5e-5},
        "baldor_map_v1": {"inertia_kg_m2": 0.05},
    }.get(model["profile"], {}))
    return defaults | values(model["parameters"])


def values(parameters):
    return {key: value["value"] if isinstance(value, dict) else value
            for key, value in parameters.items()}


def resolved_settings(document):
    profile = document["model"]["profile"]
    settings = DEFAULT | values(document["settings"])
    if profile == "ur5e_joint_v1":
        settings = settings | {
            "macro_step_s": 0.0002, "backlash_rad": 0.0, "fixture": False,
            "outer_kp_nm_per_rad": 150.0, "outer_kd_nms_per_rad": 20.0,
            "gravity_feedforward_gain": 1.0, "position_step_rad": 0.08,
            "position_start_s": 0.02, "position_ramp_s": 0.12, "payload_kg": 0.0,
            "shaft_stiffness_nm_per_rad": 500.0,
            "coupling_method": "jacobi", "robot_integrator": "implicitfast",
        } | values(document["settings"])
    elif profile == "baldor_map_v1":
        settings = settings | {"vdc_v": 540.0, "iq_reference_a": 10.0,
                               "current_limit_a": 20.0} | values(document["settings"])
    return settings


def catalog():
    return {
        name: {"backend": info["backend"], "description": info["description"],
               "settings": sorted(info["fields"]),
               "motor_overrides": [] if name == "baldor_map_v1" else sorted(MOTOR)}
        for name, info in REGISTRY.items()
    }


def validate_study(document):
    # Serialization rejects nonfinite data before optional libraries are imported.
    document_hash(document)
    VALIDATOR.validate(document)
    kind = document["kind"]
    if kind == "SimulationResult":
        for stream in document["streams"].values():
            columns, units, rows = stream["columns"], stream["units"], stream["samples"]
            if columns[0] != "time_s" or units[0] != "s":
                raise ValueError("first signal must be time_s in seconds")
            if units != [signal_unit(name) for name in columns]:
                raise ValueError("result signal unit differs from its registered SI meaning")
            if len(set(columns)) != len(columns) or len(columns) != len(units):
                raise ValueError("duplicate columns or inconsistent unit count")
            if any(len(row) != len(columns) for row in rows):
                raise ValueError("sample shape differs from columns")
            event = stream["sample_semantics"] in {"switching_events", "solver_samples"}
            if any(b[0] < a[0] if event else b[0] <= a[0]
                   for a, b in zip(rows[:-1], rows[1:], strict=True)):
                raise ValueError("stream time is invalid")
        if document["primary_stream"] not in document["streams"]:
            raise ValueError("missing primary stream")
        if document_hash(document["streams"]) != document["raw_sha256"]:
            raise ValueError("raw stream hash mismatch")
        return document
    model = document if kind == "ModelSpec" else document["model"]
    profile = model["profile"]
    if profile == "baldor_map_v1" and model["parameters"]:
        raise ValueError("pinned magnetic-map machine parameters cannot be overridden")
    MotorParameters(**model_parameters(model))
    if kind == "ModelSpec":
        return document
    entry = REGISTRY[profile]
    if document["backend"] != entry["backend"]:
        raise ValueError("model/backend capability mismatch")
    if set(document["settings"]) - entry["fields"]:
        raise ValueError("unsupported settings for this registered model")
    s = resolved_settings(document)
    if "controller_parameters" in document and profile not in {
        "motulator_pmsm_v1", "ur5e_joint_v1"
    }:
        raise ValueError("nominal overrides require a registered linear external machine")
    if s.get("energy_consistent", False) and (
        profile not in {"motulator_pmsm_v1", "ur5e_joint_v1"}
        or s.get("core_conductance_s", 0) != 0 or s.get("dc_bus") == "diode"
        or s.get("fixture", False)
    ):
        raise ValueError("energy mode requires linear machine, no core loss/fixture/diode bus")
    if ("energy_balance_abs_j" in document["acceptance"]
            and not s.get("energy_consistent", False)):
        raise ValueError("energy acceptance requires the explicit energy mode")
    FOCConfig(**{key: s[key] for key in FOC_FIELDS})
    ticks = round(s["duration_s"] / s["control_period_s"]) + 1
    if ticks > document["budget"]["control_ticks"]:
        raise ValueError("control tick budget exceeded")
    minimum = 4 * (ticks - 1) * math.ceil(s["control_period_s"] / s["integration_step_s"])
    if minimum > document["budget"]["solver_evaluations"]:
        raise ValueError("solver evaluation budget too small")
    if profile == "ur5e_joint_v1":
        if s["coupling_method"] == "midpoint_predictor" and (
            not s.get("energy_consistent", False) or s["robot_integrator"] != "rk4"
            or s["backlash_rad"] != 0 or s["fixture"]
        ):
            raise ValueError("midpoint predictor requires energy mode, RK4, no gap/fixture")
        ratio = s["macro_step_s"] / s["control_period_s"]
        if not math.isclose(ratio, round(ratio), rel_tol=0, abs_tol=1e-9):
            raise ValueError("macro step must be an integer number of controller ticks")
        if not math.isclose(
            s["duration_s"] / s["macro_step_s"],
            round(s["duration_s"] / s["macro_step_s"]), rel_tol=0, abs_tol=1e-8,
        ):
            raise ValueError("duration must align with macro steps")
        if "position_cycle_period_s" in s:
            if (s["position_start_s"] >= s["duration_s"]
                    or s["position_cycle_period_s"] < 4 * s["macro_step_s"]):
                raise ValueError("cycle needs an active window and at least four macro intervals")
            if "position_peak_error_rad" not in document["acceptance"]:
                raise ValueError("cycle requires a whole-trajectory peak-error goal")
        elif s["position_start_s"] + s["position_ramp_s"] >= s["duration_s"]:
            raise ValueError("reference ramp must finish inside the experiment")
        if "position_tail_error_rad" not in document["acceptance"]:
            raise ValueError("robot study needs a position acceptance goal")
    elif "current_tail_error_a" not in document["acceptance"]:
        raise ValueError("drive study needs a current acceptance goal")
    return document


def resolve_assets(profile, root):
    needed = []
    if profile == "baldor_map_v1":
        needed = ["baldor_400rpm_map.npz"]
    elif profile == "ur5e_joint_v1":
        needed = [name for name in ASSET_LOCK["files"] if name.startswith("ur5e/")]
    if not needed:
        return {}
    if root is None:
        raise ValueError("this profile needs the trusted host's --assets-root")
    root = Path(root).resolve()
    result = {}
    for name in needed:
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError("asset escapes its trusted root")
        raw = path.read_bytes()
        digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if digest != ASSET_LOCK["files"][name]:
            raise ValueError("pinned asset hash mismatch: " + name)
        result[name] = path
    return result


def signal_unit(name):
    if name.startswith("duty_") or name in {
        "voltage_limited", "current_limited", "enabled", "tripped", "contacts",
        "qa", "qb", "qc", "blank_a", "blank_b", "blank_c", "predictor_fallback",
        "resolved_transition", "torque_history_windows",
    }:
        return "1"
    for suffix, unit in (
        ("_rad_s2", "rad/s^2"), ("_kg_m2", "kg*m^2"), ("_rad_s", "rad/s"),
        ("_nms2", "N*m*s^2"), ("_nms", "N*m*s"), ("_nm", "N*m"), ("_rad", "rad"), ("_s", "s"),
        ("_n", "N"), ("_a", "A"), ("_v", "V"), ("_c", "degC"), ("_w", "W"), ("_j", "J"),
    ):
        if name.endswith(suffix):
            return unit
    raise ValueError("unknown signal unit: " + name)


def stream(columns, samples, semantics):
    return dict(columns=list(columns), units=[signal_unit(c) for c in columns],
                samples=np.asarray(samples, dtype=float).tolist(), sample_semantics=semantics)


def _native(document, s, motor):
    if document["model"]["profile"] == "native_foc_v1":
        result = simulate_foc(
            motor, FOCConfig(**{k: s[k] for k in FOC_FIELDS}),
            load_torque_nm=s.get("load_nm", 0.0),
        )
        return {"control": stream(COLUMNS, result.samples, "control_ticks_and_endpoint")}, {}
    from oeal.multiphysics import (
        InverterParameters,
        JointParameters,
        ThermalParameters,
        run_joint,
    )

    trace = run_joint(
        motor, FOCConfig(**{k: s[k] for k in FOC_FIELDS}),
        JointParameters(stiffness_nm_per_rad=s.get("shaft_stiffness_nm_per_rad", 80)),
        ThermalParameters(ambient_c=s.get("ambient_c", 25)),
        InverterParameters(
            ripple_fraction=s.get("ripple_fraction", 0),
            deadtime_s=s.get("deadtime_s", 0), device_drop_v=s.get("device_drop_v", 0),
        ), load_nm=s.get("load_nm", 0),
    )
    return {"control": stream(trace["columns"], trace["samples"],
                              "control_ticks_and_endpoint")}, trace["parameters"]


def _external(document, s, assets, motor):
    from motulator.common.utils import complex2abc

    from oeal.backends.motulator import CONTROL_COLUMNS, load_magnetic_map, run_drive

    profile = document["model"]["profile"]
    config = dict(
        s, period_s=s["control_period_s"], max_step_s=s["integration_step_s"],
        bus_v=s["vdc_v"], delay=bool(s["delay_samples"]), seed=document["seed"],
        max_solver_evaluations=document["budget"]["solver_evaluations"],
        motor_parameters=vars(motor),
        controller_parameters=values(document.get("controller_parameters", {})),
    )
    config["dc_bus"] = None if s.get("dc_bus", "constant") == "constant" else s["dc_bus"]
    magnetic, robot = None, None
    if profile == "baldor_map_v1":
        magnetic, _, current = load_magnetic_map(assets["baldor_400rpm_map.npz"])
        config["nonlinear"] = True
    if profile == "ur5e_joint_v1":
        from oeal.backends.robot import ROBOT_COLUMNS, RobotLoad, load_robot

        mdl, data, _ = load_robot(
            assets["ur5e/ur5e.xml"], s["macro_step_s"], s["fixture"], s["payload_kg"],
            integrator=s["robot_integrator"],
        )
        robot = RobotLoad(mdl, data, config)
    result, controller = run_drive(config, magnetic_map=magnetic, robot=robot)
    control = np.asarray(controller.rows)
    streams = {"control": stream(CONTROL_COLUMNS, control, "control_ticks_and_endpoint")}
    t = result.mdl.t
    active = t <= s["duration_s"] + 1e-12
    wave_columns = [
        "time_s", "ia_a", "ib_a", "ic_a", "ua_v", "ub_v", "uc_v",
        "bus_v", "dc_current_a", "id_a", "iq_a", "torque_nm",
    ]
    waves = np.column_stack((
        t, np.asarray(complex2abc(result.mdl.machine.i_s_ab)).T,
        np.asarray(complex2abc(result.mdl.converter.u_c_ab)).T,
        result.mdl.converter.u_dc, result.mdl.converter.i_dc_int,
        result.mdl.machine.i_s_dq.real, result.mdl.machine.i_s_dq.imag,
        result.mdl.machine.tau_M,
    ))[active]
    streams["waveforms"] = stream(wave_columns, waves, "solver_samples")
    gates = np.asarray(controller.drive.oeal_pwm_records)
    gates = gates[gates[:, 0] < s["duration_s"] - 1e-12].copy()
    gates[:, 1] = np.minimum(gates[:, 1], s["duration_s"] - gates[:, 0])
    streams["gates"] = stream(
        ["time_s", "duration_s", "qa", "qb", "qc", "blank_a", "blank_b", "blank_c", "enabled"],
        gates, "switching_events",
    )
    if robot is not None:
        streams["joint"] = stream(ROBOT_COLUMNS, robot.rows, "macro_ticks_and_endpoint")
        if robot.coupling_rows:
            from oeal.backends.robot import COUPLING_COLUMNS

            streams["coupling"] = stream(
                COUPLING_COLUMNS, robot.coupling_rows, "macro_ticks_and_endpoint"
            )
    if s.get("energy_consistent", False):
        from oeal.energy import ENERGY_COLUMNS

        streams["energy"] = stream(
            ENERGY_COLUMNS, controller.energy_rows, "control_ticks_and_endpoint"
        )
        if robot is not None:
            from oeal.backends.robot import ROBOT_ENERGY_COLUMNS

            audit = np.asarray(robot.energy_rows)
            energy = np.asarray(controller.energy_rows)
            index = np.round(audit[:, 0] / s["control_period_s"]).astype(int)
            motor_work = energy[index, ENERGY_COLUMNS.index("load_work_j")]
            imported = energy[index, ENERGY_COLUMNS.index("shaft_heat_import_j")]
            interface = motor_work - imported - audit[:, 2] - (audit[:, 5] - audit[0, 5])
            local = energy[index, ENERGY_COLUMNS.index("local_residual_j")]
            extended = local + interface - audit[:, 6]
            streams["co_sim_energy"] = stream(
                [*ROBOT_ENERGY_COLUMNS, "motor_port_work_j", "shaft_heat_j",
                 "interface_residual_j", "extended_residual_j"],
                np.column_stack((audit, motor_work, imported, interface, extended)),
                "macro_ticks_and_endpoint",
            )
    domain = True
    if profile == "baldor_map_v1":
        points, _ = current.get_input_output()
        psi = result.mdl.machine.psi_s_dq
        domain = bool(
            np.all(psi.real >= points.real.min() - 1e-10)
            and np.all(psi.real <= points.real.max() + 1e-10)
            and np.all(psi.imag >= points.imag.min() - 1e-10)
            and np.all(psi.imag <= points.imag.max() + 1e-10)
        )
    context = {
        "nominal_machine": vars(controller.nominal), "magnetic_domain_passed": domain,
        "physical_machine": controller.drive.oeal_physical_parameters,
        "solver_evaluations": controller.drive.oeal_solver_calls,
    }
    if robot is not None:
        context["coupling_parameters"] = robot.coupling_parameters()
    if s.get("energy_consistent", False):
        context["energy_parameters"] = controller.drive.oeal_energy.describe()
    return streams, context


def recompute(document, result):
    """Compute protected goals from real signal streams, ignoring reported metrics."""
    s = resolved_settings(document)
    signals = result["streams"]
    primary = signals[result["primary_stream"]]
    rows = np.asarray(primary["samples"], dtype=float)
    times = rows[:, 0]
    period = s["macro_step_s"] if result["primary_stream"] == "joint" else s["control_period_s"]
    expected = np.arange(round(s["duration_s"] / period) + 1) * period
    if len(times) != len(expected) or not np.allclose(times, expected, atol=1e-12, rtol=0):
        raise ValueError("primary trace does not cover the complete protected experiment")
    metrics = {}
    control = signals["control"]
    data = np.asarray(control["samples"], dtype=float)
    names = control["columns"]
    control_times = np.arange(round(s["duration_s"] / s["control_period_s"]) + 1)
    control_times = control_times * s["control_period_s"]
    if len(data) != len(control_times) or not np.allclose(
        data[:, 0], control_times, atol=1e-12, rtol=0
    ):
        raise ValueError("control stream does not cover the protected clock")
    current_peak = float(np.hypot(data[:, names.index("id_a")],
                                  data[:, names.index("iq_a")]).max())
    if "waveforms" in signals:
        wave = signals["waveforms"]
        samples = np.asarray(wave["samples"], dtype=float)
        current_peak = max(current_peak, float(np.hypot(
            samples[:, wave["columns"].index("id_a")],
            samples[:, wave["columns"].index("iq_a")],
        ).max()))
    metrics["current_peak_a"] = current_peak
    if result["primary_stream"] == "joint":
        q = rows[:, primary["columns"].index("joint_angle_rad")]
        ref = rows[:, primary["columns"].index("reference_rad")]
        if "position_cycle_period_s" in s:
            elapsed = np.maximum(times - s["position_start_s"], 0)
            expected_ref = q[0] + s["position_step_rad"] / 2 * (
                1 - np.cos(2 * np.pi * elapsed / s["position_cycle_period_s"])
            )
        else:
            expected_ref = q[0] + s["position_step_rad"] * np.clip(
                (times - s["position_start_s"]) / s["position_ramp_s"], 0, 1
            )
        if not np.allclose(ref, expected_ref, atol=1e-12, rtol=0):
            raise ValueError("position trace reference differs from protected target")
        error = q - expected_ref
        metrics["position_peak_error_rad"] = float(np.max(np.abs(error)))
        metrics["position_rmse_rad"] = float(np.sqrt(np.mean(error ** 2)))
        tail = times >= 0.9 * s["duration_s"]
        metrics["position_tail_error_rad"] = float(np.mean(np.abs(q[tail] - expected_ref[tail])))
        metrics["shaft_torque_peak_nm"] = float(
            np.abs(rows[:, primary["columns"].index("shaft_torque_nm")]).max()
        )
    else:
        iq = data[:, names.index("iq_a")]
        tail = data[:, 0] >= 0.9 * s["duration_s"]
        metrics["current_tail_error_a"] = float(abs(iq[tail].mean() - s["iq_reference_a"]))
    numeric = all(np.all(np.isfinite(np.asarray(v["samples"]))) for v in signals.values())
    numeric = bool(numeric and result["context"].get("magnetic_domain_passed", True))
    if s.get("energy_consistent", False):
        from oeal.energy import ENERGY_COLUMNS, recompute_balances

        energy = signals["energy"]
        energy_data = np.asarray(energy["samples"])
        if energy["columns"] != ENERGY_COLUMNS:
            raise ValueError("energy stream differs from registered energy quantities")
        if len(energy_data) != len(control_times) or not np.allclose(
            energy_data[:, 0], control_times, atol=1e-12, rtol=0
        ):
            raise ValueError("energy stream does not cover the protected clock")
        _, _, energy_metrics = recompute_balances(energy["columns"], energy["samples"])
        metrics.update(energy_metrics)
        numeric = bool(
            numeric and metrics["energy_balance_abs_j"] <= metrics["energy_balance_limit_j"]
            and metrics["thermal_balance_abs_j"] <= metrics["energy_balance_limit_j"]
        )
        if "co_sim_energy" in signals:
            audit = signals["co_sim_energy"]
            rows = np.asarray(audit["samples"])
            for name in ("interface_residual_j", "extended_residual_j"):
                metrics[name] = float(np.max(np.abs(rows[:, audit["columns"].index(name)])))
    if s.get("coupling_method") == "midpoint_predictor":
        trace = signals["coupling"]
        values_ = np.asarray(trace["samples"])
        if len(values_) != len(expected) or not np.allclose(
            values_[:, 0], expected, atol=1e-12, rtol=0
        ):
            raise ValueError("coupling stream does not cover the protected macro clock")
        fallbacks = values_[:, trace["columns"].index("predictor_fallback")]
        residual = values_[:, trace["columns"].index("law_residual_nm")]
        transitions = values_[:, trace["columns"].index("resolved_transition")]
        metrics["resolved_transition_count"] = float(np.sum(transitions))
        metrics["predictor_fallback_count"] = float(np.sum(fallbacks))
        metrics["torque_law_residual_nm"] = float(np.max(np.abs(residual)))
        numeric = bool(numeric and np.all(fallbacks == 0)
                       and metrics["torque_law_residual_nm"] <= 1e-8)
    goals = values(document["acceptance"])
    passed = numeric and all(metrics.get(name, math.inf) <= limit for name, limit in goals.items())
    return metrics, numeric, bool(passed)


def run_study(document, assets_root=None):
    validate_study(document)
    if document["kind"] != "ExperimentSpec":
        raise ValueError("ExperimentSpec required")
    profile = document["model"]["profile"]
    s = resolved_settings(document)
    assets = resolve_assets(profile, assets_root)
    motor = MotorParameters(**model_parameters(document["model"]))
    streams, context = (
        _native(document, s, motor) if document["backend"] == "native"
        else _external(document, s, assets, motor)
    )
    primary = "joint" if profile == "ur5e_joint_v1" else "control"
    result = dict(
        version="0.2", kind="SimulationResult", experiment_sha256=document_hash(document),
        raw_sha256=document_hash(streams), evidence_level="model_simulated",
        backend=document["backend"], profile=profile, primary_stream=primary, streams=streams,
        metrics={}, numeric_passed=False, goal_passed=False,
        context=dict(
            context, source_commit=os.environ.get("GITHUB_SHA", "unrecorded"),
            python=sys.version.split()[0], resolved_settings=s,
            requested_model=copy.deepcopy(document["model"]),
            parameter_source="pinned upstream assets plus declared research parameters",
            asset_hashes={name: ASSET_LOCK["files"][name] for name in assets},
        ),
    )
    result["metrics"], result["numeric_passed"], result["goal_passed"] = recompute(document, result)
    return validate_study(result)


def export_streams(result, output_dir):
    """Export registered signal streams and a shared unit/provenance manifest."""
    import csv

    validate_study(result)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, signal in result["streams"].items():
        with (output_dir / (name + ".csv")).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(signal["columns"])
            writer.writerows(signal["samples"])
    metadata = {
        "experiment_sha256": result["experiment_sha256"], "raw_sha256": result["raw_sha256"],
        "backend": result["backend"], "context": result["context"],
        "streams": {name: {k: v for k, v in signal.items() if k != "samples"}
                    for name, signal in result["streams"].items()},
    }
    (output_dir / "streams.json").write_text(json.dumps(metadata, indent=2, allow_nan=False))
