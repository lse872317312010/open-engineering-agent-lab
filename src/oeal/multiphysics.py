"""Synthetic electro-mechanical-thermal joint models with explicit SI conventions."""

import math
from dataclasses import asdict, dataclass
from functools import partial

import numpy as np

from oeal.current_control import CurrentPIParameters, CurrentPIState, current_control_step
from oeal.foc import FOCConfig, decoupling_voltage
from oeal.models import MotorParameters, PMSMState
from oeal.transforms import clarke, inverse_clarke, inverse_park, park


def _finite_parameters(instance, nonnegative=(), unrestricted=()):
    for name, value in vars(instance).items():
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
        if name in unrestricted:
            continue
        if (value < 0 if name in nonnegative else value <= 0):
            raise ValueError(f"invalid parameter range: {name}")


@dataclass(frozen=True)
class JointParameters:
    ratio: float = 10.0
    load_inertia_kg_m2: float = 0.02
    stiffness_nm_per_rad: float = 80.0
    damping_nms: float = 0.15
    motor_coulomb_nm: float = 0.002
    load_coulomb_nm: float = 0.02
    load_viscous_nms: float = 0.02
    friction_smoothing_rad_s: float = 0.1
    transmission_error_rad: float = 0.0001

    def __post_init__(self):
        _finite_parameters(self, (
            "damping_nms", "motor_coulomb_nm", "load_coulomb_nm",
            "load_viscous_nms", "transmission_error_rad",
        ))
        if self.transmission_error_rad >= 1 / self.ratio:
            raise ValueError("transmission error must be smaller than inverse gear ratio")


@dataclass(frozen=True)
class ThermalParameters:
    winding_j_per_k: float = 60.0
    case_j_per_k: float = 200.0
    board_j_per_k: float = 25.0
    winding_case_k_per_w: float = 0.8
    case_ambient_k_per_w: float = 2.0
    board_case_k_per_w: float = 1.2
    board_ambient_k_per_w: float = 4.0
    ambient_c: float = 25.0
    copper_alpha_per_k: float = 0.00393
    rds_ohm: float = 0.02
    switching_j_per_a: float = 0.00002
    switching_hz: float = 120000.0
    stop_winding_c: float = 120.0
    stop_board_c: float = 100.0

    def __post_init__(self):
        _finite_parameters(self, (
            "copper_alpha_per_k", "rds_ohm", "switching_j_per_a",
        ), ("ambient_c", "stop_winding_c", "stop_board_c"))
        if self.ambient_c <= -273.15:
            raise ValueError("ambient below absolute zero")
        if min(self.stop_winding_c, self.stop_board_c) <= self.ambient_c:
            raise ValueError("illustrative stop thresholds must exceed ambient")


@dataclass(frozen=True)
class InverterParameters:
    ripple_fraction: float = 0.0
    ripple_hz: float = 200.0
    deadtime_s: float = 0.0
    device_drop_v: float = 0.0
    sign_smoothing_a: float = 0.05

    def __post_init__(self):
        _finite_parameters(self, ("ripple_fraction", "deadtime_s", "device_drop_v"))
        if self.ripple_fraction >= 0.5:
            raise ValueError("ripple fraction must be smaller than 0.5")


def joint_terms(x, parameters):
    theta, wm, load_theta, wl = x
    p = parameters
    a = 1 / p.ratio - p.transmission_error_rad * math.cos(theta)
    delta = theta / p.ratio - load_theta - p.transmission_error_rad * math.sin(theta)
    rate = a * wm - wl
    torque = p.stiffness_nm_per_rad * delta + p.damping_nms * rate
    return a, delta, rate, torque


def joint_energy(x, motor, parameters):
    _, delta, _, _ = joint_terms(x, parameters)
    return (
        0.5 * motor.inertia_kg_m2 * x[1] ** 2
        + 0.5 * parameters.load_inertia_kg_m2 * x[3] ** 2
        + 0.5 * parameters.stiffness_nm_per_rad * delta ** 2
    )


def joint_rhs(x, motor, parameters, electromagnetic_nm, load_nm):
    p = parameters
    a, _, _, torque = joint_terms(x, p)
    _, wm, _, wl = x
    motor_friction = (
        motor.viscous_friction_nms * wm
        + p.motor_coulomb_nm * math.tanh(wm / p.friction_smoothing_rad_s)
    )
    load_friction = (
        p.load_viscous_nms * wl
        + p.load_coulomb_nm * math.tanh(wl / p.friction_smoothing_rad_s)
    )
    return np.array([
        wm, (electromagnetic_nm - a * torque - motor_friction) / motor.inertia_kg_m2,
        wl, (torque - load_nm - load_friction) / p.load_inertia_kg_m2,
    ])


def thermal_rhs(temperatures, parameters, copper_w, board_w, friction_w=0.0):
    p = parameters
    tw, tc, tb = temperatures
    qwc = (tw - tc) / p.winding_case_k_per_w
    qbc = (tb - tc) / p.board_case_k_per_w
    qca = (tc - p.ambient_c) / p.case_ambient_k_per_w
    qba = (tb - p.ambient_c) / p.board_ambient_k_per_w
    return np.array([
        (copper_w - qwc) / p.winding_j_per_k,
        (qwc + qbc + friction_w - qca) / p.case_j_per_k,
        (board_w - qbc - qba) / p.board_j_per_k,
    ])


def losses(motor, thermal, tw, id_a, iq_a):
    resistance = motor.stator_resistance_ohm * (1 + thermal.copper_alpha_per_k * (tw - 25))
    if resistance <= 0:
        raise ValueError("temperature model outside positive resistance domain")
    square = id_a * id_a + iq_a * iq_a
    copper = 1.5 * resistance * square
    board = (
        1.5 * thermal.rds_ohm * square
        + thermal.switching_j_per_a * thermal.switching_hz * math.sqrt(square)
    )
    return resistance, copper, board


def inverter_voltage(t, state, alpha, beta, motor, control, thermal, inverter):
    bus = control.vdc_v * (
        1 + inverter.ripple_fraction * math.sin(2 * math.pi * inverter.ripple_hz * t)
    )
    theta = motor.pole_pairs * state[2]
    ca, cb = inverse_park(state[0], state[1], theta)
    phase_current = inverse_clarke(ca, cb)
    phase_voltage = inverse_clarke(alpha, beta)
    drop = bus * inverter.deadtime_s * thermal.switching_hz + inverter.device_drop_v
    actual = [
        voltage - drop * math.tanh(current / inverter.sign_smoothing_a)
        for voltage, current in zip(phase_voltage, phase_current, strict=True)
    ]
    a, b, _ = clarke(*actual)
    magnitude = math.hypot(a, b)
    if magnitude > bus / math.sqrt(3):
        scale = (bus / math.sqrt(3)) / magnitude
        a, b = a * scale, b * scale
    vd, vq = park(a, b, theta)
    return vd, vq, bus


def coupled_rhs(t, x, motor, joint, thermal, control, inverter, alpha, beta, load_nm):
    vd, vq, _ = inverter_voltage(
        t, x, alpha, beta, motor, control, thermal, inverter
    )
    resistance, copper, board = losses(motor, thermal, x[6], x[0], x[1])
    we = motor.pole_pairs * x[3]
    te = 1.5 * motor.pole_pairs * (
        motor.flux_linkage_wb * x[1]
        + (motor.d_inductance_h - motor.q_inductance_h) * x[0] * x[1]
    )
    mechanical = joint_rhs(x[2:6], motor, joint, te, load_nm)
    _, _, strain_rate, _ = joint_terms(x[2:6], joint)
    friction = (
        motor.viscous_friction_nms * x[3] ** 2
        + joint.motor_coulomb_nm * x[3] * math.tanh(x[3] / joint.friction_smoothing_rad_s)
        + joint.load_viscous_nms * x[5] ** 2
        + joint.load_coulomb_nm * x[5] * math.tanh(x[5] / joint.friction_smoothing_rad_s)
        + joint.damping_nms * strain_rate ** 2
    )
    return np.concatenate((
        [(vd - resistance * x[0] + we * motor.q_inductance_h * x[1])
         / motor.d_inductance_h,
         (vq - resistance * x[1] - we * (motor.d_inductance_h * x[0]
                                       + motor.flux_linkage_wb)) / motor.q_inductance_h],
        mechanical, thermal_rhs(x[6:9], thermal, copper, board, friction),
    ))


def rk4(function, t, x, dt):
    k1 = function(t, x)
    k2 = function(t + dt / 2, x + dt / 2 * k1)
    k3 = function(t + dt / 2, x + dt / 2 * k2)
    k4 = function(t + dt, x + dt * k3)
    result = x + dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
    if not np.all(np.isfinite(result)):
        raise ValueError("nonfinite model state")
    return result


JOINT_COLUMNS = [
    "time_s", "id_a", "iq_a", "motor_angle_rad", "motor_speed_rad_s",
    "load_angle_rad", "load_speed_rad_s", "winding_c", "case_c", "board_c",
    "shaft_torque_nm", "copper_w", "board_loss_w", "bus_v", "voltage_abs_v", "tripped",
]


def run_joint(
    motor: MotorParameters, control: FOCConfig, joint: JointParameters | None = None,
    thermal: ThermalParameters | None = None, inverter: InverterParameters | None = None,
    initial_temperature_c=None, load_nm=0.0,
):
    joint = joint or JointParameters()
    thermal = thermal or ThermalParameters()
    inverter = inverter or InverterParameters()
    temperatures = (
        [thermal.ambient_c] * 3 if initial_temperature_c is None else initial_temperature_c
    )
    if len(temperatures) != 3 or not all(math.isfinite(t) and t > -273.15 for t in temperatures):
        raise ValueError("three finite initial temperatures above absolute zero required")
    if not math.isfinite(load_nm):
        raise ValueError("load_nm must be finite")
    x = np.array([0.0] * 6 + list(temperatures))
    pi = CurrentPIState()
    previous = (0.0, 0.0)
    c = control
    ticks = round(c.duration_s / c.control_period_s)
    step_tick = round(c.step_time_s / c.control_period_s)
    rows, tripped = [], False
    for tick in range(ticks + 1):
        t = tick * c.control_period_s
        tripped = tripped or x[6] >= thermal.stop_winding_c or x[8] >= thermal.stop_board_c
        state = PMSMState(x[0], x[1], x[3], x[2])
        bus = c.vdc_v * (
            1 + inverter.ripple_fraction * math.sin(2 * math.pi * inverter.ripple_hz * t)
        )
        if tripped:
            alpha, beta = 0.0, 0.0
            pi = CurrentPIState()
        elif tick < ticks:
            p = CurrentPIParameters(
                motor.d_inductance_h * c.bandwidth_per_s,
                motor.stator_resistance_ohm * c.bandwidth_per_s,
                motor.q_inductance_h * c.bandwidth_per_s,
                motor.stator_resistance_ohm * c.bandwidth_per_s,
                bus / math.sqrt(3), c.current_limit_a, c.tracking_rate_per_s,
            )
            fd, fq = decoupling_voltage(motor, state)
            command = current_control_step(
                p, pi, reference_d_a=c.id_reference_a if tick >= step_tick else 0,
                reference_q_a=c.iq_reference_a if tick >= step_tick else 0,
                measured_d_a=x[0], measured_q_a=x[1], period_s=c.control_period_s,
                feedforward_d_v=fd, feedforward_q_v=fq,
            )
            pi = command.next_state
            pending = inverse_park(command.vd_v, command.vq_v, motor.pole_pairs * x[2])
            alpha, beta = previous if c.delay_samples else pending
            previous = pending
        else:
            alpha, beta = previous
        vd, vq, bus = inverter_voltage(
            t, x, alpha, beta, motor, c, thermal, inverter
        ) if not tripped else (0.0, 0.0, bus)
        _, copper, board = losses(motor, thermal, x[6], x[0], x[1])
        rows.append([
            t, *x, joint_terms(x[2:6], joint)[3], copper, board, bus,
            math.hypot(vd, vq), float(tripped),
        ])
        if tick == ticks:
            break
        substeps = math.ceil(c.control_period_s / c.integration_step_s)
        dt = c.control_period_s / substeps
        # Stopped command uses ideal zero average voltage (not open-circuit hardware).
        active_inverter = InverterParameters() if tripped else inverter
        for substep in range(substeps):
            x = rk4(
                partial(
                    coupled_rhs, motor=motor, joint=joint, thermal=thermal,
                    control=c, inverter=active_inverter, alpha=alpha, beta=beta,
                    load_nm=load_nm,
                ), t + substep * dt, x, dt,
            )
    return {
        "columns": JOINT_COLUMNS, "samples": np.asarray(rows),
        "parameters": {"motor": asdict(motor), "control": asdict(c), "joint": asdict(joint),
                       "thermal": asdict(thermal), "inverter": asdict(inverter)},
        "evidence_level": "model_simulated", "parameter_source": "synthetic_research",
    }
