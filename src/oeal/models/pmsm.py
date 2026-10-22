"""A deterministic average-voltage PMSM model in rotor dq coordinates."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class MotorParameters:
    """PMSM parameters in SI units."""

    stator_resistance_ohm: float
    d_inductance_h: float
    q_inductance_h: float
    flux_linkage_wb: float
    pole_pairs: int
    inertia_kg_m2: float
    viscous_friction_nms: float = 0.0

    def __post_init__(self) -> None:
        positive = {
            "stator_resistance_ohm": self.stator_resistance_ohm,
            "d_inductance_h": self.d_inductance_h,
            "q_inductance_h": self.q_inductance_h,
            "flux_linkage_wb": self.flux_linkage_wb,
            "inertia_kg_m2": self.inertia_kg_m2,
        }
        for name, value in positive.items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and greater than zero")
        if not isinstance(self.pole_pairs, int) or self.pole_pairs < 1:
            raise ValueError("pole_pairs must be a positive integer")
        if not math.isfinite(self.viscous_friction_nms) or self.viscous_friction_nms < 0:
            raise ValueError("viscous_friction_nms must be finite and non-negative")


@dataclass(frozen=True)
class PMSMState:
    """State variables; mechanical angle and speed are in rad and rad/s."""

    id_a: float = 0.0
    iq_a: float = 0.0
    mechanical_speed_rad_s: float = 0.0
    mechanical_angle_rad: float = 0.0

    def as_array(self) -> FloatArray:
        return np.asarray(
            [self.id_a, self.iq_a, self.mechanical_speed_rad_s, self.mechanical_angle_rad],
            dtype=np.float64,
        )

    @classmethod
    def from_array(cls, values: FloatArray) -> PMSMState:
        return cls(*(float(value) for value in values))


@dataclass(frozen=True)
class PMSMInput:
    """Average dq-axis stator voltage and opposing load torque."""

    vd_v: float = 0.0
    vq_v: float = 0.0
    load_torque_nm: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (
            ("vd_v", self.vd_v),
            ("vq_v", self.vq_v),
            ("load_torque_nm", self.load_torque_nm),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")


@dataclass(frozen=True)
class SimulationTrace:
    """Time history returned by :func:`simulate`. State columns follow PMSMState."""

    times_s: FloatArray
    states: FloatArray
    torque_nm: FloatArray


def electromagnetic_torque(state: PMSMState, parameters: MotorParameters) -> float:
    """Return electromagnetic torque using the amplitude-invariant dq convention."""

    return 1.5 * parameters.pole_pairs * (
        parameters.flux_linkage_wb * state.iq_a
        + (parameters.d_inductance_h - parameters.q_inductance_h) * state.id_a * state.iq_a
    )


def state_derivative(
    state: PMSMState, command: PMSMInput, parameters: MotorParameters
) -> PMSMState:
    """Evaluate the continuous-time PMSM and rigid-rotor equations."""

    omega_e = parameters.pole_pairs * state.mechanical_speed_rad_s
    did = (
        command.vd_v
        - parameters.stator_resistance_ohm * state.id_a
        + omega_e * parameters.q_inductance_h * state.iq_a
    ) / parameters.d_inductance_h
    diq = (
        command.vq_v
        - parameters.stator_resistance_ohm * state.iq_a
        - omega_e * (parameters.d_inductance_h * state.id_a + parameters.flux_linkage_wb)
    ) / parameters.q_inductance_h
    torque = electromagnetic_torque(state, parameters)
    acceleration = (
        torque
        - command.load_torque_nm
        - parameters.viscous_friction_nms * state.mechanical_speed_rad_s
    ) / parameters.inertia_kg_m2
    return PMSMState(did, diq, acceleration, state.mechanical_speed_rad_s)


def _derivative_vector(
    values: FloatArray, command: PMSMInput, parameters: MotorParameters
) -> FloatArray:
    return state_derivative(PMSMState.from_array(values), command, parameters).as_array()


def _rk4_step(
    values: FloatArray, dt: float, command: PMSMInput, parameters: MotorParameters
) -> FloatArray:
    k1 = _derivative_vector(values, command, parameters)
    k2 = _derivative_vector(values + 0.5 * dt * k1, command, parameters)
    k3 = _derivative_vector(values + 0.5 * dt * k2, command, parameters)
    k4 = _derivative_vector(values + dt * k3, command, parameters)
    return values + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def simulate(
    parameters: MotorParameters,
    command: PMSMInput,
    duration_s: float,
    step_s: float,
    initial_state: PMSMState | None = None,
) -> SimulationTrace:
    """Run a constant-input simulation and return samples including both endpoints."""

    if not math.isfinite(duration_s) or duration_s <= 0:
        raise ValueError("duration_s must be finite and greater than zero")
    if not math.isfinite(step_s) or step_s <= 0:
        raise ValueError("step_s must be finite and greater than zero")

    state = (initial_state or PMSMState()).as_array()
    if not np.all(np.isfinite(state)):
        raise ValueError("initial_state values must be finite")

    ratio = duration_s / step_s
    nearest_integer = round(ratio)
    if math.isclose(ratio, nearest_integer, rel_tol=1e-12, abs_tol=0.0):
        count = int(nearest_integer)
    else:
        count = math.ceil(ratio)
    times = np.empty(count + 1, dtype=np.float64)
    states = np.empty((count + 1, 4), dtype=np.float64)
    times[0] = 0.0
    states[0] = state
    for index in range(1, count + 1):
        previous_time = times[index - 1]
        dt = min(step_s, duration_s - previous_time)
        state = _rk4_step(state, dt, command, parameters)
        times[index] = duration_s if index == count else index * step_s
        states[index] = state

    torques = np.asarray(
        [electromagnetic_torque(PMSMState.from_array(row), parameters) for row in states],
        dtype=np.float64,
    )
    return SimulationTrace(times, states, torques)

