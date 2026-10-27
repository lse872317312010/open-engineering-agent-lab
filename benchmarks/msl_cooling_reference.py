"""Independent nonlinear cooling port equations frozen before MSL wiring."""

import math

import numpy as np
from msl_thermal_reference import BLOCKS, CAPACITY, EDGES

SIGMA = 2*math.pi**5*(1.380649e-23)**4/(15*(6.62607015e-34)**3*299792458**2)
CASES = [
    dict(id="linear-limit", ambient_c=25., area_m2=0., period_s=1., fan=False),
    dict(id="radiation", ambient_c=25., area_m2=.02, period_s=1., fan=False),
    dict(id="radiation-fine", ambient_c=25., area_m2=.02, period_s=.5, fan=False),
    dict(id="fan-loss-recovery", ambient_c=25., area_m2=.02, period_s=1., fan=True),
    dict(id="hot-ambient", ambient_c=60., area_m2=.02, period_s=1., fan=False),
    dict(id="cold-ambient", ambient_c=-10., area_m2=.02, period_s=1., fan=False),
]


def conductance(t, case):
    if not case["fan"] or t < 1200.:
        return 1/3
    return .05 if t < 2400. else 1.


def powers(t):
    elapsed = 0.
    for duration, value in BLOCKS:
        if t < elapsed+duration:
            return value
        elapsed += duration
    return BLOCKS[-1][1]


def flow_values(temperatures_c, ambient_c, area_m2, gc):
    t = np.asarray(temperatures_c)
    internal = [(t[a]-t[b])/r for a, b, r in EDGES]
    case = (t[2]-ambient_c)/2
    convection = gc*(t[5]-ambient_c)
    radiation = area_m2*SIGMA*((t[5]+273.15)**4-(ambient_c+273.15)**4)
    return np.array([*internal, case, convection, radiation])


def rhs(_t, state, power, ambient, area, gc):
    q = flow_values(state[:6], ambient, area, gc)
    heat = np.asarray(power, dtype=float).copy()
    for (a, b, _), value in zip(EDGES, q[:5], strict=True):
        heat[a] -= value
        heat[b] += value
    heat[2] -= q[5]
    heat[5] -= q[6]+q[7]
    return np.r_[heat/CAPACITY, sum(power), q[5:]]


def balance(state, ambient):
    a = np.asarray(state)
    return (a[..., :6]-ambient) @ CAPACITY-a[..., 6]+a[..., 7:10].sum(axis=-1)


def segments():
    return list(zip([0.,600.,1200.,1800.,2400.], [600.,1200.,1800.,2400.,3600.],
                    strict=True))
