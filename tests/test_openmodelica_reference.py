"""Independent pre-implementation checks for Modelica exchange physics."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from joint_fmi_reference import initial, rhs, schedule, stored  # noqa: E402


def test_unforced_equilibrium_and_two_analytic_initial_slopes():
    y = initial()
    np.testing.assert_array_equal(rhs(0., y, (0., 0., 0., 0.)), np.zeros(12))
    f = rhs(0., y, (1., 0., 0., 25.))
    assert f[0] == 1250.
    assert f[8] == 1.
    assert f[9] == 25.


def test_independent_total_power_identity_at_nonzero_state():
    y = np.array([.4, -.7, .2, 3., -.03, -.4, 45., 32., 36., 0., 0., 0.])
    u = (.8, -1.2, -.3, 20.)
    f = rhs(0., y, u)
    gradient = np.array([
        .0012*y[0], .0012*y[1], 8*(y[2]/10-y[4]), 5e-5*y[3],
        -80*(y[2]/10-y[4]), .02*y[5], 60., 200., 25.,
    ])
    assert abs(gradient @ f[:9] - (f[9]-f[10]-f[11])) < 1e-12
    assert stored(initial()) == 0.


def test_frozen_four_exchange_clocks_cover_real_discontinuities():
    for name in ("no-load", "loaded-heating", "reversal", "variable-clock"):
        windows = schedule(name)
        assert len(windows) == 1600
        assert abs(windows[-1][0]+windows[-1][1]-.08) < 1e-13
        assert all(h > 0 for _, h, _ in windows)
        for left, right in zip(windows, windows[1:]):
            assert abs(left[0]+left[1]-right[0]) < 1e-14
