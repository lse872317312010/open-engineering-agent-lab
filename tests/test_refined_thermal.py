"""Independent physical limits for the six-node network and backlash port."""

import numpy as np
import pytest

pytest.importorskip("scipy")

from oeal.refined_thermal import CAPACITIES, ThermalNetwork  # noqa: E402


def test_environment_equilibrium_and_total_energy():
    network = ThermalNetwork()
    np.testing.assert_allclose(network.advance(np.zeros(6)), np.full(6, 25), atol=1e-12)
    temperatures = np.array([90, 80, 50, 110, 60, 40])
    powers = np.array([20, 5, 2, 15, 0, 0])
    assert abs(network.balance_error_w(temperatures, powers)) < 1e-8
    assert np.all(np.linalg.eigvalsh(network.conductance) > 0)
    assert float(CAPACITIES @ network.rates(temperatures, np.zeros(6))) < 0


def test_heat_input_is_positive_and_invalid_ports_rejected():
    network = ThermalNetwork()
    temperatures = network.advance([10, 0, 0, 10, 0, 0])
    assert np.all(temperatures >= 25)
    assert temperatures[0] > 25 and temperatures[3] > 25
    with pytest.raises(ValueError):
        network.advance([1, 2])
    with pytest.raises(ValueError):
        network.advance([float("nan")] * 6)
