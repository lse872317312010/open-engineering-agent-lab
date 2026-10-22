import math
from dataclasses import replace
from unittest import TestCase

import numpy as np

from oeal.foc import FOCConfig, average_svpwm, decoupling_voltage, simulate_foc
from oeal.models import MotorParameters, PMSMInput, PMSMState, state_derivative
from oeal.transforms import clarke


class FOCTests(TestCase):
    def setUp(self):
        self.motor = MotorParameters(0.3, 0.0008, 0.001, 0.03, 7, 0.002, 1e-5)

    def test_feedforward_cancels_coupling_at_nonzero_speed_both_directions(self):
        for speed in (-30.0, 0.0, 30.0):
            s = PMSMState(2.0, 3.0, speed)
            fd, fq = decoupling_voltage(self.motor, s)
            derivative = state_derivative(
                s, PMSMInput(fd + 0.6, fq + 0.9), self.motor
            )
            self.assertAlmostEqual(derivative.id_a, 0.0, delta=1e-9)
            self.assertAlmostEqual(derivative.iq_a, 0.0, delta=1e-9)

    def test_svpwm_reconstruction_and_linear_bus_limit_all_angles(self):
        for angle in np.linspace(-math.pi, math.pi, 31):
            alpha, beta, duties = average_svpwm(
                100 * math.cos(angle), 100 * math.sin(angle), 24.0
            )
            self.assertLessEqual(math.hypot(alpha, beta), 24 / math.sqrt(3) + 1e-12)
            self.assertTrue(all(-1e-14 <= d <= 1 + 1e-14 for d in duties))
            a, b, _ = clarke(*(24 * d for d in duties))
            self.assertAlmostEqual(a, alpha)
            self.assertAlmostEqual(b, beta)

    def test_svpwm_zero_and_invalid(self):
        self.assertEqual(average_svpwm(0.0, 0.0, 24.0), (0.0, 0.0, (0.5, 0.5, 0.5)))
        for value in (0.0, -1.0, math.nan, math.inf):
            with self.assertRaises(ValueError):
                average_svpwm(0.0, 0.0, value)

    def test_sample_ticks_delay_and_step_alignment(self):
        c = FOCConfig(duration_s=0.001, step_time_s=0.0, delay_samples=1)
        trace = simulate_foc(self.motor, c).samples
        np.testing.assert_allclose(trace[:, 0], np.arange(21) * 50e-6, atol=1e-15)
        np.testing.assert_allclose(trace[0, 5:7], 0.0)
        self.assertEqual(trace[1, 2], 0.0)
        self.assertGreater(trace[2, 2], 0.0)
        self.assertTrue(np.all(trace[0, 7:10] == 0.5))

    def test_20khz_step_tracks_and_substep_halving_converges(self):
        c = FOCConfig(duration_s=0.01)
        coarse = simulate_foc(self.motor, c).samples
        fine = simulate_foc(self.motor, replace(c, integration_step_s=2.5e-6)).samples
        self.assertLess(abs(fine[-1, 2] - 5), 0.05)
        self.assertLess(abs(fine[-1, 1]), 0.05)
        np.testing.assert_allclose(coarse[:, 1:5], fine[:, 1:5], atol=1e-6, rtol=1e-6)

    def test_bus_saturation_and_current_reference_limit(self):
        c = FOCConfig(duration_s=0.002, step_time_s=0, vdc_v=2, iq_reference_a=50)
        data = simulate_foc(self.motor, c).samples
        self.assertTrue(np.any(data[:, 12]))
        self.assertTrue(np.all(data[:, 11] <= c.current_limit_a + 1e-12))
        self.assertTrue(np.all(np.hypot(data[:, 5], data[:, 6]) <= 2 / math.sqrt(3) + 1e-12))

    def test_invalid_timing_and_budget(self):
        for changes in (
            {"delay_samples": 2}, {"delay_samples": True}, {"duration_s": 0},
            {"integration_step_s": 1e-3}, {"step_time_s": 1e-7},
            {"duration_s": 1e6}, {"vdc_v": math.inf},
        ):
            with self.assertRaises(ValueError):
                FOCConfig(**changes)
