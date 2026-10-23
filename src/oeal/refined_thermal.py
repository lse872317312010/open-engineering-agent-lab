"""Six-node SI thermal network with reciprocal conductances and explicit power ports."""

import numpy as np

NAMES = ("winding", "core", "case", "junction", "board", "sink")
CAPACITIES = np.array([60.0, 70.0, 200.0, 0.5, 25.0, 100.0])
LINKS = ((0, 1, 0.6), (1, 2, 0.4), (2, 4, 2.0), (3, 4, 0.8), (4, 5, 1.2))
AMBIENT_LINKS = ((2, 2.0), (5, 3.0))


class ThermalNetwork:
    """Research RC parameters, not a calibrated package or motor thermal model."""

    def __init__(self, period_s=0.001, ambient_c=25.0):
        if not np.isfinite(period_s) or period_s <= 0 or not np.isfinite(ambient_c):
            raise ValueError("finite positive period and finite ambient required")
        from scipy.linalg import expm

        self.period_s = period_s
        self.ambient_c = ambient_c
        self.temperatures = np.full(6, ambient_c)
        conductance = np.zeros((6, 6))
        for a, b, resistance in LINKS:
            g = 1 / resistance
            conductance[a, a] += g
            conductance[b, b] += g
            conductance[a, b] -= g
            conductance[b, a] -= g
        for node, resistance in AMBIENT_LINKS:
            conductance[node, node] += 1 / resistance
        self.conductance = conductance
        self.matrix = -conductance / CAPACITIES[:, None]
        self.transition = expm(self.matrix * period_s)
        self.power_transition = np.linalg.solve(
            self.matrix, self.transition - np.eye(6)
        ) / CAPACITIES[None, :]

    def advance(self, powers_w):
        powers = np.asarray(powers_w, dtype=float)
        if powers.shape != (6,) or not np.all(np.isfinite(powers)):
            raise ValueError("six finite heat-source powers required")
        relative = self.temperatures - self.ambient_c
        self.temperatures = (
            self.ambient_c + self.transition @ relative + self.power_transition @ powers
        )
        return self.temperatures.copy()

    def rates(self, temperatures, powers_w):
        relative = np.asarray(temperatures) - self.ambient_c
        return self.matrix @ relative + np.asarray(powers_w) / CAPACITIES

    def balance_error_w(self, temperatures, powers_w):
        ambient = sum(
            (temperatures[node] - self.ambient_c) / resistance
            for node, resistance in AMBIENT_LINKS
        )
        return float(CAPACITIES @ self.rates(temperatures, powers_w)
                     - (sum(powers_w) - ambient))
