"""Independent cooling limits and unit traps, before MSL implementation."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from msl_cooling_reference import SIGMA, balance, flow_values, rhs  # noqa: E402


def test_radiation_uses_kelvin_fourth_power_and_retains_sign():
    t = np.full(6, 26.85)
    t[5] = 126.85
    q = flow_values(t, 26.85, .02, 1/3)
    assert abs(q[6]-100/3) < 1e-12
    assert abs(q[7]/(.02*SIGMA)-17_500_000_000) < 1e-5
    wrong = .02*SIGMA*(126.85**4-26.85**4)
    assert abs(q[7]-wrong) > 10.
    negative = flow_values(np.full(6, 26.85), 126.85, .02, 0.)
    assert negative[7] < 0 and negative[6] == 0.
    assert abs(negative[7]+q[7]) < 1e-12


def test_equilibrium_and_disabled_boundary_components():
    y = np.r_[np.full(6, 25.), np.zeros(4)]
    np.testing.assert_array_equal(rhs(0., y, [0.]*6, 25., .02, 1/3), np.zeros(10))
    assert balance(y, 25.) == 0.
    t = np.full(6, 60.)
    q = flow_values(t, 25., 0., 0.)
    assert q[6] == q[7] == 0.
    assert q[5] == 17.5


def test_nonlinear_total_power_identity_at_nonzero_temperatures():
    y = np.r_[[45.,39.,35.,42.,38.,31.], [50.,10.,20.,5.]]
    power = [40.,5.,0.,15.,0.,0.]
    f = rhs(0., y, power, 25., .02, .05)
    assert abs(np.dot([60.,70.,200.,.5,25.,100.], f[:6])+sum(f[7:])-f[6]) < 1e-12
    corrupted = y.copy()
    corrupted[9] = 0.
    assert abs(balance(corrupted, 25.)-balance(y, 25.)) == 5.
