"""Analytic prescribed-motion clock, phase and derivative checks."""
import importlib
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def ramp(monkeypatch):
    for package in ("scipy", "gmsh", "meshio", "skfem", "matplotlib"):
        pytest.importorskip(package)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "benchmarks"))
    return importlib.import_module("p7_speed_ramp")


def test_motion_has_continuous_phase_and_exact_scoring_travel(ramp):
    theta, omega = ramp.motion(np.array([0., .2, .4, .6]), 1.)
    np.testing.assert_allclose(omega/ramp.OMEGA, [.5, .5, 2., .5], atol=1e-14)
    assert theta[0] == .23
    assert theta[-1]-theta[1] == pytest.approx(25*np.pi/4, abs=1e-14)
    reversed_theta, reversed_omega = ramp.motion(np.array([0., .2, .4, .6]), -1.)
    np.testing.assert_allclose(reversed_theta-.23, -(theta-.23), atol=1e-14)
    np.testing.assert_allclose(reversed_omega, -omega, atol=1e-14)


def test_speed_is_derivative_of_prescribed_angle(ramp):
    for at in (.1, .3, .5):
        theta, _ = ramp.motion(np.array([at-1e-6, at+1e-6]), 1.)
        _, omega = ramp.motion(at, 1.)
        assert (theta[1]-theta[0])/2e-6 == pytest.approx(float(omega), abs=1e-7)
