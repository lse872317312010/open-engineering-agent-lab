"""Independent loss routing and resistance checks frozen before coupling code."""

import numpy as np

from msl_thermal_reference import CAPACITY, EDGES


def resistance(winding_c, enabled=True):
    return .3*(1+.00393*(np.asarray(winding_c)-25)) if enabled else np.asarray(winding_c)*0+.3


def route_heat(copper, friction, conduction, auxiliary):
    return np.array([copper, 0., friction, conduction+auxiliary, 0., 0.])


def independent_rates(temperatures, heat):
    t = np.atleast_2d(temperatures)
    net = np.atleast_2d(heat).copy()
    for a, b, r in EDGES:
        q = (t[:, a]-t[:, b])/r
        net[:, a] -= q
        net[:, b] += q
    ambient = (t[:, 2]-25)/2+(t[:, 5]-25)/3
    net[:, 2] -= (t[:, 2]-25)/2
    net[:, 5] -= (t[:, 5]-25)/3
    return np.column_stack([net/CAPACITY, np.atleast_2d(heat).sum(axis=1), ambient])
