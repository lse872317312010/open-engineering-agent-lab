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
