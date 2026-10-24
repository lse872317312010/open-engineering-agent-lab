"""Validate fixed coupling capabilities and the real MuJoCo inertia port."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from jsonschema import ValidationError

from oeal.ir import validate_document

ROOT = Path(__file__).resolve().parents[1]


class CouplingCapabilityTests(unittest.TestCase):
    def test_midpoint_scope_is_explicit_and_unsupported_combinations_rejected(self):
        spec = json.loads((ROOT / "examples/studies/ur5e_joint_v1.json").read_text())
        spec["settings"].update(energy_consistent=True, coupling_method="midpoint_predictor",
                                robot_integrator="rk4")
        validate_document(spec)
        for key, value in (("energy_consistent", False), ("robot_integrator", "implicitfast"),
                           ("fixture", True), ("backlash_rad", {"value": 0.001, "unit": "rad"}),
                           ("coupling_method", "unregistered")):
            changed = copy.deepcopy(spec)
            changed["settings"][key] = value
            with self.assertRaises((ValueError, ValidationError)):
                validate_document(changed)


@unittest.skipUnless(importlib.util.find_spec("mujoco"), "optional MuJoCo")
class CouplingInertiaTests(unittest.TestCase):
    def model(self):
        import mujoco

        xml = """<mujoco><option gravity="0 0 0" integrator="RK4"/>
        <worldbody><body><joint name="shoulder_lift_joint" axis="0 0 1"/>
        <geom type="capsule" fromto="0 0 0 1 0 0" size=".05" mass="2"
              contype="0" conaffinity="0"/>
        <body pos="1 0 0"><joint name="second" axis="0 0 1"/>
        <geom type="capsule" fromto="0 0 0 .8 0 0" size=".05" mass="1"
              contype="0" conaffinity="0"/></body></body></worldbody></mujoco>"""
        model = mujoco.MjModel.from_xml_string(xml)
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        return model, data

    def setup_port(self):
        from oeal.backends.robot import RobotLoad

        model, data = self.model()
        config = {"macro_step_s": 0.0002, "period_s": 50e-6,
                  "energy_consistent": True, "coupling_method": "midpoint_predictor"}
        robot = RobotLoad(model, data, config)
        drive = SimpleNamespace(
            mechanics=SimpleNamespace(J=0.001, B_L=0.02,
                                      out=SimpleNamespace(w_M=1.0),
                                      set_external_load_torque=lambda torque: None),
            machine=SimpleNamespace(out=SimpleNamespace(tau_M=0.1)),
        )
        controller = SimpleNamespace(t=0.0, tick=0, theta_continuous=1.0,
                                     nominal=SimpleNamespace(n_p=7, psi_f=0.03))
        return model, data, robot, drive, controller

    def test_full_inverse_inertia_matches_independent_forward_force_difference(self):
        import mujoco

        model, data, robot, drive, controller = self.setup_port()
        robot.predict_exchange(controller, drive, 0.02, 0.1)
        measured_gain = 1 / robot.coupling_rows[-1][5]
        initial_acceleration = float(data.qacc[robot.index])
        data.qfrc_applied[robot.index] = 1
        mujoco.mj_forward(model, data)
        self.assertAlmostEqual(measured_gain, data.qacc[robot.index] - initial_acceleration)
        mass = np.zeros((model.nv, model.nv))
        mujoco.mj_fullM(model, mass, data.qM)
        self.assertGreater(abs(measured_gain - 1 / mass[robot.index, robot.index]), 1e-3)

    def test_reported_spring_storage_uses_actual_endpoint_not_prediction(self):
        _, _, robot, drive, controller = self.setup_port()
        robot.sample(controller, drive)
        actual = 0.5 * 500 * 0.02 ** 2
        self.assertAlmostEqual(robot.rows[-1][10], actual)
        self.assertAlmostEqual(robot.energy_rows[-1][5], actual)
        predicted = 0.5 * 500 * robot.coupling_rows[-1][6] ** 2
        self.assertNotAlmostEqual(predicted, actual, places=10)
