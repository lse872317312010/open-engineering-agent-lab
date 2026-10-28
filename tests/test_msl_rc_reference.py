"""Independent RC scaling and stored-energy reference cases."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from msl_rc_reference import CAPACITY, RESISTANCE, linear_solution, rates  # noqa: E402


def test_uniform_hot_start_capacity_scaling_and_power():
    a = rates([80.]*6, [0.]*6, 1/3, .02, 25., CAPACITY, RESISTANCE, 2.)[0]
    b = rates([80.]*6, [0.]*6, 1/3, .02, 25., 2*CAPACITY, RESISTANCE, 2.)[0]
    np.testing.assert_allclose(b[:6], a[:6]/2, atol=1e-15)
    assert abs(CAPACITY @ a[:6]+a[7]) < 1e-12
    assert abs(2*CAPACITY @ b[:6]+b[7]) < 1e-12
    np.testing.assert_allclose(a[8:], b[8:], atol=1e-15)


def test_exact_linear_double_capacity_time_and_energy_scaling():
    initial = [80.,70.,60.,100.,65.,50.]
    a = linear_solution(2., initial, 25., CAPACITY, RESISTANCE, 2.)
    b = linear_solution(4., initial, 25., 2*CAPACITY, RESISTANCE, 2.)
    np.testing.assert_allclose(a[:6], b[:6], atol=1e-11)
    np.testing.assert_allclose(2*a[7:], b[7:], atol=1e-11)
    loss = (np.asarray(initial)-a[:6]) @ CAPACITY
    assert abs(loss-sum(a[7:])) < 1e-10
