"""Experimental local reciprocal affine flux model with a bounded current input."""
import numpy as np


class LocalFluxModel:
    def __init__(self, psi, inductance):
        self.psi = np.array(psi, dtype=float, copy=True)
        self.inductance = np.array(inductance, dtype=float, copy=True)
        if (self.psi.shape != (2,) or self.inductance.shape != (2, 2)
                or not np.isfinite(self.psi).all() or not np.isfinite(self.inductance).all()
                or not np.allclose(self.inductance, self.inductance.T, atol=1e-14, rtol=0)
                or np.min(np.linalg.eigvalsh(self.inductance)) <= 0):
            raise ValueError("finite psi and symmetric positive definite inductance required")
        self.psi.flags.writeable = False
        self.inductance.flags.writeable = False

    def _current(self, current):
        value = np.asarray(current, dtype=float)
        if value.shape != (2,) or not np.isfinite(value).all() or np.sum(abs(value)) > 2:
            raise ValueError("current must be finite and satisfy abs(id)+abs(iq)<=2 A")
        return value

    def flux(self, current):
        value = self._current(current)
        return self.psi+self.inductance@value

    def coenergy_increment(self, current):
        value = self._current(current)
        return float(self.psi@value+.5*value@self.inductance@value)
