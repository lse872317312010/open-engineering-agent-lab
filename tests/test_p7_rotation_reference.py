"""Independent zero-field rotating-frame limit and rejection."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "rotation_ref", Path(__file__).resolve().parents[1] / "benchmarks/p7_rotation_reference.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)


def test_rotating_coordinates_constant_stationary_current():
    state = np.array([.5, 0., 0., 0., 0.])
    matrix = np.eye(2)*.002
    for i in range(100):
        state = ref.advance(i*1e-5, state, np.zeros(2), 100., .2, 0.,
                            matrix, np.zeros(2), 1e-5)
    np.testing.assert_allclose(state[:2], [.5*np.cos(.1), -.5*np.sin(.1)], atol=1e-12)
    assert state[:2]@matrix@state[:2] == pytest.approx(.0005, abs=1e-14)
    np.testing.assert_allclose(state[2:], 0., atol=1e-14)


def test_zero_speed_rl_and_domain():
    derivative = ref.rhs(0., np.zeros(5), np.array([.3, 0.]), 0., 0., .3,
                         np.eye(2)*.002, np.array([.06, 0.]))
    assert derivative[0] == pytest.approx(150.)
    with pytest.raises(ref.DomainViolation):
        ref.rhs(0., np.array([3., 0., 0., 0., 0.]), np.zeros(2), 100., 0., .3,
                np.eye(2)*.002, np.zeros(2))
