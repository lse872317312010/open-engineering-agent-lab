"""Full-matrix rotating dq dynamics under stationary voltage hold."""
import math

import numpy as np

J = np.array([[0., -1.], [1., 0.]])


class DomainViolation(ValueError):
    def __init__(self, time_s, current):
        super().__init__("current left declared abs(id)+abs(iq)<=2 A domain")
        self.time_s = float(time_s)
        self.current = np.asarray(current).tolist()


def rhs(time_s, state, stationary_voltage, omega_e, offset, resistance, matrix, psi):
    current = state[:2]
    if not np.isfinite(state).all() or np.sum(abs(current)) > 2:
        raise DomainViolation(time_s, current)
    angle = omega_e*time_s+offset
    cosine, sine = math.cos(angle), math.sin(angle)
    alpha, beta = stationary_voltage
    voltage = np.array([alpha*cosine+beta*sine, -alpha*sine+beta*cosine])
    flux = psi+matrix@current
    rotation = omega_e*J@flux
    derivative = np.linalg.solve(matrix, voltage-resistance*current-rotation)
    return np.array([*derivative, 1.5*voltage@current,
                     1.5*resistance*(current@current), 1.5*current@rotation])


def advance(time_s, state, voltage, omega_e, offset, resistance, matrix, psi, dt):
    args = (voltage, omega_e, offset, resistance, matrix, psi)
    k1 = rhs(time_s, state, *args)
    k2 = rhs(time_s+dt/2, state+dt*k1/2, *args)
    k3 = rhs(time_s+dt/2, state+dt*k2/2, *args)
    k4 = rhs(time_s+dt, state+dt*k3, *args)
    result = state+dt*(k1+2*k2+2*k3+k4)/6
    rhs(time_s+dt, result, *args)
    return result
