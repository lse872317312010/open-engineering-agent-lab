"""IR boundaries and independently protected cyclic targets."""

import copy
import json
import unittest
from pathlib import Path

from jsonschema import ValidationError

from oeal.ir import document_hash
from oeal.studies import recompute, validate_study

ROOT = Path(__file__).resolve().parents[1]


class CyclicCapabilities(unittest.TestCase):
    def spec(self):
        s = json.loads((ROOT / "examples/studies/ur5e-midpoint.json").read_text())
        s["settings"]["position_cycle_period_s"] = {"value": .1, "unit": "s"}
        s["acceptance"]["position_peak_error_rad"] = {"value": .03, "unit": "rad"}
        s["controller_parameters"] = {"stator_resistance_ohm": {"value": .3, "unit": "ohm"}}
        return s

    def test_explicit_ir_scope_and_units(self):
        s = self.spec()
        validate_study(s)
        for mutate in (
            lambda d: d["controller_parameters"].update(pole_pairs={"value": 7, "unit": "1"}),
            lambda d: d["controller_parameters"]["stator_resistance_ohm"].update(unit="H"),
            lambda d: d["acceptance"].pop("position_peak_error_rad"),
            lambda d: d["settings"]["position_cycle_period_s"].update(value=1e-5),
        ):
            changed = copy.deepcopy(s)
            mutate(changed)
            with self.assertRaises((ValueError, ValidationError)):
                validate_study(changed)
        changed = copy.deepcopy(s)
        changed["model"]["profile"] = "baldor_map_v1"
        changed["backend"] = "motulator"
        with self.assertRaises(ValueError):
            validate_study(changed)

    def test_rehashed_linear_ramp_cannot_impersonate_a_cycle(self):
        # A minimum real-clock-shaped stream; recompute must reject the wrong target
        # before it needs optional backend data, nominal metadata or energy balances.
        s = self.spec()
        s["settings"].update(duration_s={"value": .001, "unit": "s"},
                             position_start_s={"value": 0, "unit": "s"})
        s["settings"].pop("energy_consistent")
        s["settings"]["coupling_method"] = "jacobi"
        rows = [[i * .0002, 0, .08 * (i * .0002 / .12), 0] for i in range(6)]
        result = dict(primary_stream="joint", context={}, streams={
            "joint": dict(columns=["time_s", "joint_angle_rad", "reference_rad",
                                  "shaft_torque_nm"], samples=rows),
            "control": dict(columns=["time_s", "id_a", "iq_a"],
                            samples=[[i * .00005, 0, 0] for i in range(21)]),
        })
        result["raw_sha256"] = document_hash(result["streams"])
        with self.assertRaisesRegex(ValueError, "protected target"):
            recompute(s, result)


if __name__ == "__main__":
    unittest.main()
