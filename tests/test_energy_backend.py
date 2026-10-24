"""Independent power-port checks on the real optional upstream subsystem."""

import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec("motulator"), "optional motulator")
class EnergyBackendTests(unittest.TestCase):
    def drive(self):
        from oeal.backends.motulator import make_drive

        return make_drive({
            "energy_consistent": True, "period_s": 50e-6, "bus_v": 48,
            "dc_bus": "capacitor", "duration_s": 0.02, "step_time_s": 0.005,
            "pwm": False,
        })[0]

    def test_actual_capacitor_rhs_includes_the_extra_dc_load(self):
        drive = self.drive()
        drive.machine.state.psi_s_dq = 0.03 + 0.0008 * 2j
        drive.set_outputs(0)
        # q=0 gives zero ideal bridge current. |i|=2 A produces
        # 1.5*.02*4 + 6*20e-6/50e-6*2 = 4.92 W in the added DC branch.
        self.assertAlmostEqual(drive.oeal_energy.bridge_current(drive.converter.inp), 0)
        self.assertAlmostEqual(drive.dc_bus.rhs(0)[0], -4.92 / (48 * 0.002), places=9)
        self.assertAlmostEqual(
            drive.converter.compute_internal_dc_current(drive.converter.inp), 4.92 / 48
        )

    def test_viscous_coast_uses_the_same_heat_removed_from_rotor(self):
        drive = self.drive()
        drive.mechanics.J = 0.5
        drive.mechanics.B_L = 0.2
        drive.mechanics.state.w_M = 10
        drive.set_outputs(0)
        drive.mechanics.inp.tau_M = 0
        drive.mechanics.set_external_load_torque(0)
        acceleration = drive.mechanics.rhs(0)[1]
        self.assertAlmostEqual(acceleration, -4)
        powers, _, heat = drive.oeal_energy.powers(0)
        self.assertAlmostEqual(powers["rotor_friction_w"], 20)
        self.assertAlmostEqual(heat[2], 20)
        self.assertAlmostEqual(0.5 * 10 * acceleration + heat[2], 0)
