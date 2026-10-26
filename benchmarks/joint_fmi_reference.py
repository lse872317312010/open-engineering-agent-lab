"""Independent SI equations for the frozen nine-state joint FMI contract."""

import numpy as np


def initial():
    return np.array([0., 0., 0., 0., 0., 0., 25., 25., 25., 0., 0., 0.])


def rhs(_t, y, u):
    d, q, tm, wm, tl, wl, tw, tc, tb = y[:9]
    vd, vq, load, board = u
    resistance = .3 * (1 + .00393 * (tw - 25))
    speed = 7 * wm
    strain, rate = tm / 10 - tl, wm / 10 - wl
    shaft = 80 * strain + .15 * rate
    copper = 1.5 * resistance * (d*d + q*q)
    friction = 1e-5 * wm*wm + .02 * wl*wl + .15 * rate*rate
    wc, bc, ca, ba = (tw-tc)/.8, (tb-tc)/1.2, (tc-25)/2, (tb-25)/4
    return np.array([
        (vd-resistance*d+speed*.0008*q)/.0008,
        (vq-resistance*q-speed*(.0008*d+.03))/.0008,
        wm, (.315*q-shaft/10-1e-5*wm)/5e-5,
        wl, (shaft-load-.02*wl)/.02,
        (copper-wc)/60, (wc+bc+friction-ca)/200, (board-bc-ba)/25,
        1.5*(vd*d+vq*q)+board, load*wl, ca+ba,
    ])


def stored(y):
    d, q, tm, wm, tl, wl, tw, tc, tb = np.asarray(y)[..., :9].T
    return (.75*.0008*(d*d+q*q) + .5*5e-5*wm*wm + .5*.02*wl*wl
            + 40*(tm/10-tl)**2 + 60*(tw-25)+200*(tc-25)+25*(tb-25))


def balance(y):
    y = np.asarray(y)
    return stored(y) - y[..., 9] + y[..., 10] + y[..., 11]


def schedule(name):
    steps = []
    t = 0.
    tick = 0
    while t < .08 - 1e-13:
        h = ([25e-6, 75e-6][tick % 2] if name == "variable-clock" else 50e-6)
        h = min(h, .08-t)
        if name == "no-load":
            u = (0., 2. if t < .04-1e-12 else 0., 0., 0.)
        elif name == "loaded-heating":
            u = (.2, 3., .3 if t >= .02-1e-12 else 0., 20.)
        elif name == "reversal":
            u = (0., 2. if t < .04-1e-12 else -2., -.1, 5.)
        elif name == "variable-clock":
            u = (.1, 1.5 if t < .04-1e-12 else -.5, .1, 10.)
        else:
            raise ValueError(name)
        steps.append((t, h, u))
        t += h
        tick += 1
    return steps
