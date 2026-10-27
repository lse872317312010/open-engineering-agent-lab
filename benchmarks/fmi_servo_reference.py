"""Independent configurable joint and position/current host equations."""

import math

import numpy as np


def defaults():
    return dict(stator_resistance_ohm=.3, d_inductance_h=.0008, q_inductance_h=.0008,
                flux_linkage_wb=.03, pole_pairs=7, inertia_kg_m2=5e-5,
                viscous_friction_nms=1e-5)


def rhs(_t, y, u, p):
    d, q, tm, wm, tl, wl, tw, tc, tb = y[:9]
    vd, vq, load, board = u
    resistance = p["stator_resistance_ohm"]*(1+.00393*(tw-25))
    ld, lq, psi = p["d_inductance_h"], p["q_inductance_h"], p["flux_linkage_wb"]
    speed = p["pole_pairs"]*wm
    strain, rate = tm/10-tl, wm/10-wl
    shaft = 80*strain+.15*rate
    te = 1.5*p["pole_pairs"]*(psi*q+(ld-lq)*d*q)
    copper = 1.5*resistance*(d*d+q*q)
    friction = p["viscous_friction_nms"]*wm*wm+.02*wl*wl+.15*rate*rate
    wc, bc, ca, ba = (tw-tc)/.8, (tb-tc)/1.2, (tc-25)/2, (tb-25)/4
    return np.array([
        (vd-resistance*d+speed*lq*q)/ld,
        (vq-resistance*q-speed*(ld*d+psi))/lq,
        wm, (te-shaft/10-p["viscous_friction_nms"]*wm)/p["inertia_kg_m2"],
        wl, (shaft-load-.02*wl)/.02,
        (copper-wc)/60, (wc+bc+friction-ca)/200, (board-bc-ba)/25,
        1.5*(vd*d+vq*q)+board, load*wl, ca+ba,
    ])


def stored(y, p):
    x = np.asarray(y)
    return (.75*(p["d_inductance_h"]*x[..., 0]**2+p["q_inductance_h"]*x[..., 1]**2)
            + .5*p["inertia_kg_m2"]*x[..., 3]**2+.01*x[..., 5]**2
            + 40*(x[..., 2]/10-x[..., 4])**2
            + 60*(x[..., 6]-25)+200*(x[..., 7]-25)+25*(x[..., 8]-25))


def reference(t, s):
    elapsed = t-s["position_start_s"]
    q = s["position_step_rad"]*max(0., min(1., elapsed/s["position_ramp_s"]))
    velocity = (s["position_step_rad"]/s["position_ramp_s"]
                if s["position_start_s"] <= t < s["position_start_s"]+s["position_ramp_s"] else 0.)
    return q, velocity


def command(s, x, tick, integral, previous):
    period = s["control_period_s"]
    qref, vref = reference(tick*period, s)
    effort = s["outer_kp_nm_per_rad"]*(qref-x[4])+s["outer_kd_nms_per_rad"]*(vref-x[5])
    rd, rq = 0., effort/(10*1.5*7*.03)
    length = math.hypot(rd, rq)
    if length > s["current_limit_a"]:
        rd, rq = rd*s["current_limit_a"]/length, rq*s["current_limit_a"]/length
    zd = integral[0]+.3*s["bandwidth_per_s"]*period*(rd-x[0])
    zq = integral[1]+.3*s["bandwidth_per_s"]*period*(rq-x[1])
    raw = np.array([.0008*s["bandwidth_per_s"]*(rd-x[0])+zd-7*x[3]*.0008*x[1],
                    .0008*s["bandwidth_per_s"]*(rq-x[1])+zq+7*x[3]*(.0008*x[0]+.03)])
    norm = float(np.linalg.norm(raw))
    limit = s["vdc_v"]/math.sqrt(3)
    pending = raw*limit/norm if norm > limit else raw
    new_integral = np.array([zd, zq])+(1-math.exp(-s["tracking_rate_per_s"]*period))*(pending-raw)
    applied = np.array(previous) if s["delay_samples"] else pending
    return applied, new_integral, pending
