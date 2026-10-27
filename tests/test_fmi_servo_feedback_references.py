"""Independent ideal-current two-inertia criterion before feedback revision B."""

import runpy
from pathlib import Path

import numpy as np

R = runpy.run_path(str(Path(__file__).parents[1] / "benchmarks/fmi_servo_reference.py"))


def test_load_velocity_feedback_fails_reduced_hurwitz_condition():
    a4, a3, a2, a1, a0 = .0001, .00375, 2.45, 249., 4800.
    assert abs(a3*a2-a4*a1-(-.0157125)) < 1e-12
    assert a3*a2*a1-a4*a1*a1-a3*a3*a0 < 0


def test_motor_velocity_feedback_passes_reduced_hurwitz_condition():
    a4, a3, a2, a1, a0 = .0001, .06375, 2.45, 249., 4800.
    assert abs(a3*a2-a4*a1-.1312875) < 1e-12
    assert abs(a3*a2*a1-a4*a1*a1-a3*a3*a0-13.1830875) < 1e-10


def test_motor_side_derivative_reference_with_distinct_load_speed():
    s = dict(position_start_s=.01, position_ramp_s=.1, position_step_rad=.02,
             outer_kp_nm_per_rad=60., outer_kd_nms_per_rad=3.,
             control_period_s=50e-6, current_limit_a=3., bandwidth_per_s=1000.,
             tracking_rate_per_s=1000., vdc_v=48., delay_samples=0)
    x = np.array([0., 0., 0., 10., 0., 0., 25., 25., 25., 0., 0., 0.])
    u, _, _ = R["command"](s, x, 200, [0., 0.], [0., 0.])
    np.testing.assert_allclose(u, [0., .815*(-2.4/3.15)+2.1], atol=1e-14)
