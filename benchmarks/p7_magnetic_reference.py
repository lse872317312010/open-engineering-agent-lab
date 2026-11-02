"""Independent SI analytic reference for a bounded two-region return-current pair."""
import numpy as np

MU0 = 4e-7*np.pi
LENGTH, SPLIT, HEIGHT, DEPTH = .1, .04, .1, .01
CASES = [
    dict(id="air", current_a=2., mu_left=MU0, mu_right=MU0),
    dict(id="contrast", current_a=2., mu_left=MU0, mu_right=5*MU0),
    dict(id="reverse", current_a=-2., mu_left=MU0, mu_right=5*MU0),
    dict(id="double", current_a=4., mu_left=MU0, mu_right=5*MU0),
]


def exact(x, case):
    """Return Az [Wb/m], Bx/By [T] and tangential Hy [A/m]."""
    x = np.asarray(x)
    left = x <= SPLIT
    width = np.where(left, SPLIT, LENGTH-SPLIT)
    local = np.where(left, x, x-SPLIT)
    sign = np.where(left, 1., -1.)
    mu = np.where(left, case["mu_left"], case["mu_right"])
    density = sign*case["current_a"]/(width*HEIGHT)
    az = mu*density*local*(width-local)/2
    derivative = mu*density*(width-2*local)/2
    by = -derivative
    return az, np.zeros_like(az), by, by/mu


def inductance(case):
    """Exact finite-domain single-turn circuit L, not PMSM d/q inductance."""
    return DEPTH*(case["mu_left"]*SPLIT
                  +case["mu_right"]*(LENGTH-SPLIT))/(12*HEIGHT)


def norms(case):
    i = case["current_a"]
    widths = np.array([SPLIT, LENGTH-SPLIT])
    mus = np.array([case["mu_left"], case["mu_right"]])
    a2 = np.sum(mus**2*i**2*widths**3/(120*HEIGHT))
    b2 = np.sum(mus**2*i**2*widths/(12*HEIGHT))
    return np.sqrt(a2), np.sqrt(b2)
