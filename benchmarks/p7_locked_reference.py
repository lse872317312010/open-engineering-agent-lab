"""Bounded locked-rotor RL right-hand side and RK4 reference integration."""
import numpy as np


def rhs(state, voltage, resistance, inverse_inductance):
    current = np.asarray(state[:2], dtype=float)
    if not np.isfinite(state).all() or np.sum(abs(current)) > 2:
        raise ValueError("current left the declared local-model domain")
    derivative = inverse_inductance@(voltage-resistance*current)
    return np.array([*derivative, 1.5*voltage@current, 1.5*resistance*(current@current)])


def advance(state, voltage, resistance, inverse_inductance, dt):
    if not np.isfinite(dt) or dt <= 0:
        raise ValueError("positive finite integration step required")
    k1 = rhs(state, voltage, resistance, inverse_inductance)
    k2 = rhs(state+.5*dt*k1, voltage, resistance, inverse_inductance)
    k3 = rhs(state+.5*dt*k2, voltage, resistance, inverse_inductance)
    k4 = rhs(state+dt*k3, voltage, resistance, inverse_inductance)
    result = state+dt*(k1+2*k2+2*k3+k4)/6
    rhs(result, voltage, resistance, inverse_inductance)
    return result
