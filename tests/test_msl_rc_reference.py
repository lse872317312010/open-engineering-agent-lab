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
    import pytest

    pytest.importorskip("scipy")
    initial = [80.,70.,60.,100.,65.,50.]
    a = linear_solution(2., initial, 25., CAPACITY, RESISTANCE, 2.)
    b = linear_solution(4., initial, 25., 2*CAPACITY, RESISTANCE, 2.)
    np.testing.assert_allclose(a[:6], b[:6], atol=1e-11)
    np.testing.assert_allclose(2*a[7:], b[7:], atol=1e-11)
    loss = (np.asarray(initial)-a[:6]) @ CAPACITY
    assert abs(loss-sum(a[7:])) < 1e-10


def test_parameter_normalization_rejects_bad_dimensions_types_and_bounds():
    import pytest
    from msl_rc_parameters import rc_parameters

    for keyword, invalids in {
        "capacities_j_per_k": ([1.]*5, [1.]*5+[True], ["2"]*6, [0.]*6,
                              [1001.]*6, [float("nan")]*6),
        "link_resistances_k_per_w": ([1.]*4, [1.]*4+[True], [0.]*5,
                                    [21.]*5, [float("inf")]*5),
        "case_resistance_k_per_w": (True, "2", 0, 21, float("nan")),
    }.items():
        for value in invalids:
            with pytest.raises(ValueError):
                rc_parameters(**{keyword:value})
    assert rc_parameters()[0] == tuple(CAPACITY)
