"""Independent RC parameter equations and matrix exponential, frozen before implementation."""
import numpy as np
from scipy.linalg import expm

CAPACITY = np.array([60.,70.,200.,.5,25.,100.])
RESISTANCE = np.array([.6,.4,2.,.8,1.2])
EDGES = [(0,1),(1,2),(2,4),(3,4),(4,5)]
SIGMA = 5.6703744191844314e-8


def rates(temperatures, heat, gc, area, ambient, capacities, resistances, case_r):
    t = np.atleast_2d(temperatures)
    net = np.atleast_2d(heat).copy()
    for (a, b), r in zip(EDGES, resistances, strict=True):
        q = (t[:, a]-t[:, b])/r
        net[:, a] -= q
        net[:, b] += q
    branch = np.column_stack([(t[:, 2]-ambient)/case_r,
                              np.asarray(gc)*(t[:, 5]-ambient),
                              area*SIGMA*((t[:, 5]+273.15)**4-(ambient+273.15)**4)])
    net[:, 2] -= branch[:, 0]
    net[:, 5] -= branch[:, 1]+branch[:, 2]
    return np.column_stack([net/np.asarray(capacities), np.atleast_2d(heat).sum(axis=1),
                            branch.sum(axis=1), branch])


def linear_solution(t, initial, ambient, capacities, resistances, case_r, gc=1/3):
    # Exact zero-input, zero-radiation temperatures and three branch integrals.
    c = np.asarray(capacities)
    matrix = np.zeros((9, 9))
    for (a, b), r in zip(EDGES, resistances, strict=True):
        matrix[a, a] -= 1/(r*c[a])
        matrix[a, b] += 1/(r*c[a])
        matrix[b, b] -= 1/(r*c[b])
        matrix[b, a] += 1/(r*c[b])
    matrix[2, 2] -= 1/(case_r*c[2])
    matrix[5, 5] -= gc/c[5]
    matrix[6, 2] = 1/case_r
    matrix[7, 5] = gc
    state = expm(matrix*t) @ np.r_[np.asarray(initial)-ambient, np.zeros(3)]
    return np.r_[state[:6]+ambient, 0., state[6:]]
