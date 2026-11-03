"""Independent bounded permanent-magnet cylinder reference and peak dq conventions."""
import numpy as np

MU0 = 4e-7*np.pi


def magnet_field(x, y, radius_m=.02, outer_m=.04, br_t=1.2):
    """Uniform +x remanence, mur=1 everywhere, Az=0 circular finite boundary."""
    x, y = np.asarray(x), np.asarray(y)
    r2 = x*x+y*y
    inside = r2 < radius_m**2
    safe = np.maximum(r2, 1e-30)
    c = br_t*radius_m**2/2
    a_inside = br_t/2*(1-radius_m**2/outer_m**2)
    az = np.where(inside, a_inside*y, c*(1/safe-1/outer_m**2)*y)
    bx = np.where(inside, a_inside, c*(1/safe-2*y*y/safe**2-1/outer_m**2))
    by = np.where(inside, 0., 2*c*x*y/safe**2)
    return az, bx, by


def abc_from_dq(id_a, iq_a, angle_rad):
    alpha = id_a*np.cos(angle_rad)-iq_a*np.sin(angle_rad)
    beta = id_a*np.sin(angle_rad)+iq_a*np.cos(angle_rad)
    return np.array([alpha, -.5*alpha+np.sqrt(3)/2*beta,
                     -.5*alpha-np.sqrt(3)/2*beta])


def dq_from_abc(abc, angle_rad):
    a, b, c = np.asarray(abc)
    alpha, beta = (2*a-b-c)/3, (b-c)/np.sqrt(3)
    return np.array([alpha*np.cos(angle_rad)+beta*np.sin(angle_rad),
                     -alpha*np.sin(angle_rad)+beta*np.cos(angle_rad)])


def maxwell_torque(phi, bx, by, radius_m, depth_m=.04):
    """Total-field circular Maxwell stress, uniform angular nodes, SI."""
    br = bx*np.cos(phi)+by*np.sin(phi)
    bt = -bx*np.sin(phi)+by*np.cos(phi)
    return float(depth_m*radius_m**2/MU0*2*np.pi*np.mean(br*bt))
