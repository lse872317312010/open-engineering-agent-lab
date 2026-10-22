import math
from unittest import TestCase

import numpy as np

from oeal.models import (
    MotorParameters,
    PMSMInput,
    PMSMState,
    electromagnetic_torque,
    simulate,
    state_derivative,
)


class PMSMTests(TestCase):
    def setUp(self) -> None:
        self.motor = MotorParameters(
            stator_resistance_ohm=0.3,
            d_inductance_h=0.0008,
            q_inductance_h=0.0008,
            flux_linkage_wb=0.03,
            pole_pairs=7,
            inertia_kg_m2=0.0002,
            viscous_friction_nms=0.00001,
        )


    def test_torque_matches_surface_pmsm_formula(self) -> None:
        state = PMSMState(id_a=0.0, iq_a=2.0)
        self.assertAlmostEqual(electromagnetic_torque(state, self.motor), 0.63)


    def test_zero_speed_derivative_matches_electrical_equations(self) -> None:
        derivative = state_derivative(PMSMState(), PMSMInput(vd_v=3.0, vq_v=6.0), self.motor)
        self.assertAlmostEqual(derivative.id_a, 3.0 / 0.0008)
        self.assertAlmostEqual(derivative.iq_a, 6.0 / 0.0008)
        self.assertAlmostEqual(derivative.mechanical_speed_rad_s, 0.0)


    def test_zero_input_zero_state_is_an_equilibrium(self) -> None:
        trace = simulate(self.motor, PMSMInput(), duration_s=0.01, step_s=0.0001)
        np.testing.assert_allclose(trace.states, 0.0, atol=1e-14)
        np.testing.assert_allclose(trace.torque_nm, 0.0, atol=1e-14)


    def test_simulation_includes_endpoints_and_stays_finite(self) -> None:
        trace = simulate(
            self.motor,
            PMSMInput(vq_v=5.0, load_torque_nm=0.1),
            duration_s=0.0025,
            step_s=0.001,
        )
        self.assertEqual(trace.times_s[0], 0.0)
        self.assertEqual(trace.times_s[-1], 0.0025)
        self.assertEqual(trace.states.shape, (4, 4))
        self.assertTrue(np.all(np.isfinite(trace.states)))
        self.assertTrue(np.all(np.isfinite(trace.torque_nm)))

    def test_rk4_current_matches_locked_rotor_rl_response(self) -> None:
        locked_rotor = MotorParameters(
            stator_resistance_ohm=0.3,
            d_inductance_h=0.0008,
            q_inductance_h=0.0008,
            flux_linkage_wb=0.03,
            pole_pairs=7,
            inertia_kg_m2=1e9,
        )
        duration_s = 0.0026
        trace = simulate(
            locked_rotor,
            PMSMInput(vq_v=5.0),
            duration_s=duration_s,
            step_s=0.0001,
        )
        expected_iq = (5.0 / 0.3) * (1 - math.exp(-0.3 * duration_s / 0.0008))
        self.assertAlmostEqual(trace.states[-1, 1], expected_iq, delta=1e-5)


    def test_invalid_parameters_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "stator_resistance_ohm"):
            MotorParameters(0.0, 0.001, 0.001, 0.03, 7, 0.001)


    def test_invalid_simulation_step_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "step_s"):
            simulate(self.motor, PMSMInput(), duration_s=0.01, step_s=0.0)

