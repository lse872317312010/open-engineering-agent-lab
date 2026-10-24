"""Menagerie UR5e load model and an explicit torque/velocity co-simulation port."""

import math
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco
import numpy as np

from oeal.coupling import (
    Exchange,
    WeightedTorqueHistory,
    path_average,
    path_midpoint_exchange,
    transmission,
)

ROBOT_COLUMNS = [
    "time_s", "joint_angle_rad", "joint_speed_rad_s", "reference_rad",
    "motor_output_angle_rad", "twist_rad", "shaft_torque_nm", "gravity_nm",
    "contacts", "fixture_force_n", "elastic_energy_j", "damping_power_w",
]


ROBOT_ENERGY_COLUMNS = [
    "time_s", "robot_storage_delta_j", "robot_shaft_work_j",
    "holding_actuator_work_j", "passive_work_j", "spring_j", "robot_balance_residual_j",
]


COUPLING_COLUMNS = [
    "time_s", "held_torque_nm", "actual_delta_rad", "actual_relative_speed_rad_s",
    "free_relative_accel_rad_s2", "robot_effective_inertia_kg_m2",
    "predicted_delta_rad", "predicted_relative_speed_rad_s",
    "predicted_damping_power_w", "law_residual_nm", "motor_torque_impulse_nms",
    "motor_torque_time_moment_nms2",
    "instant_motor_torque_nm", "previous_mean_motor_torque_nm",
    "previous_weighted_motor_torque_nm", "forecast_motor_torque_nm",
    "torque_history_windows", "resolved_transition", "predictor_fallback",
]


def prepare_ur5e(source, output):
    output = Path(output)
    destination = output / "ur5e"
    shutil.copytree(source, destination, dirs_exist_ok=True)
    return destination / "ur5e.xml"


def load_robot(path, macro_step_s=0.0002, fixture=False, payload_kg=0.0, integrator=None):
    """Keep upstream link parameters; replace only one actuator with a torque port."""
    if not math.isfinite(payload_kg) or payload_kg < 0:
        raise ValueError("payload must be finite and nonnegative")
    path = Path(path)
    root = ET.parse(path).getroot()
    root.find("option").set("timestep", str(macro_step_s))
    root.find("option").set("gravity", "0 0 -9.81")
    if integrator is not None:
        if integrator not in {"implicitfast", "rk4"}:
            raise ValueError("unsupported robot integrator")
        root.find("option").set("integrator", "RK4" if integrator == "rk4" else "implicitfast")
    selected_actuator = root.find("./actuator/general[@name='shoulder_lift']")
    selected_actuator.set("gainprm", "0")
    selected_actuator.set("biasprm", "0 0 0")
    compiler = root.find("compiler")
    compiler.set("meshdir", str(path.parent / "assets"))
    wrist = root.find(".//body[@name='wrist_3_link']")
    ET.SubElement(
        wrist, "geom", name="oeal_pad", type="sphere", size="0.03",
        pos="0 0.1 0", rgba="0.1 0.65 0.55 1", mass="0",
    )
    if payload_kg:
        payload = ET.SubElement(wrist, "body", name="oeal_payload", pos="0 0.1 0")
        ET.SubElement(
            payload, "geom", type="sphere", size="0.03", mass=str(payload_kg),
            contype="0", conaffinity="0", rgba="0.6 0.4 0.2 1",
        )
    # The optional payload is a separate body; upstream link inertials stay intact.
    model = mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, 0)
    mujoco.mj_forward(model, data)
    if fixture:
        site = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, "attachment_site")
        pos = data.site_xpos[site] + np.array([0.055, 0, 0])
        ET.SubElement(
            root.find("worldbody"), "geom", name="oeal_fixture", type="sphere",
            size="0.035", pos=" ".join(map(str, pos)), rgba="0.8 0.4 0.2 1",
        )
        model = mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))
        data = mujoco.MjData(model)
        mujoco.mj_resetDataKeyframe(model, data, 0)
        mujoco.mj_forward(model, data)
    # Shoulder lift receives only the independent transmission torque.
    actuator = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, "shoulder_lift")
    model.actuator_gainprm[actuator, :] = 0
    model.actuator_biasprm[actuator, :] = 0
    return model, data, root


class RobotLoad:
    """Jacobi macro-step coupling; each side holds the exchanged shaft torque."""

    def __init__(self, model, data, config):
        self.model, self.data, self.config = model, data, config
        self.index = int(model.joint("shoulder_lift_joint").dofadr[0])
        self.qindex = int(model.joint("shoulder_lift_joint").qposadr[0])
        self.initial_angle = float(data.qpos[self.qindex])
        self.period = config["macro_step_s"]
        self.ticks_per_macro = round(self.period / config["period_s"])
        if not math.isclose(
            self.ticks_per_macro * config["period_s"], self.period, abs_tol=1e-12
        ):
            raise ValueError("macro step must be an integer number of controller ticks")
        self.method = config.get("coupling_method", "jacobi")
        if self.method not in {"jacobi", "midpoint_predictor"}:
            raise ValueError("unsupported coupling method")
        if self.method == "midpoint_predictor" and (
            not config.get("energy_consistent", False)
            or model.opt.integrator != mujoco.mjtIntegrator.mjINT_RK4
            or config.get("backlash_rad", 0) != 0 or config.get("fixture", False)
        ):
            raise ValueError("midpoint predictor requires energy mode, RK4, no gap/fixture")
        self.coupling_rows = []
        self.torque_history = WeightedTorqueHistory()
        self.ratio = 50.0
        self.torque = 0.0
        self.rows = []
        self.energy_rows = []
        self.thermal_power_w = 0.0
        self.shaft_work_j = self.actuator_work_j = self.passive_work_j = 0.0
        self.initial_energy_j = self.mechanical_energy() if config.get(
            "energy_consistent", False
        ) else 0.0
        self.fixture_id = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_GEOM, "oeal_fixture"
        )

    def sample(self, controller, drive):
        if controller.tick % self.ticks_per_macro == 0:
            audit = self.config.get("energy_consistent", False)
            if audit:
                previous_q = self.data.qpos.copy()
                previous_actuator = self.data.qfrc_actuator.copy()
                previous_passive = self.data.qfrc_passive.copy()
                held_torque = self.torque
            if controller.tick > 0:
                self.data.qfrc_applied[:] = 0
                self.data.qfrc_applied[self.index] = self.torque
                mujoco.mj_step(self.model, self.data)
            mujoco.mj_forward(self.model, self.data)
            if audit and controller.tick > 0:
                delta_q = self.data.qpos - previous_q
                self.shaft_work_j += held_torque * delta_q[self.qindex]
                self.actuator_work_j += float(
                    0.5 * (previous_actuator + self.data.qfrc_actuator) @ delta_q
                )
                self.passive_work_j += float(
                    0.5 * (previous_passive + self.data.qfrc_passive) @ delta_q
                )
            q = float(self.data.qpos[self.qindex])
            velocity = float(self.data.qvel[self.index])
            delta = controller.theta_continuous / self.ratio - (q - self.initial_angle)
            relative_speed = float(drive.mechanics.out.w_M) / self.ratio - velocity
            self.torque, energy, damping = transmission(
                delta, relative_speed,
                stiffness=self.config.get("shaft_stiffness_nm_per_rad", 500.0),
                backlash=self.config.get("backlash_rad", 0.0)
            )
            if self.method == "midpoint_predictor":
                exchange = self.predict_exchange(controller, drive, delta, relative_speed)
                self.torque, damping = exchange.torque_nm, exchange.damping_power_w
                # 'energy' deliberately remains the actual endpoint spring energy.
            if audit:
                self.thermal_power_w = damping
                storage_delta = self.mechanical_energy() - self.initial_energy_j
                balance = (storage_delta - self.shaft_work_j - self.actuator_work_j
                           - self.passive_work_j)
                self.energy_rows.append([
                    controller.t, storage_delta, self.shaft_work_j, self.actuator_work_j,
                    self.passive_work_j, energy, balance,
                ])
            drive.mechanics.set_external_load_torque(self.torque / self.ratio)
            contacts, force = 0, 0.0
            for i in range(self.data.ncon):
                contact = self.data.contact[i]
                if self.fixture_id >= 0 and self.fixture_id in (contact.geom1, contact.geom2):
                    wrench = np.zeros(6)
                    mujoco.mj_contactForce(self.model, self.data, i, wrench)
                    contacts += 1
                    force += float(np.linalg.norm(wrench[:3]))
            ref = self.reference(controller.t)
            gravity = float(self.data.qfrc_bias[self.index])
            self.rows.append([
                controller.t, q, velocity, ref, controller.theta_continuous / self.ratio,
                delta, self.torque, gravity, contacts, force, energy, damping,
            ])
        q = float(self.data.qpos[self.qindex])
        velocity = float(self.data.qvel[self.index])
        target = self.reference(controller.t)
        # Synthetic outer-loop PD plus model bias feedforward, not a UR controller.
        required = (
            self.config.get("outer_kp_nm_per_rad", 150) * (target - q)
            - self.config.get("outer_kd_nms_per_rad", 20) * velocity
            + self.config.get("gravity_feedforward_gain", 1) * self.data.qfrc_bias[self.index]
        )
        kt = 1.5 * controller.nominal.n_p * controller.nominal.psi_f
        return float(required / (self.ratio * kt))

    def predict_exchange(self, controller, drive, delta, relative_speed):
        mass = np.zeros((self.model.nv, self.model.nv))
        mujoco.mj_fullM(self.model, mass, self.data.qM)
        basis = np.zeros(self.model.nv)
        basis[self.index] = 1
        gain = float(np.linalg.solve(mass, basis)[self.index])
        if not math.isfinite(gain) or gain <= 0:
            raise ValueError("robot effective inverse inertia is not positive")
        mechanics = drive.mechanics
        speed = float(mechanics.out.w_M)
        damping = mechanics.B_L(speed) if callable(mechanics.B_L) else mechanics.B_L
        instant = float(drive.machine.out.tau_M)
        impulse = (float(drive.oeal_energy.state.motor_torque_impulse_nms.real)
                   if controller.t > 0 else 0.0)
        moment = (float(drive.oeal_energy.state.motor_torque_time_moment_nms2.real)
                  if controller.t > 0 else 0.0)
        mean, weighted, forecast, windows = self.torque_history.observe(
            controller.t, impulse, moment, instant
        )
        motor_free = (forecast - damping * speed) / (
            mechanics.J * self.ratio
        )
        robot_free = float(self.data.qacc[self.index]) - gain * float(
            self.data.qfrc_applied[self.index]
        )
        free = motor_free - robot_free
        inverse = 1 / (mechanics.J * self.ratio ** 2) + gain
        stiffness = self.config.get("shaft_stiffness_nm_per_rad", 500.0)
        exchange = path_midpoint_exchange(
            delta, relative_speed, free, inverse, self.period, stiffness=stiffness
        )
        if self.data.nefc:
            torque, _, heat = transmission(delta, relative_speed, stiffness=stiffness)
            v_mid = relative_speed + self.period / 2 * (free - inverse * torque)
            d_mid = delta + self.period / 2 * v_mid
            residual = torque - path_average(
                delta, v_mid, self.period, stiffness=stiffness
            )[0]
            exchange = Exchange(torque, d_mid, v_mid, heat, residual, True)
        self.coupling_rows.append([
            controller.t, exchange.torque_nm, delta, relative_speed, free, 1 / gain,
            exchange.delta_mid_rad, exchange.speed_mid_rad_s, exchange.damping_power_w,
            exchange.law_residual_nm, impulse, moment, instant, mean, weighted,
            forecast, float(windows),
            float(exchange.transition_resolved), float(exchange.fallback),
        ])
        return exchange

    def coupling_parameters(self):
        return {
            "coupling_method": self.method,
            "robot_integrator": "rk4" if self.model.opt.integrator
            == mujoco.mjtIntegrator.mjINT_RK4 else "implicitfast",
            "macro_step_s": self.period, "gear_ratio": self.ratio,
            "shaft_stiffness_nm_per_rad": self.config.get("shaft_stiffness_nm_per_rad", 500),
            "shaft_damping_nms_per_rad": 1.0,
            "fallback_count": int(sum(row[-1] for row in self.coupling_rows)),
            "resolved_transition_count": int(sum(row[-2] for row in self.coupling_rows)),
            "motor_torque_predictor": "causal displacement-weighted means from actual I/M integrals",
            "force_and_heat": "original law integrated on piecewise predicted paths",
            "prediction_scope": "frozen free acceleration, not a nonlinear implicit solve",
            "stored_spring_energy": "actual endpoint deflection; never midpoint storage",
        }

    def mechanical_energy(self):
        mujoco.mj_energyPos(self.model, self.data)
        mujoco.mj_energyVel(self.model, self.data)
        return float(self.data.energy.sum())

    def reference(self, t):
        amplitude = self.config.get("position_step_rad", 0.08)
        start = self.config.get("position_start_s", 0.02)
        ramp = self.config.get("position_ramp_s", 0.12)
        return self.initial_angle + amplitude * min(max((t - start) / ramp, 0), 1)


def robot_reference_checks(path):
    model = mujoco.MjModel.from_xml_path(str(path))
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, 0)
    model.actuator_gainprm[:] = 0
    model.actuator_biasprm[:] = 0
    model.opt.disableflags |= int(mujoco.mjtDisableBit.mjDSBL_CONTACT)
    data.qvel[:] = 0
    mujoco.mj_forward(model, data)
    gravity = data.qfrc_bias.copy()
    finite_difference = np.zeros(model.nv)
    for i in range(model.nv):
        original = float(data.qpos[i])
        values = []
        for sign in (1, -1):
            data.qpos[i] = original + sign * 1e-6
            mujoco.mj_forward(model, data)
            mujoco.mj_energyPos(model, data)
            values.append(float(data.energy[0]))
        data.qpos[i] = original
        finite_difference[i] = (values[0] - values[1]) / 2e-6
    mujoco.mj_forward(model, data)
    mass = np.zeros((model.nv, model.nv))
    mujoco.mj_fullM(model, mass, data.qM)
    acceleration = np.linspace(-0.1, 0.1, model.nv)
    data.qacc[:] = acceleration
    mujoco.mj_inverse(model, data)
    data.qfrc_applied[:] = data.qfrc_inverse
    mujoco.mj_forward(model, data)
    return {
        "gravity_gradient_error_nm": float(np.max(np.abs(gravity - finite_difference))),
        "forward_inverse_error_rad_s2": float(np.max(np.abs(data.qacc - acceleration))),
        "mass_min_eigenvalue_kg_m2": float(np.linalg.eigvalsh(mass).min()),
        "joint_count": int(model.nv),
    }
