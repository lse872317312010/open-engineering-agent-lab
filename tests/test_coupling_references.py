"""Hand vectors and independent linear two-mass references precede model changes."""

import importlib.util
import unittest

import numpy as np

from oeal.coupling import (
    TorqueHistory,
    midpoint_exchange,
    path_average,
    path_midpoint_exchange,
    transmission,
)


def step(state, period, exchange_function=midpoint_exchange):
    qm, vm, ql, vl = state
    exchange = exchange_function(qm - ql, vm - vl, 0, 1 / 0.125 + 1 / 2, period)
    torque = exchange.torque_nm
    result = np.array([
        qm + period * vm - 0.5 * period ** 2 * torque / 0.125,
        vm - period * torque / 0.125,
        ql + period * vl + 0.5 * period ** 2 * torque / 2,
        vl + period * torque / 2,
    ])
    return result, exchange


def energy(state):
    qm, vm, ql, vl = state
    return 0.5 * 0.125 * vm ** 2 + 0.5 * 2 * vl ** 2 + 0.5 * 500 * (qm - ql) ** 2


class CouplingReferenceTests(unittest.TestCase):
    def test_hand_calculated_midpoint_and_unloading_branch(self):
        result = midpoint_exchange(0.5, 0.2, 1, 3, 0.1, stiffness=4, damping=2)
        self.assertAlmostEqual(result.torque_nm, 2.55 / 1.33)
        self.assertFalse(result.fallback)
        self.assertLess(abs(result.law_residual_nm), 1e-12)
        result = midpoint_exchange(0.01, -10, 0, 1, 0.001)
        self.assertEqual(result.torque_nm, 0)
        self.assertAlmostEqual(result.damping_power_w, 25)
        self.assertFalse(result.fallback)

    def test_zero_crossing_and_invalid_inputs_are_not_certified(self):
        result = midpoint_exchange(-0.001, 1, 0, 1, 0.002)
        self.assertTrue(result.fallback)
        self.assertEqual(result.torque_nm, transmission(-0.001, 1)[0])
        for inverse, period in ((-1, 0.001), (1, 0), (float("nan"), 0.001)):
            with self.assertRaises(ValueError):
                midpoint_exchange(0.01, 0, 0, inverse, period)

    def test_isolated_two_mass_energy_and_physical_heat_identity(self):
        state = np.array([0.02, 0.1, 0.0, 0.0])
        initial, heat = energy(state), 0.0
        for _ in range(10):
            state, exchange = step(state, 0.001)
            self.assertFalse(exchange.fallback)
            heat += 0.001 * exchange.damping_power_w
            self.assertLess(abs(energy(state) + heat - initial), 1e-10)

    @unittest.skipUnless(importlib.util.find_spec("scipy"), "optional SciPy")
    def test_second_order_state_convergence_against_matrix_exponential(self):
        from scipy.linalg import expm

        matrix = np.array([
            [0, 1, 0, 0],
            [-500 / 0.125, -1 / 0.125, 500 / 0.125, 1 / 0.125],
            [0, 0, 0, 1],
            [500 / 2, 1 / 2, -500 / 2, -1 / 2],
        ])
        initial = np.array([0.02, 0.1, 0, 0])
        reference = expm(matrix * 0.01) @ initial
        errors = []
        for period in (0.001, 0.0005, 0.00025):
            state = initial.copy()
            for _ in range(round(0.01 / period)):
                state, result = step(state, period)
                self.assertFalse(result.fallback)
            errors.append(float(np.linalg.norm(state - reference)))
        for ratio in (errors[0] / errors[1], errors[1] / errors[2]):
            self.assertGreater(ratio, 3.8)
            self.assertLess(ratio, 4.2)

    def test_path_midpoint_resolves_crossing_and_conserves_physical_work(self):
        state = np.array([-0.001, 1.0, 0, 0])
        initial = energy(state)
        after, exchange = step(state, 0.002, path_midpoint_exchange)
        self.assertTrue(exchange.transition_resolved)
        self.assertFalse(exchange.fallback)
        self.assertGreater(exchange.damping_power_w, 0)
        self.assertLess(abs(energy(after) + 0.002 * exchange.damping_power_w - initial),
                        1e-10)

    def test_torque_history_is_causal_and_exact_for_a_linear_mean_trend(self):
        history = TorqueHistory()
        self.assertEqual(history.observe(0, 0, 3), (3, 3, 0))
        mean, forecast, windows = history.observe(0.01, 0.0301, 3.02)
        self.assertAlmostEqual(mean, 3.01)
        self.assertAlmostEqual(forecast, 3.01)
        self.assertEqual(windows, 1)
        mean, forecast, windows = history.observe(0.02, 0.0604, 3.04)
        self.assertAlmostEqual(mean, 3.03)
        self.assertAlmostEqual(forecast, 3.05)
        self.assertEqual(windows, 2)
        with self.assertRaises(ValueError):
            history.observe(0.02, 0.0604, 3.04)

    @unittest.skipUnless(importlib.util.find_spec("scipy"), "optional SciPy")
    def test_piecewise_force_and_heat_match_independent_adaptive_quadrature(self):
        from scipy.integrate import quad

        force, heat, resolved = path_average(-0.01, 2, 0.02, backlash=0.003)
        self.assertTrue(resolved)
        for index, actual in ((0, force), (2, heat)):
            expected = quad(
                lambda x: transmission(-0.01 + 0.04 * x, 2, backlash=0.003)[index],
                0, 1, points=[0.075, 0.175, 0.325], epsabs=1e-12,
            )[0]
            self.assertLess(abs(actual - expected), 1e-10)

    @unittest.skipUnless(importlib.util.find_spec("scipy"), "optional SciPy")
    def test_path_reference_retains_second_order_in_smooth_linear_limit(self):
        from scipy.linalg import expm

        initial = np.array([0.02, 0.1, 0, 0])
        matrix = np.array([[0, 1, 0, 0], [-4000, -8, 4000, 8],
                           [0, 0, 0, 1], [250, 0.5, -250, -0.5]])
        exact = expm(matrix * 0.01) @ initial
        errors = []
        for h in (0.001, 0.0005, 0.00025):
            state = initial.copy()
            for _ in range(round(0.01 / h)):
                state, exchange = step(state, h, path_midpoint_exchange)
                self.assertFalse(exchange.fallback)
            errors.append(float(np.linalg.norm(state - exact)))
        self.assertTrue(all(3.8 < a / b < 4.2 for a, b in zip(
            errors[:-1], errors[1:], strict=True
        )))
