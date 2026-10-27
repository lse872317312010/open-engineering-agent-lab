"""Trusted thermal provider boundaries on the real optional upstream drive."""

import importlib.util
import unittest

import numpy as np


@unittest.skipUnless(importlib.util.find_spec("motulator"), "optional motulator")
class ThermalProviderTests(unittest.TestCase):
    def drive(self, provider):
        from oeal.backends.motulator import make_drive

        drive, _ = make_drive(dict(energy_consistent=True, period_s=50e-6, bus_v=48,
                                   duration_s=.01, step_time_s=.005, pwm=False),
                              thermal_provider=provider)
        drive.machine.state.psi_s_dq = .03+.0008*2j
        drive.set_outputs(0.)
        return drive

    def test_actual_port_heat_is_sent_to_provider_in_same_rhs(self):
        class Provider:
            # Existing FMI providers use state_names for compiler metadata, not host states.
            state_names = ("legacy_compiled_state",)

            def evaluate(self, t, temperatures, heat, input_j, ambient_j, **_):
                np.testing.assert_array_equal(temperatures, [25.]*6)
                assert t == .001 and input_j == ambient_j == 0.
                np.testing.assert_allclose(heat, [1.8, 0., 0., 4.92, 0., 0.], atol=1e-12)
                return np.r_[heat/np.array([60.,70.,200.,.5,25.,100.]), sum(heat), 0.]

        drive = self.drive(Provider())
        rates = drive.oeal_energy.rhs(.001)
        self.assertAlmostEqual(rates[0], .03)
        self.assertAlmostEqual(rates[3], 9.84)

    def test_malformed_or_missing_input_power_cannot_enter_integrator(self):
        class Provider:
            def __init__(self, result):
                self.result = result

            def evaluate(self, *_args, **_kwargs):
                return self.result

        for result in ([0.]*7, [float("nan")]*8, [0.]*8):
            drive = self.drive(Provider(result))
            with self.assertRaises(ValueError):
                drive.oeal_energy.rhs(0.)

    def test_nonenergy_provider_is_rejected_before_drive_construction(self):
        from oeal.backends.motulator import make_drive

        with self.assertRaises(ValueError):
            make_drive({}, thermal_provider=object())

    def test_branch_integrals_are_solver_states_with_hot_initial_storage(self):
        class Provider:
            energy_state_names = ("case_out_j", "convection_out_j", "radiation_out_j")
            initial_temperatures_c = (80.,)*6

            def evaluate(self, _t, temperatures, heat, input_j, ambient_j, *,
                         branch_energy_j, **_):
                np.testing.assert_array_equal(temperatures, [80.]*6)
                assert input_j == ambient_j == sum(branch_energy_j) == 0.
                rate = np.array(heat)/np.array([60.,70.,200.,.5,25.,100.])
                rate[2] -= 1/200
                rate[5] -= 5/100
                return np.r_[rate, sum(heat), 6., 1., 2., 3.]

        drive = self.drive(Provider())
        energy = drive.oeal_energy
        self.assertGreater(energy.initial_storage["thermal_j"], 0)
        rates = energy.rhs(.001)
        np.testing.assert_array_equal(rates[-3:], [1., 2., 3.])
        self.assertEqual(len(rates), len(vars(energy.state)))
        from oeal.energy import ENERGY_COLUMNS
        row = energy.snapshot(0.)
        self.assertAlmostEqual(row[ENERGY_COLUMNS.index("thermal_residual_j")], 0.)

    def test_branch_power_and_state_sum_mismatches_are_rejected(self):
        class Provider:
            energy_state_names = ("case_out_j", "convection_out_j", "radiation_out_j")

            def evaluate(self, _t, temperatures, heat, *_args, **_kwargs):
                return np.r_[np.array(heat)/np.array([60.,70.,200.,.5,25.,100.]),
                             sum(heat), 0., 1., 0., 0.]

        drive = self.drive(Provider())
        with self.assertRaisesRegex(ValueError, "branch powers"):
            drive.oeal_energy.rhs(0.)
        drive.oeal_energy.state.case_out_j = 1.
        with self.assertRaisesRegex(ValueError, "branch state sum"):
            drive.oeal_energy.rhs(0.)
