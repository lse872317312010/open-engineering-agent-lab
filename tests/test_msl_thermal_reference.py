"""Hand calculations independent of MSL components or generated FMU."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from msl_thermal_reference import CAPACITY, balance, flows, rhs  # noqa: E402


def test_uniform_thermal_equilibrium_and_junction_initial_slope():
    for ambient in (-10., 25., 60.):
        y = np.r_[np.full(6, ambient), 0., 0.]
        np.testing.assert_array_equal(rhs(0., y, (0, 0, 0, 0, 0, 0), ambient), np.zeros(8))
        f = rhs(0., y, (0, 0, 0, .5, 0, 0), ambient)
        np.testing.assert_array_equal(f, [0., 0., 0., 1., 0., 0., .5, 0.])
        assert balance(y, ambient) == 0.


def test_signed_flows_and_nonzero_power_identity():
    y = np.array([45., 39., 35., 42., 38., 31., 50., 20.])
    q = flows(y[:6], 25.)
    np.testing.assert_allclose(q, [10., 10., -1.5, 5., 7/1.2, 7.], atol=1e-14)
    f = rhs(0., y, (40, 5, 0, 15, 0, 0), 25.)
    assert abs(CAPACITY @ f[:6] - (f[6]-f[7])) < 1e-13
    assert f[6] == 60. and f[7] == 7.


def test_celsius_shift_invariance_and_energy_fault():
    y = np.array([45., 39., 35., 42., 38., 31., 50., 20.])
    shifted = y.copy()
    shifted[:6] += 273.15
    np.testing.assert_allclose(rhs(0., y, (0,)*6, 25.),
                               rhs(0., shifted, (0,)*6, 298.15), atol=1e-12)
    assert abs(balance(y, 25.)-balance(shifted, 298.15)) < 1e-10
    corrupt = y.copy()
    corrupt[6] += 10.
    assert abs(balance(corrupt, 25.)-balance(y, 25.)+10.) < 1e-12
