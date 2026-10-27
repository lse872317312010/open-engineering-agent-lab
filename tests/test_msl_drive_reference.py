"""Hand checks independent of motulator and FMI implementation."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from msl_drive_reference import independent_rates, resistance, route_heat  # noqa: E402


def test_actual_loss_routing_and_temperature_feedback_hand_values():
    np.testing.assert_array_equal(route_heat(4.5, .2, 1.1, 3.), [4.5, 0, .2, 4.1, 0, 0])
    assert abs(float(resistance(35.))-.31179) < 1e-15
    assert float(resistance(35., False)) == .3
    # Both axes are peak-vector amps: 1.5*.3*|2j|^2 = 1.8 W.
    assert abs(1.5*.3*abs(2j)**2-1.8) < 1e-15


def test_nonzero_temperature_flows_and_total_power_identity():
    t = np.array([[45., 39., 35., 42., 38., 31.]])
    heat = np.array([[40., 5., .2, 15., 0., 0.]])
    rates = independent_rates(t, heat)[0]
    expected_net = np.array([30., 5., 6.7, 10., -1.5+5.-7/1.2, 7/1.2-2.])
    # Board receives -1.5 W from case, +5 W from junction, rejects 7/1.2 W.
    np.testing.assert_allclose(rates[:6]*[60,70,200,.5,25,100], expected_net, atol=1e-13)
    assert abs(np.dot([60,70,200,.5,25,100], rates[:6])+rates[7]-heat.sum()) < 1e-13


def test_misrouted_copper_cannot_hide_behind_total_energy_conservation():
    t = np.full((1, 6), 25.)
    correct = independent_rates(t, [[10., 0., 0., 0., 0., 0.]])
    wrong = independent_rates(t, [[0., 0., 0., 10., 0., 0.]])
    assert abs(correct[0, 6]-wrong[0, 6]) == 0.
    assert np.max(np.abs(correct[:, :6]-wrong[:, :6])) > 1.
