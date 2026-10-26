"""Independent sampled PI arithmetic and energy identity for the FMI host."""

import math

import numpy as np


def command(settings, x, tick, integral, previous):
    period = settings["control_period_s"]
    active = tick >= round(settings["step_time_s"]/period)
    rd = settings["id_reference_a"] if active else 0.
    rq = settings["iq_reference_a"] if active else 0.
    length = math.hypot(rd, rq)
    limit = settings["current_limit_a"]
    if length > limit:
        rd, rq = rd*limit/length, rq*limit/length
    zd = integral[0]+.3*settings["bandwidth_per_s"]*period*(rd-x[0])
    zq = integral[1]+.3*settings["bandwidth_per_s"]*period*(rq-x[1])
    raw = np.array([
        .0008*settings["bandwidth_per_s"]*(rd-x[0])+zd-7*x[3]*.0008*x[1],
        .0008*settings["bandwidth_per_s"]*(rq-x[1])+zq+7*x[3]*(.0008*x[0]+.03),
    ])
    magnitude = float(np.linalg.norm(raw))
    voltage_limit = settings["vdc_v"]/math.sqrt(3)
    pending = raw*(voltage_limit/magnitude) if magnitude > voltage_limit else raw
    beta = 1-math.exp(-settings["tracking_rate_per_s"]*period)
    next_integral = np.array([zd, zq])+beta*(pending-raw)
    applied = np.array(previous) if settings["delay_samples"] else pending
    return applied, next_integral, pending, (rd, rq)


def stored(y):
    x = np.asarray(y)
    return (.0006*(x[..., 0]**2+x[..., 1]**2)
            + .000025*x[..., 3]**2+.01*x[..., 5]**2
            + 40*(x[..., 2]/10-x[..., 4])**2
            + 60*(x[..., 6]-25)+200*(x[..., 7]-25)+25*(x[..., 8]-25))
