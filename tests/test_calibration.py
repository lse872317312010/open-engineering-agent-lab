from unittest import TestCase

import numpy as np

from oeal.calibration import fit_rc, simulate_rc


class CalibrationTests(TestCase):
    def test_identifies_analytic_training_and_predicts_distinct_holdout(self):
        training = np.tile(np.repeat([0.0, 5.0, 20.0, 3.0], 50), 4)
        temperature = simulate_rc(training, 1, 1.5, 80)
        fit = fit_rc(temperature, training, 1)
        self.assertAlmostEqual(fit["resistance_k_per_w"], 1.5, delta=1e-8)
        self.assertAlmostEqual(fit["capacity_j_per_k"], 80, delta=1e-7)
        holdout = 10 + 7 * np.sin(np.arange(300) / 23)
        actual = simulate_rc(holdout, 1, 1.5, 80)
        predicted = simulate_rc(
            holdout, 1, fit["resistance_k_per_w"], fit["capacity_j_per_k"]
        )
        np.testing.assert_allclose(predicted, actual, atol=1e-8)

    def test_rejects_unexcited_or_misaligned_training(self):
        with self.assertRaises(ValueError):
            fit_rc(np.full(21, 25), np.zeros(20), 1)
        with self.assertRaises(ValueError):
            fit_rc(np.zeros(20), np.zeros(20), 1)
