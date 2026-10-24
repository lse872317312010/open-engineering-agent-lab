"""Analytic energy limits precede changes to the optional physical backend."""

import importlib.util
import unittest

import numpy as np

from oeal.energy import (
    ENERGY_COLUMNS,
    auxiliary_device_power,
    linear_magnetic_energy,
    recompute_balances,
)
from oeal.refined_thermal import AMBIENT_LINKS, CAPACITIES, ThermalNetwork


class EnergyReferenceTests(unittest.TestCase):
    def test_flux_energy_matches_hand_calculated_dq_inductors(self):
        value = linear_magnetic_energy(0.104 - 0.009j, 0.002, 0.003, 0.1)
        self.assertAlmostEqual(float(value), 0.02625)
        self.assertEqual(float(linear_magnetic_energy(0.1 + 0j, 0.002, 0.003, 0.1)), 0)
        with self.assertRaises(ValueError):
            linear_magnetic_energy(0j, 0, 0.003, 0.1)

    def test_device_shunt_has_explicit_off_and_on_hand_vectors(self):
        self.assertAlmostEqual(float(auxiliary_device_power(3 + 4j, 50e-6, True)), 12.75)
        self.assertAlmostEqual(float(auxiliary_device_power(3 + 4j, 50e-6, False)), 0.75)
        with self.assertRaises(ValueError):
            auxiliary_device_power(1, 0, True)

    def test_balance_detects_missing_work_and_ignores_self_reported_residual(self):
        rows = np.zeros((11, len(ENERGY_COLUMNS)))
        t = np.linspace(0, 1, 11)
        signals = {"time_s": t, "source_j": 10 * t, "source_abs_j": 10 * t,
                   "magnetic_j": 2 * t, "kinetic_j": 3 * t, "thermal_j": 4 * t,
                   "ambient_j": t, "copper_j": 4 * t, "rotor_friction_j": t,
                   "local_residual_j": np.full(11, -999)}
        for name, values in signals.items():
            rows[:, ENERGY_COLUMNS.index(name)] = values
        local, thermal, metrics = recompute_balances(ENERGY_COLUMNS, rows)
        np.testing.assert_allclose(local, 0, atol=1e-12)
        np.testing.assert_allclose(thermal, 0, atol=1e-12)
        self.assertLess(metrics["energy_balance_abs_j"], metrics["energy_balance_limit_j"])
        rows[:, ENERGY_COLUMNS.index("kinetic_j")] += t
        _, _, metrics = recompute_balances(ENERGY_COLUMNS, rows)
        self.assertAlmostEqual(metrics["energy_balance_abs_j"], 1)

    @unittest.skipUnless(importlib.util.find_spec("scipy"), "optional SciPy")
    def test_six_node_heat_matches_independent_augmented_exponential(self):
        from scipy.linalg import expm

        period = 0.7
        network = ThermalNetwork(period_s=period)
        powers = np.array([20, 0, 3, 7, 0, 0])
        augmented = np.zeros((8, 8))
        augmented[:6, :6] = network.matrix
        augmented[:6, 7] = powers / CAPACITIES
        for node, resistance in AMBIENT_LINKS:
            augmented[6, node] = 1 / resistance
        initial = np.zeros(8)
        initial[7] = 1
        independent = expm(augmented * period) @ initial
        actual = network.advance(powers)
        np.testing.assert_allclose(actual - 25, independent[:6], atol=1e-10)
        stored = float(CAPACITIES @ (actual - 25))
        self.assertLess(abs(stored + independent[6] - sum(powers) * period), 1e-8)
