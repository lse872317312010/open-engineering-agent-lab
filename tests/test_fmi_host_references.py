"""Independent sampled host limits committed before implementing its adapter."""

import runpy
from pathlib import Path

import numpy as np

REFERENCE = runpy.run_path(str(Path(__file__).parents[1] / "benchmarks/fmi_host_reference.py"))


def settings(delay=0, voltage=48.):
    return dict(control_period_s=50e-6, step_time_s=0., id_reference_a=0.,
                iq_reference_a=1., current_limit_a=15., bandwidth_per_s=1000.,
                tracking_rate_per_s=1000., vdc_v=voltage, delay_samples=delay)


def test_fmi_host_hand_computed_first_pi_step_and_delay():
    x = np.array([0.]*6+[25.]*3)
    u, integral, pending, refs = REFERENCE["command"](settings(), x, 0, [0., 0.], [0., 0.])
    np.testing.assert_allclose(u, [0., .815], atol=1e-15)
    np.testing.assert_allclose(integral, [0., .015], atol=1e-15)
    assert refs == (0., 1.)
    delayed, _, _, _ = REFERENCE["command"](settings(1), x, 0, [0., 0.], [0., 0.])
    np.testing.assert_array_equal(delayed, [0., 0.])
    np.testing.assert_allclose(pending, [0., .815], atol=1e-15)


def test_fmi_host_radial_saturation_and_tracking_arithmetic():
    x = np.array([0.]*6+[25.]*3)
    s = settings(voltage=1.)
    u, integral, _, _ = REFERENCE["command"](s, x, 0, [0., 0.], [0., 0.])
    assert abs(np.linalg.norm(u)-1/np.sqrt(3)) < 1e-15
    expected = .015+(1-np.exp(-.05))*(1/np.sqrt(3)-.815)
    assert abs(integral[1]-expected) < 1e-15


def test_fmi_host_storage_independent_hand_point():
    x = np.array([1., 2., .1, 3., .002, -.4, 35., 28., 30.])
    expected = .003+.000225+.0016+.00256+600+600+125
    assert abs(REFERENCE["stored"](x)-expected) < 1e-12
