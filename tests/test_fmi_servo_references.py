"""Preimplementation hand references for saliency, parameter energy and position PD."""

import runpy
from pathlib import Path

import numpy as np

R = runpy.run_path(str(Path(__file__).parents[1] / "benchmarks/fmi_servo_reference.py"))


def test_configurable_joint_salient_hand_point_and_power():
    p = R["defaults"]() | dict(d_inductance_h=.001, q_inductance_h=.0006)
    x = np.array([1., 2., .1, 3., .002, -.4, 35., 28., 30., 0., 0., 0.])
    p0 = p | dict(stator_resistance_ohm=.3/(1+.00393*10))
    dy = R["rhs"](0, x, [1., 2., .3, 20.], p0)
    assert abs(dy[0]-725.2) < 1e-10
    assert abs(dy[1]-1248.3333333333333) < 1e-10
    delta = x[2]/10-x[4]
    gradient = np.array([1.5*p0["d_inductance_h"]*x[0],
                         1.5*p0["q_inductance_h"]*x[1], 8*delta,
                         p0["inertia_kg_m2"]*x[3], -80*delta, .02*x[5], 60, 200, 25])
    assert abs(gradient @ dy[:9]-dy[9]+dy[10]+dy[11]) < 1e-12
    te = dy[3]*p0["inertia_kg_m2"]+(80*delta+.15*(x[3]/10-x[5]))/10+1e-5*x[3]
    assert abs(te-.6384) < 1e-12


def test_position_velocity_and_outer_pd_first_step():
    s = dict(position_start_s=.01, position_ramp_s=.1, position_step_rad=.02,
             outer_kp_nm_per_rad=60., outer_kd_nms_per_rad=3.,
             control_period_s=50e-6, current_limit_a=3., bandwidth_per_s=1000.,
             tracking_rate_per_s=1000., vdc_v=48., delay_samples=0)
    assert R["reference"](0, s) == (0., 0.)
    np.testing.assert_allclose(R["reference"](.06, s), [.01, .2], atol=1e-15)
    np.testing.assert_allclose(R["reference"](.12, s), [.02, 0.], atol=1e-15)
    x = np.array([0.]*6+[25.]*3+[0.]*3)
    u, integral, _ = R["command"](s, x, 200, [0., 0.], [0., 0.])
    np.testing.assert_allclose(u, [0., .815*(.6/3.15)], atol=1e-15)
    np.testing.assert_allclose(integral, [0., .015*(.6/3.15)], atol=1e-15)
