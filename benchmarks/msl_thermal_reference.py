"""Independent physical port equations, frozen before MSL implementation."""

import numpy as np

CAPACITY = np.array([60., 70., 200., .5, 25., 100.])
EDGES = ((0, 1, .6), (1, 2, .4), (2, 4, 2.), (3, 4, .8), (4, 5, 1.2))
BLOCKS = ((600, (40, 5, 0, 15, 0, 0)), (1200, (10, 2, 0, 3, 0, 0)),
          (600, (60, 8, 0, 20, 0, 0)), (1200, (0, 0, 0, 0, 0, 0)))


def flows(temperatures, ambient):
    t = np.asarray(temperatures)
    return np.array([(t[a]-t[b])/r for a, b, r in EDGES]
                    + [(t[2]-ambient)/2+(t[5]-ambient)/3])


def rhs(_time, y, powers, ambient):
    heat = np.array(powers, dtype=float)
    q = flows(y[:6], ambient)
    for (a, b, _), rate in zip(EDGES, q[:5], strict=True):
        heat[a] -= rate
        heat[b] += rate
    heat[2] -= (y[2]-ambient)/2
    heat[5] -= (y[5]-ambient)/3
    return np.r_[heat/CAPACITY, sum(powers), q[5]]


def balance(values, ambient):
    y = np.asarray(values)
    return (y[..., :6]-ambient) @ CAPACITY - y[..., 6]+y[..., 7]
