"""Independent quadratic/bilinear values, nonzero zero-current loss and validity clocks."""
import importlib
from pathlib import Path

import numpy as np
import pytest

from oeal.reference_loss_map import ReferenceCopperLossMap
from oeal.reference_validity import ReferenceSettlingGuard
from oeal.stator_feedback import StatorCopperFeedback


def packet():
    resistance, speed = [.3, .36, .42], [10., 20., 40.]
    coefficients = np.array([[[[base+r+.01*v+.01*r*v, .1, .05] for r in resistance]
                               for v in speed] for base in (1., 2.)])
    return dict(format_version=1, resistance_ohm=resistance, speed_abs_rad_s=speed,
                copper_coefficients=coefficients, reference_max_a=.5)


def test_quadratic_and_bilinear_hand_values_and_zero_reference_floor():
    model = ReferenceCopperLossMap(packet())
    assert model.mean_power(.33, omega_rad_s=15., iq_reference_a=.25) == pytest.approx(.23309375)
    assert model.mean_power(.33, omega_rad_s=-15., iq_reference_a=-.25) == pytest.approx(.17059375)
    assert model.mean_power(.33, omega_rad_s=15., iq_reference_a=0.) == pytest.approx(.05)


@pytest.mark.parametrize("r,v,i", [(.29, 20., .25), (.43, 20., .25), (.33, 9., .25),
    (.33, 41., .25), (.33, 20., -.25), (.33, 20., .51), (.33, 0., 0.),
    (float("nan"), 20., .25), (True, 20., .25)])
def test_lookup_rejects_unsupported_points(r, v, i):
    with pytest.raises(ValueError):
        ReferenceCopperLossMap(packet()).mean_power(r, omega_rad_s=v, iq_reference_a=i)


def test_nonpassive_quadratic_is_rejected():
    data = packet()
    data["copper_coefficients"][0, 0, 0, 1] = 100.
    with pytest.raises(ValueError, match="nonnegative quadratic"):
        ReferenceCopperLossMap(data)


def test_guard_resets_on_step_and_rejects_invalid_observation_transactionally():
    guard = ReferenceSettlingGuard(period_s=.001)
    for tick in range(25):
        guard.observe(tick, .1)
    assert guard.window_ready(20, 25)
    guard.observe(25, .4)
    assert guard.ready_after_tick == 45 and not guard.window_ready(25, 26)
    before = guard.last_tick, guard.reference_a, guard.ready_after_tick
    for tick, value in ((27, .4), (26, float("nan")), (True, .4), (26, .51)):
        with pytest.raises(ValueError):
            guard.observe(tick, value)
        assert (guard.last_tick, guard.reference_a, guard.ready_after_tick) == before
    for tick in range(26, 65):
        guard.observe(tick, .4)
    guard.require_constant_window(45, 65, .4)


def test_smooth_slew_ready_but_varying_reference_cannot_submit_constant_source():
    guard = ReferenceSettlingGuard(period_s=.001)
    for tick in range(25):
        guard.observe(tick, .1+.001*tick)
    assert guard.window_ready(20, 25)
    with pytest.raises(ValueError, match="varying reference"):
        guard.require_constant_window(20, 25, .124)


def test_guarded_heat_submission_keeps_unsettled_state_and_preserves_time():
    data = dict(format_version=1, mass=[[2., 0.], [0., 3.]],
                bulk=[[1., -1.], [-1., 1.]], convection=[[0., 0.], [0., 1.]],
                forcing=[1., 0.], observations=[[1., 0.], [0., 1.], [2., 3.], [0., 1.]],
                h_bounds=[5., 80.], power_bounds_w=[0., 2.], ambient_c=25.)
    thermal = StatorCopperFeedback(data, h_w_m2_k=5., drive_dt_s=.1,
                                   ticks_per_window=1, ambient_c=25.)
    guard = ReferenceSettlingGuard(period_s=.1, settling_s=.2)
    model = ReferenceCopperLossMap(packet())
    guard.observe(0, .25)
    with pytest.raises(ValueError, match="unsettled"):
        model.advance_thermal_window(thermal, 1, omega_rad_s=10., iq_reference_a=.25,
                                     guard=guard, control_start_tick=0, control_end_tick=1)
    assert thermal.windows == 0 and not np.any(thermal.state)
    thermal.advance_window(1, 0.)
    guard.observe(1, .25)
    thermal.advance_window(2, 0.)
    guard.observe(2, .25)
    output = model.advance_thermal_window(thermal, 3, omega_rad_s=10., iq_reference_a=.25,
                                          guard=guard, control_start_tick=2, control_end_tick=3)
    power = .226875  # a=2.43, b=.1, c=.05 at R=.3, speed=10, I=.25
    expected = np.linalg.solve([[2.1, -.1], [-.1, 3.6]], [.1*power, 0.])
    np.testing.assert_allclose(output[:2], 25+expected, atol=1e-14)
    assert abs(thermal.balance_j) < 1e-14


def test_affine_response_energy_moments_match_direct_scalar_values(monkeypatch):
    pytest.importorskip("scipy")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "benchmarks"))
    module = importlib.import_module("p7_reference_periodic")
    coefficients = module.quadratic_moments(np.array([[2.]]), np.array([[1.], [2.]]),
                                           np.array([[3.], [4.]]), .5, 2.)
    np.testing.assert_allclose(coefficients, [32., 24., 5.], atol=1e-14)
    assert np.polyval(coefficients, .125) == pytest.approx(8.5)
