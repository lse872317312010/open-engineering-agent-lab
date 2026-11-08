"""Hand-calculated two-node feedback step and transactional current/power rejection."""
import math

import numpy as np
import pytest

from oeal.current_envelope import advance_current_window, copper_power
from oeal.stator_feedback import CopperResistanceLaw, StatorCopperFeedback


def heater():
    data = dict(format_version=1, mass=[[2., 0.], [0., 3.]],
                bulk=[[1., -1.], [-1., 1.]], convection=[[0., 0.], [0., 1.]],
                forcing=[1., 0.], observations=[[1., 0.], [0., 1.], [2., 3.], [0., 1.]],
                h_bounds=[5., 80.], power_bounds_w=[0., 2.], ambient_c=25.)
    return StatorCopperFeedback(data, h_w_m2_k=5., drive_dt_s=.1, ticks_per_window=10,
                                ambient_c=25., law=CopperResistanceLaw(reference_ohm=1.))


def test_two_node_constant_current_energy_and_explicit_feedback():
    model = heater()
    current = math.sqrt(2/3)
    first = advance_current_window(model, 10, id_a=0., iq_a=current)
    np.testing.assert_allclose(first, [25+9/26, 25+1/26, 21/26, 5/26], atol=1e-14)
    next_power = 1+.004*9/26
    expected = np.linalg.solve([[3., -1.], [-1., 9.]],
                               [2*9/26+next_power, 3/26])
    second = advance_current_window(model, 20, id_a=0., iq_a=-current)
    np.testing.assert_allclose(second[:2], 25+expected, atol=1e-14)
    assert model.copper_j == pytest.approx(1+next_power)
    assert abs(model.balance_j) < 1e-14


@pytest.mark.parametrize("id_a,iq_a", [(0., float("nan")), (True, .5), (0., 2.1),
                                       (1.1, 1.), (1j, 0.), (0., 2.)])
def test_bad_current_or_overpower_does_not_advance(id_a, iq_a):
    model = heater()
    before = model.state
    with pytest.raises(ValueError):
        advance_current_window(model, 10, id_a=id_a, iq_a=iq_a)
    np.testing.assert_array_equal(model.state, before)
    assert model.windows == 0 and model.copper_j == 0


def test_squared_dq_current_and_positive_resistance():
    assert copper_power(.3, -.4, 2.) == pytest.approx(.75)
    with pytest.raises(ValueError):
        copper_power(0., .5, -1.)
