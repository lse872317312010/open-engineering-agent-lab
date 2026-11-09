"""Independent two-node heat solution, causal clocks, and transactional rejection."""
import numpy as np
import pytest

from oeal.stator_feedback import CopperResistanceLaw, StatorCopperFeedback


def bundle():
    return dict(format_version=1, mass=[[2., 0.], [0., 3.]],
                bulk=[[1., -1.], [-1., 1.]], convection=[[0., 0.], [0., 1.]],
                forcing=[1., 0.], observations=[[1., 0.], [0., 1.], [2., 3.], [0., 1.]],
                h_bounds=[5., 80.], power_bounds_w=[0., 2.], ambient_c=25.)


def feedback(**kwargs):
    parameters = dict(h_w_m2_k=5., drive_dt_s=.1, ticks_per_window=10, ambient_c=75.)
    parameters.update(kwargs)
    return StatorCopperFeedback(bundle(), **parameters)


def test_hot_ambient_translation_and_causal_energy_hand_calculation():
    model = feedback()
    assert model.resistance_ohm == pytest.approx(.36)
    assert model.windows == 0
    values = model.advance_window(10, 1.)
    # (M+K)^-1 f = (1/26) [9, 1]; reference is the selected ambient, not 0°C.
    np.testing.assert_allclose(values, [75+9/26, 75+1/26, 21/26, 5/26], atol=1e-14)
    assert model.resistance_ohm == pytest.approx(.3*(1+.004*(50+9/26)))
    assert model.copper_j == 1. and model.boundary_j == pytest.approx(5/26)
    assert abs(model.balance_j) < 1e-14
    returned = model.state
    returned[:] = 99
    assert not np.any(model.state == 99)


@pytest.mark.parametrize("tick,energy", [(9, 1.), (20, 1.), (0, 1.), (True, 1.),
                                        (10., 1.), (10, -1.), (10, float("nan")),
                                        (10, float("inf")), (10, 2.1), (10, True)])
def test_invalid_window_has_no_effect(tick, energy):
    model = feedback()
    before = model.state
    with pytest.raises(ValueError):
        model.advance_window(tick, energy)
    np.testing.assert_array_equal(model.state, before)
    assert model.windows == 0 and model.copper_j == model.boundary_j == 0
    assert model.resistance_ohm == pytest.approx(.36)


def test_repeated_tick_and_decreasing_energy_preserve_accepted_state():
    model = feedback()
    model.advance_window(10, 1.)
    before = model.state
    for tick, energy in ((10, 1.5), (20, .9)):
        with pytest.raises(ValueError):
            model.advance_window(tick, energy)
        np.testing.assert_array_equal(model.state, before)
        assert model.windows == 1 and model.copper_j == 1.


def test_temperature_domain_failure_after_prediction_is_transactional():
    model = feedback(ambient_c=125.)
    before = model.state
    with pytest.raises(ValueError, match="temperature outside"):
        model.advance_window(10, 1.)
    np.testing.assert_array_equal(model.state, before)
    assert model.windows == 0 and model.copper_j == model.boundary_j == 0


@pytest.mark.parametrize("temperature", [-.1, 125.1, float("nan"), True, 1j])
def test_resistance_domain_rejects(temperature):
    with pytest.raises(ValueError):
        CopperResistanceLaw().resistance(temperature)


@pytest.mark.parametrize("parameters", [dict(coefficient_per_k=-1.), dict(reference_ohm=0.),
                                         dict(minimum_c=30.), dict(maximum_c=float("inf"))])
def test_invalid_resistance_law_rejected(parameters):
    with pytest.raises(ValueError):
        CopperResistanceLaw(**parameters)
