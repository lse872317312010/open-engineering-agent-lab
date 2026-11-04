"""Independent current direction and peak-value torque convention."""
import math

import pytest

from oeal.transforms import clarke, inverse_clarke, inverse_park, park


@pytest.mark.parametrize("angle", [0., .37, math.pi/2])
@pytest.mark.parametrize(("d", "q"), [(0., 2.), (0., -2.), (2., 0.), (-2., 0.)])
def test_dq_current_direction(angle, d, q):
    abc = inverse_clarke(*inverse_park(d, q, angle))
    alpha, beta, zero = clarke(*abc)
    actual = park(alpha, beta, angle)
    assert actual == pytest.approx((d, q), abs=1e-12)
    assert zero == pytest.approx(0., abs=1e-12)


def test_peak_value_torque_hand_limit():
    assert 1.5*4*.06*2 == pytest.approx(.72)
    assert 1.5*4*.06*(-2) == pytest.approx(-.72)
