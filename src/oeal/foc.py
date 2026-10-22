"""Sampled FOC with an ideal average inverter and stationary voltage hold."""

import math
from dataclasses import dataclass

import numpy as np

from oeal.current_control import (
    CurrentPIParameters,
    CurrentPIState,
    current_control_step,
    radial_limit,
)
from oeal.models import MotorParameters, PMSMInput, PMSMState, state_derivative
from oeal.transforms import inverse_clarke, inverse_park, park


def decoupling_voltage(
    motor: MotorParameters, state: PMSMState
) -> tuple[float, float]:
    """Feedforward in V: -we*Lq*iq, we*(Ld*id+psi_f)."""
    values = state.as_array()
    if not np.all(np.isfinite(values)):
        raise ValueError("state must be finite")
    we = motor.pole_pairs * state.mechanical_speed_rad_s
    result = (
        -we * motor.q_inductance_h * state.iq_a,
        we * (motor.d_inductance_h * state.id_a + motor.flux_linkage_wb),
    )
    if not all(math.isfinite(value) for value in result):
        raise ValueError("feedforward overflow")
    return result


def average_svpwm(alpha_v: float, beta_v: float, vdc_v: float):
    """Return limited alpha/beta and centered abc duties; linear circular region."""
    if not math.isfinite(vdc_v) or vdc_v <= 0:
        raise ValueError("vdc_v must be finite and positive")
    alpha, beta = radial_limit(alpha_v, beta_v, vdc_v / math.sqrt(3.0))
    phases = inverse_clarke(alpha, beta)
    common = -(max(phases) + min(phases)) / 2.0
    duties = tuple(0.5 + (phase + common) / vdc_v for phase in phases)
    return alpha, beta, duties


@dataclass(frozen=True)
class FOCConfig:
    duration_s: float = 0.02
    control_period_s: float = 50e-6
    integration_step_s: float = 5e-6
    step_time_s: float = 0.001
    id_reference_a: float = 0.0
    iq_reference_a: float = 5.0
    vdc_v: float = 48.0
    current_limit_a: float = 10.0
    bandwidth_per_s: float = 2000.0
    tracking_rate_per_s: float = 2000.0
    delay_samples: int = 0

    def __post_init__(self):
        for name, value in vars(self).items():
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        for name in (
            "duration_s", "control_period_s", "integration_step_s", "vdc_v",
            "current_limit_a", "bandwidth_per_s", "tracking_rate_per_s",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if not 0 <= self.step_time_s < self.duration_s:
            raise ValueError("step_time_s must lie in [0, duration_s)")
        if type(self.delay_samples) is not int or self.delay_samples not in (0, 1):
            raise ValueError("delay_samples must be 0 or 1")
        if self.integration_step_s > self.control_period_s:
            raise ValueError("integration_step_s must not exceed control_period_s")
        for interval in (self.duration_s, self.step_time_s):
            ratio = interval / self.control_period_s
            if not math.isclose(ratio, round(ratio), rel_tol=0, abs_tol=1e-8):
                raise ValueError("duration and step time must align with control ticks")
        if self.duration_s / self.integration_step_s > 2_000_000:
            raise ValueError("simulation budget exceeded")


@dataclass(frozen=True)
class FOCTrace:
    # Columns: t, id, iq, wm, theta_m, vd_applied, vq_applied, duty_a/b/c,
    # id_ref, iq_ref, voltage_limited. Final row has no new command, repeats hold.
    samples: np.ndarray


def _advance_stationary(motor, state, alpha, beta, load, dt):
    def rhs(values):
        s = PMSMState.from_array(values)
        vd, vq = park(alpha, beta, motor.pole_pairs * s.mechanical_angle_rad)
        return state_derivative(s, PMSMInput(vd, vq, load), motor).as_array()

    x = state.as_array()
    k1 = rhs(x)
    k2 = rhs(x + 0.5 * dt * k1)
    k3 = rhs(x + 0.5 * dt * k2)
    k4 = rhs(x + dt * k3)
    result = x + dt / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)
    if not np.all(np.isfinite(result)):
        raise ValueError("nonfinite plant state; reduce step or inspect parameters")
    return PMSMState.from_array(result)


def simulate_foc(
    motor: MotorParameters, config: FOCConfig,
    initial_state: PMSMState | None = None, load_torque_nm: float = 0.0,
    controller_motor: MotorParameters | None = None,
) -> FOCTrace:
    """20 kHz by default; update once per tick, then hold alpha/beta through RK4."""
    if not math.isfinite(load_torque_nm):
        raise ValueError("load_torque_nm must be finite")
    state = initial_state or PMSMState()
    if not np.all(np.isfinite(state.as_array())):
        raise ValueError("initial_state must be finite")
    nominal = controller_motor or motor
    c = config
    p = CurrentPIParameters(
        nominal.d_inductance_h * c.bandwidth_per_s,
        nominal.stator_resistance_ohm * c.bandwidth_per_s,
        nominal.q_inductance_h * c.bandwidth_per_s,
        nominal.stator_resistance_ohm * c.bandwidth_per_s,
        c.vdc_v / math.sqrt(3), c.current_limit_a, c.tracking_rate_per_s,
    )
    pi = CurrentPIState()
    held = (0.0, 0.0, (0.5, 0.5, 0.5))
    rows = []
    ticks = round(c.duration_s / c.control_period_s)
    step_tick = round(c.step_time_s / c.control_period_s)
    for tick in range(ticks):
        id_ref = c.id_reference_a if tick >= step_tick else 0.0
        iq_ref = c.iq_reference_a if tick >= step_tick else 0.0
        fd, fq = decoupling_voltage(nominal, state)
        command = current_control_step(
            p, pi, reference_d_a=id_ref, reference_q_a=iq_ref,
            measured_d_a=state.id_a, measured_q_a=state.iq_a,
            period_s=c.control_period_s, feedforward_d_v=fd, feedforward_q_v=fq,
        )
        pi = command.next_state
        alpha, beta = inverse_park(
            command.vd_v, command.vq_v, motor.pole_pairs * state.mechanical_angle_rad
        )
        pending = average_svpwm(alpha, beta, c.vdc_v)
        applied = held if c.delay_samples else pending
        held = pending
        vd, vq = park(applied[0], applied[1], motor.pole_pairs * state.mechanical_angle_rad)
        rows.append([
            tick * c.control_period_s, *state.as_array(), vd, vq, *applied[2],
            command.reference_d_a, command.reference_q_a, float(command.voltage_limited),
        ])
        substeps = math.ceil(c.control_period_s / c.integration_step_s)
        dt = c.control_period_s / substeps
        for _ in range(substeps):
            state = _advance_stationary(
                motor, state, applied[0], applied[1], load_torque_nm, dt
            )
    final = list(rows[-1])
    final[:5] = [c.duration_s, *state.as_array()]
    rows.append(final)
    return FOCTrace(np.asarray(rows, dtype=float))
