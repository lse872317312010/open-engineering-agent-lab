import math
from dataclasses import replace
from unittest import TestCase

from oeal.current_control import (
    CurrentPIParameters,
    CurrentPIState,
    current_control_step,
    radial_limit,
)


class CurrentControlTests(TestCase):
    def setUp(self):
        self.parameters = CurrentPIParameters(2.0, 3.0, 4.0, 5.0, 100.0, 10.0, 20.0)

    def step(self, state=None, parameters=None, **overrides):
        values = dict(
            reference_d_a=0.0, reference_q_a=0.0,
            measured_d_a=0.0, measured_q_a=0.0, period_s=0.1,
        )
        values.update(overrides)
        return current_control_step(
            parameters or self.parameters, state or CurrentPIState(), **values
        )

    def test_radial_limit_geometry_boundary_and_extreme_values(self):
        self.assertEqual(radial_limit(0.0, 0.0, 5.0), (0.0, 0.0))
        self.assertEqual(radial_limit(3.0, 4.0, 5.0), (3.0, 4.0))
        d, q = radial_limit(-6.0, 8.0, 5.0)
        self.assertAlmostEqual(d, -3.0)
        self.assertAlmostEqual(q, 4.0)
        d, q = radial_limit(1.7e308, 1.7e308, 5.0)
        self.assertAlmostEqual(math.hypot(d, q), 5.0)
        self.assertAlmostEqual(d, q)

    def test_backward_rectangle_and_independent_axis_gains(self):
        state = CurrentPIState(1.0, -2.0)
        result = self.step(state, reference_d_a=2.0, reference_q_a=-1.0)
        self.assertAlmostEqual(result.vd_v, 5.6)
        self.assertAlmostEqual(result.vq_v, -6.5)
        self.assertAlmostEqual(result.next_state.integral_d_v, 1.6)
        self.assertAlmostEqual(result.next_state.integral_q_v, -2.5)
        self.assertEqual(state, CurrentPIState(1.0, -2.0))
        self.assertFalse(result.voltage_limited)
        self.assertFalse(result.current_reference_limited)

    def test_constant_error_integral_recurrence(self):
        state = CurrentPIState()
        for _ in range(4):
            result = self.step(state, reference_d_a=1.0)
            state = result.next_state
        self.assertAlmostEqual(state.integral_d_v, 1.2)
        self.assertAlmostEqual(result.vd_v, 3.2)

    def test_reference_limited_before_error_without_clipping_measurement(self):
        result = self.step(
            parameters=replace(self.parameters, current_limit_a=5.0),
            reference_d_a=6.0, reference_q_a=8.0, measured_d_a=8.0,
        )
        self.assertAlmostEqual(result.reference_d_a, 3.0)
        self.assertAlmostEqual(result.reference_q_a, 4.0)
        self.assertAlmostEqual(result.vd_v, -11.5)
        self.assertTrue(result.current_reference_limited)

    def test_total_voltage_including_feedforward_drives_back_calculation(self):
        p = CurrentPIParameters(0.0, 1.0, 0.0, 1.0, 2.5, 10.0, math.log(2.0))
        result = self.step(
            parameters=p, reference_d_a=1.0, reference_q_a=2.0, period_s=1.0,
            feedforward_d_v=2.0, feedforward_q_v=2.0,
        )
        self.assertAlmostEqual(result.vd_v, 1.5)
        self.assertAlmostEqual(result.vq_v, 2.0)
        self.assertAlmostEqual(result.next_state.integral_d_v, 0.25)
        self.assertAlmostEqual(result.next_state.integral_q_v, 1.0)
        self.assertTrue(result.voltage_limited)

    def test_sustained_saturation_and_reversed_error_recovery(self):
        p = CurrentPIParameters(0.0, 10.0, 0.0, 10.0, 2.0, 10.0, 1e6)
        state = CurrentPIState()
        for _ in range(100):
            result = self.step(state, p, reference_d_a=10.0)
            state = result.next_state
        self.assertAlmostEqual(state.integral_d_v, 2.0)
        self.assertAlmostEqual(result.vd_v, 2.0)
        for _ in range(2):
            result = self.step(state, p, reference_d_a=-1.0)
            state = result.next_state
        self.assertAlmostEqual(result.vd_v, 0.0)
        self.assertAlmostEqual(state.integral_d_v, 0.0)

    def test_zero_ki_is_proportional_only_even_with_saturation(self):
        p = replace(self.parameters, ki_d_v_per_as=0.0, ki_q_v_per_as=0.0,
                    voltage_limit_v=1.0)
        result = self.step(parameters=p, reference_d_a=2.0)
        self.assertAlmostEqual(result.vd_v, 1.0)
        self.assertEqual(result.next_state, CurrentPIState())
        with self.assertRaisesRegex(ValueError, "zero Ki"):
            self.step(CurrentPIState(1.0, 0.0), p)
        with self.assertRaisesRegex(ValueError, "zero Ki"):
            self.step(CurrentPIState(0.0, 1.0), p)

    def test_closed_loop_against_exact_zero_order_hold_rl_plant(self):
        # Synthetic R=0.3 ohm, L=1 mH, bandwidth=1000/s; no PMSM/RK4 calls.
        resistance, inductance, period = 0.3, 0.001, 1e-5
        p = CurrentPIParameters(1.0, 300.0, 1.0, 300.0, 2.0, 2.0, 1000.0)
        decay = math.exp(-resistance * period / inductance)
        currents = [0.0, 0.0]
        state = CurrentPIState()
        for _ in range(5000):
            result = self.step(
                state, p, reference_d_a=1.0, reference_q_a=-0.5,
                measured_d_a=currents[0], measured_q_a=currents[1], period_s=period,
            )
            state = result.next_state
            for axis, voltage in enumerate((result.vd_v, result.vq_v)):
                currents[axis] = decay * currents[axis] + (1 - decay) * voltage / resistance
            self.assertLessEqual(math.hypot(result.vd_v, result.vq_v), 2.0 + 1e-12)
        self.assertAlmostEqual(currents[0], 1.0, delta=1e-5)
        self.assertAlmostEqual(currents[1], -0.5, delta=1e-5)
        self.assertAlmostEqual(result.vd_v, 0.3, delta=1e-5)
        self.assertAlmostEqual(result.vq_v, -0.15, delta=1e-5)

    def test_invalid_parameters_and_state(self):
        for name in vars(self.parameters):
            for invalid in (math.nan, math.inf, -math.inf, -1.0):
                with self.subTest(name=name, invalid=invalid):
                    with self.assertRaises(ValueError):
                        replace(self.parameters, **{name: invalid})
        for name in ("voltage_limit_v", "current_limit_a", "tracking_rate_per_s"):
            with self.assertRaises(ValueError):
                replace(self.parameters, **{name: 0.0})
        for invalid in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                CurrentPIState(invalid, 0.0)
            with self.assertRaises(ValueError):
                CurrentPIState(0.0, invalid)

    def test_invalid_step_and_limiter_inputs(self):
        for name in (
            "reference_d_a", "reference_q_a", "measured_d_a", "measured_q_a",
            "period_s", "feedforward_d_v", "feedforward_q_v",
        ):
            for invalid in (math.nan, math.inf, -math.inf):
                with self.subTest(name=name, invalid=invalid):
                    with self.assertRaises(ValueError):
                        self.step(**{name: invalid})
        for invalid in (0.0, -0.1):
            with self.assertRaises(ValueError):
                self.step(period_s=invalid)
        for index in range(3):
            for invalid in (math.nan, math.inf, -math.inf):
                values = [1.0, 1.0, 1.0]
                values[index] = invalid
                with self.assertRaises(ValueError):
                    radial_limit(*values)
        for invalid in (0.0, -1.0):
            with self.assertRaises(ValueError):
                radial_limit(1.0, 1.0, invalid)

    def test_overflow_rejected_without_mutating_state(self):
        state = CurrentPIState(1.0, 2.0)
        with self.assertRaises(ValueError):
            self.step(state, reference_d_a=1e308, measured_d_a=-1.7e308)
        self.assertEqual(state, CurrentPIState(1.0, 2.0))
