"""Independent window-energy ramp and sampling-order references."""
import numpy as np
import pytest

from oeal.multirate import ThermalWindowClock


class IntegratingSink:
    dt_s = .0025

    def __init__(self):
        self.energy = np.zeros(2)

    def step_average(self, factors):
        self.energy += np.asarray(factors)*np.array([.04, .12])*self.dt_s
        return np.r_[25+self.energy/.04, 25., 25., 0., 0.]


def test_linear_power_ramp_uses_integral_not_last_sample():
    sink = IntegratingSink()
    clock = ThermalWindowClock(sink, source_powers_w=[.04, .12])
    packets = []
    for tick in range(101):
        t = tick*50e-6
        packet = clock.sample(tick, np.array([1., 2.])*t*t/2)
        if packet is not None:
            packets.append(packet)
    assert len(packets) == 2
    np.testing.assert_allclose(packets[0]["energy_j"], [3.125e-6, 6.25e-6], atol=1e-18)
    np.testing.assert_allclose(packets[0]["mean_power_w"], [.00125, .0025], atol=1e-15)
    np.testing.assert_allclose(sink.energy, [12.5e-6, 25e-6], atol=1e-18)
    assert packets[-1]["end_tick"] == 100 and packets[-1]["control_count"] == 50


@pytest.mark.parametrize("bad", [0, 2, .5, True])
def test_duplicate_gap_or_noninteger_tick_is_transactionally_rejected(bad):
    sink = IntegratingSink()
    clock = ThermalWindowClock(sink, source_powers_w=[.04, .12])
    clock.sample(0, [0., 0.])
    with pytest.raises((ValueError, TypeError)):
        clock.sample(bad, [0., 0.])
    assert clock.sample(1, [0., 0.]) is None
    np.testing.assert_array_equal(sink.energy, [0., 0.])


def test_decreasing_ledger_is_rejected():
    clock = ThermalWindowClock(IntegratingSink(), source_powers_w=[.04, .12])
    clock.sample(0, [1., 1.])
    with pytest.raises(ValueError):
        clock.sample(1, [.9, 1.])
    assert clock.sample(1, [1., 1.]) is None
