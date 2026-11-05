"""Bounded periodic dq flux with piecewise-linear angle dependence."""
import math

import numpy as np


class AngleFlux:
    def __init__(self, psi, inductance, resistance=.3):
        psi = np.asarray(psi, dtype=float)
        self.inductance = np.asarray(inductance, dtype=float).copy()
        if (psi.shape != (5, 2) or self.inductance.shape != (2, 2)
                or not np.isfinite(psi).all() or not np.isfinite(self.inductance).all()
                or not np.allclose(self.inductance, self.inductance.T, atol=1e-14, rtol=0)
                or np.min(np.linalg.eigvalsh(self.inductance)) <= 0):
            raise ValueError("five finite dq knots and a symmetric positive definite L required")
        if not math.isfinite(resistance) or resistance < 0:
            raise ValueError("finite nonnegative resistance required")
        self.resistance = float(resistance)
        self.closure_error = (psi[-1]-psi[0]).copy()
        self.psi = psi.copy()
        self.psi[-1] = self.psi[0]
        self.step = math.pi/16
        self.period = math.pi/4

    @staticmethod
    def current(i):
        i = np.asarray(i, dtype=float)
        if i.shape != (2,) or not np.isfinite(i).all() or np.sum(np.abs(i)) > 2:
            raise ValueError("current must be finite and satisfy abs(id)+abs(iq)<=2")
        return i

    def coefficients(self, theta, segment=None):
        if not math.isfinite(theta):
            raise ValueError("finite angle required")
        phase = theta % self.period
        k = int(phase/self.step) if segment is None else int(segment)
        if k not in range(4):
            raise ValueError("segment must be in 0..3")
        if segment is not None and k == 3 and phase < self.step/2:
            phase += self.period
        if segment is not None and k == 0 and phase > self.period-self.step/2:
            phase -= self.period
        slope = (self.psi[k+1]-self.psi[k])/self.step
        return self.psi[k]+slope*(phase-k*self.step), slope

    def flux(self, theta, i):
        i = self.current(i)
        psi, _ = self.coefficients(theta)
        return psi+self.inductance@i

    def rhs(self, theta, omega, voltage, i, segment=None):
        i = self.current(i)
        v = np.asarray(voltage, dtype=float)
        if v.shape != (2,) or not np.isfinite(v).all() or not math.isfinite(omega):
            raise ValueError("finite voltage and angular velocity required")
        psi, slope = self.coefficients(theta, segment)
        lam = psi+self.inductance@i
        jlam = np.array([-lam[1], lam[0]])
        return np.linalg.solve(self.inductance, v-self.resistance*i-omega*slope-4*omega*jlam)

    def power(self, theta, omega, voltage, i, segment=None):
        i = self.current(i)
        psi, slope = self.coefficients(theta, segment)
        lam = psi+self.inductance@i
        mechanical = 1.5*omega*(4*np.dot(i, [-lam[1], lam[0]])+np.dot(i, slope))
        return np.array([1.5*np.dot(voltage, i), 1.5*self.resistance*np.dot(i, i), mechanical])

    def stored(self, i):
        i = self.current(i)
        return float(.75*i@self.inductance@i)
