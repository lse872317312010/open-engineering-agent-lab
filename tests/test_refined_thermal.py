"""Independent equilibrium, energy and heat-port checks for the six-node network."""

import importlib.util
import unittest

import numpy as np

from oeal.refined_thermal import CAPACITIES, ThermalNetwork


@unittest.skipUnless(importlib.util.find_spec("scipy"), "optional SciPy backend")
class RefinedThermalTests(unittest.TestCase):
    def test_environment_equilibrium_and_total_energy(self):
        network = ThermalNetwork()
        np.testing.assert_allclose(network.advance(np.zeros(6)), np.full(6, 25), atol=1e-12)
        temperatures = np.array([90, 80, 50, 110, 60, 40])
        powers = np.array([20, 5, 2, 15, 0, 0])
        self.assertLess(abs(network.balance_error_w(temperatures, powers)), 1e-8)
        self.assertTrue(np.all(np.linalg.eigvalsh(network.conductance) > 0))
        self.assertLess(
            float(CAPACITIES @ network.rates(temperatures, np.zeros(6))), 0
        )

    def test_heat_input_is_positive_and_invalid_ports_rejected(self):
        network = ThermalNetwork()
        temperatures = network.advance([10, 0, 0, 10, 0, 0])
        self.assertTrue(np.all(temperatures >= 25))
        self.assertGreater(temperatures[0], 25)
        self.assertGreater(temperatures[3], 25)
        with self.assertRaises(ValueError):
            network.advance([1, 2])
        with self.assertRaises(ValueError):
            network.advance([float("nan")] * 6)
