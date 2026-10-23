import math
from dataclasses import replace
from unittest import TestCase

import numpy as np

from oeal.foc import FOCConfig
from oeal.models import MotorParameters
from oeal.multiphysics import (
    InverterParameters,
    JointParameters,
    ThermalParameters,
    joint_energy,
    joint_rhs,
    run_joint,
    thermal_rhs,
)


class MultiPhysicsTests(TestCase):
    def setUp(self):
        self.motor = MotorParameters(0.3, 0.0008, 0.0008, 0.03, 7, 0.002, 0.0)

    def test_mechanical_power_balance_and_dissipation(self):
        p = JointParameters(
            damping_nms=0.0, motor_coulomb_nm=0.0,
            load_coulomb_nm=0.0, load_viscous_nms=0.0,
        )
        x = np.array([0.4, 2.0, 0.01, -0.1])
        derivative = joint_rhs(x, self.motor, p, 0.0, 0.0)
        epsilon = 1e-7
        gradient = np.array([
            (joint_energy(x + np.eye(4)[i] * epsilon, self.motor, p)
             - joint_energy(x - np.eye(4)[i] * epsilon, self.motor, p)) / (2 * epsilon)
            for i in range(4)
        ])
        self.assertAlmostEqual(float(gradient @ derivative), 0.0, delta=1e-7)
        dissipative = replace(p, damping_nms=0.3, motor_coulomb_nm=0.01)
        self.assertLess(float(gradient @ joint_rhs(x, self.motor, dissipative, 0, 0)), 0)

    def test_thermal_equilibrium_and_energy_balance(self):
        p = ThermalParameters()
        np.testing.assert_allclose(thermal_rhs(np.full(3, 25.0), p, 0, 0, 0), 0)
        temperatures = np.array([50.0, 35.0, 60.0])
        derivative = thermal_rhs(temperatures, p, 10.0, 5.0, 2.0)
        storage = derivative @ np.array([p.winding_j_per_k, p.case_j_per_k, p.board_j_per_k])
        ambient_loss = (35 - 25) / p.case_ambient_k_per_w + (60 - 25) / p.board_ambient_k_per_w
        self.assertAlmostEqual(storage, 17.0 - ambient_loss, delta=1e-12)

    def test_coupled_halving_and_latched_command_stop(self):
        control = FOCConfig(duration_s=0.004, integration_step_s=1e-5)
        coarse = run_joint(self.motor, control)["samples"]
        fine = run_joint(self.motor, replace(control, integration_step_s=5e-6))["samples"]
        np.testing.assert_allclose(coarse[:, :10], fine[:, :10], atol=2e-4, rtol=0)
        stopped = run_joint(
            self.motor, control, initial_temperature_c=(130, 25, 25)
        )["samples"]
        self.assertTrue(np.all(stopped[:, -1] == 1))
        self.assertTrue(np.all(stopped[:, -2] == 0))

    def test_parameter_ranges_and_nonfinite(self):
        for constructor, changes in (
            (JointParameters, {"ratio": 0}),
            (JointParameters, {"transmission_error_rad": 0.5}),
            (ThermalParameters, {"winding_j_per_k": -1}),
            (ThermalParameters, {"ambient_c": math.nan}),
            (InverterParameters, {"ripple_fraction": 0.8}),
            (InverterParameters, {"deadtime_s": -1}),
        ):
            with self.assertRaises(ValueError):
                constructor(**changes)
