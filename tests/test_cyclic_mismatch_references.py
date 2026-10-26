"""Independent trajectory samples and actual upstream plant/controller isolation."""

import importlib.util
import math
import unittest

from oeal.trajectories import joint_reference


class TrajectoryReferences(unittest.TestCase):
    def test_two_cycles_hand_samples_and_negative_amplitude(self):
        settings = dict(position_start_s=.02, position_step_rad=.04,
                        position_cycle_period_s=.6)
        for t, delta in ((0, 0), (.02, 0), (.17, .02), (.32, .04),
                         (.62, 0), (.92, .04), (1.22, 0)):
            self.assertAlmostEqual(joint_reference(t, -1.5, settings), -1.5 + delta)
        settings["position_step_rad"] = -.04
        self.assertAlmostEqual(joint_reference(.32, -1.5, settings), -1.54)

    def test_legacy_linear_ramp_and_zero_endpoint_velocity(self):
        settings = dict(position_start_s=.02, position_step_rad=.08, position_ramp_s=.12)
        for t, delta in ((0, 0), (.02, 0), (.08, .04), (.14, .08), (1, .08)):
            self.assertAlmostEqual(joint_reference(t, 2, settings), 2 + delta)
        settings["position_cycle_period_s"] = .6
        epsilon = 1e-7
        speed = (joint_reference(.02 + epsilon, 0, settings)
                 - joint_reference(.02, 0, settings)) / epsilon
        self.assertLess(abs(speed), 1e-6)
        with self.assertRaises(ValueError):
            joint_reference(.1, 0, dict(position_cycle_period_s=0))

    def test_cosine_average_and_half_period_symmetry(self):
        settings = dict(position_start_s=0, position_step_rad=.04,
                        position_cycle_period_s=.6)
        # A half-period pair sums to A, independently of phase.
        for t in (.01, .07, .2):
            self.assertAlmostEqual(joint_reference(t, 0, settings)
                                   + joint_reference(t + .3, 0, settings), .04)


@unittest.skipUnless(importlib.util.find_spec("motulator"), "optional motulator")
class ActualPlantIsolation(unittest.TestCase):
    def drive(self, energy=True):
        from oeal.backends.motulator import make_drive
        from oeal.studies import MOTOR

        actual = dict(MOTOR, stator_resistance_ohm=.36, d_inductance_h=.00064,
                      q_inductance_h=.00064, flux_linkage_wb=.027)
        return make_drive(dict(
            period_s=50e-6, duration_s=.001, step_time_s=0, bus_v=48, pwm=False,
            motor_parameters=actual, energy_consistent=energy, thermal_feedback=True,
            controller_parameters=dict(stator_resistance_ohm=.3, d_inductance_h=.0008,
                                       q_inductance_h=.0008, flux_linkage_wb=.03),
        ))

    def test_real_plant_torque_and_nominal_torque_constant_are_distinct(self):
        drive, controller = self.drive()
        drive.machine.state.psi_s_dq = .027 + .00064 * 2j
        drive.set_outputs(0)
        self.assertAlmostEqual(drive.machine.out.tau_M, .567)
        self.assertAlmostEqual(1.5 * controller.nominal.n_p * controller.nominal.psi_f * 2,
                               .63)
        self.assertAlmostEqual(controller.nominal.R_s, .3)
        self.assertAlmostEqual(drive.machine.par.R_s, .36)
        self.assertAlmostEqual(controller.nominal.L_q, .0008)
        self.assertAlmostEqual(drive.machine.par.L_q, .00064)

    def test_continuous_temperature_feedback_updates_only_actual_resistance(self):
        drive, controller = self.drive()
        drive.oeal_energy.state.winding_c = 35
        drive.set_outputs(0)
        self.assertAlmostEqual(drive.machine.par.R_s, .36 * (1 + .00393 * 10))
        self.assertAlmostEqual(controller.nominal.R_s, .3)

    def test_legacy_sampled_heat_feedback_does_not_replace_plant_with_nominal_r(self):
        drive, controller = self.drive(energy=False)
        drive.machine.state.psi_s_dq = .027 + .00064 * 2j
        drive.set_outputs(0)
        controller(drive)
        expected = .36 * (1 + .00393 * (controller.thermal.temperatures[0] - 25))
        self.assertTrue(math.isclose(drive.machine.par.R_s, expected, abs_tol=1e-14))
        self.assertAlmostEqual(controller.nominal.R_s, .3)
