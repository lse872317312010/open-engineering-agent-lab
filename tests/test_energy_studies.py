"""Reject unsupported energy combinations before optional libraries are imported."""

import copy
import json
import unittest
from pathlib import Path

from oeal.ir import validate_document

ROOT = Path(__file__).resolve().parents[1]


class EnergyStudyTests(unittest.TestCase):
    def test_energy_capabilities_are_explicit_and_budget_is_still_protected(self):
        path = ROOT / "examples/studies/motulator_pmsm_v1.json"
        base = json.loads(path.read_text())
        base["settings"]["energy_consistent"] = True
        validate_document(base)
        for key, value in (("core_conductance_s", {"value": 0.01, "unit": "S"}),
                           ("dc_bus", "diode")):
            altered = copy.deepcopy(base)
            altered["settings"][key] = value
            with self.assertRaises(ValueError):
                validate_document(altered)
        altered = copy.deepcopy(base)
        altered["model"]["profile"] = "baldor_map_v1"
        with self.assertRaises(ValueError):
            validate_document(altered)
        altered = copy.deepcopy(base)
        altered["budget"]["control_ticks"] = 1
        with self.assertRaises(ValueError):
            validate_document(altered)
        altered = copy.deepcopy(base)
        altered["settings"]["energy_consistent"] = False
        altered["acceptance"]["energy_balance_abs_j"] = {"value": 1e-3, "unit": "J"}
        with self.assertRaises(ValueError):
            validate_document(altered)
