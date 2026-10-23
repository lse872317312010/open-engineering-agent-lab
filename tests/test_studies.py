"""Version compatibility, unit/clock contracts and trusted independent verification."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from jsonschema import ValidationError

from oeal.experiments import run_experiment
from oeal.foc import FOCConfig, simulate_foc
from oeal.ir import document_hash, validate_document
from oeal.models import MotorParameters
from oeal.studies import FOC_FIELDS, MOTOR, recompute, resolve_assets, resolved_settings
from oeal.study_tools import StudyTools

ROOT = Path(__file__).resolve().parents[1]


def example(name="native_foc_v1"):
    return json.loads((ROOT / "examples/studies" / (name + ".json")).read_text())


class StudyTests(unittest.TestCase):
    def test_native_result_matches_direct_plant_and_is_reproducible(self):
        spec = example()
        result = run_experiment(spec)
        again = run_experiment(spec)
        self.assertEqual(result["raw_sha256"], again["raw_sha256"])
        s = resolved_settings(spec)
        direct = simulate_foc(
            MotorParameters(**MOTOR), FOCConfig(**{k: s[k] for k in FOC_FIELDS})
        ).samples
        np.testing.assert_allclose(result["streams"]["control"]["samples"], direct,
                                   rtol=0, atol=1e-12)
        self.assertEqual(result["streams"]["control"]["units"][1:3], ["A", "A"])
        self.assertEqual(result["experiment_sha256"], document_hash(spec))

    def test_invalid_units_capabilities_budget_and_macro_rejected(self):
        for path, value in (
            (("settings", "duration_s", "unit"), "ms"),
            (("backend",), "motulator"),
            (("budget", "control_ticks"), 2),
            (("settings", "pwm"), True),
        ):
            spec = example()
            target = spec
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.assertRaises((ValueError, ValidationError)):
                validate_document(spec)
        spec = example("ur5e_joint_v1")
        spec["settings"]["macro_step_s"] = {"value": 0.00013, "unit": "s"}
        with self.assertRaises(ValueError):
            validate_document(spec)
        spec = example()
        spec["model"]["import"] = "os"
        with self.assertRaises(ValidationError):
            validate_document(spec)

    def test_result_shape_time_and_units_rejected(self):
        result = run_experiment(example())
        for change in ("time", "unit", "shape", "hash"):
            altered = copy.deepcopy(result)
            if change == "time":
                altered["streams"]["control"]["samples"][1][0] = 0
                altered["raw_sha256"] = document_hash(altered["streams"])
            elif change == "unit":
                altered["streams"]["control"]["units"][1] = "V"
                altered["raw_sha256"] = document_hash(altered["streams"])
            elif change == "shape":
                altered["streams"]["control"]["samples"][1].pop()
                altered["raw_sha256"] = document_hash(altered["streams"])
            else:
                altered["streams"]["control"]["samples"][1][1] += 1
            with self.assertRaises(ValueError):
                validate_document(altered)

    def test_assets_are_checked_before_optional_backend_import(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baldor_400rpm_map.npz"
            path.write_bytes(b"not the registered asset")
            with self.assertRaisesRegex(ValueError, "asset hash mismatch"):
                resolve_assets("baldor_map_v1", directory)

    def test_agent_rejects_goal_changes_and_recomputes_from_attested_raw_data(self):
        with tempfile.TemporaryDirectory() as directory:
            tools = StudyTools(example(), directory)
            candidate = tools.propose_change({"bandwidth_per_s": 1500})
            result = tools.run_experiment(candidate)
            verification = tools.verify_change(candidate, result)
            spoof = copy.deepcopy(result)
            spoof["metrics"] = {"current_tail_error_a": -999}
            spoof["goal_passed"] = not result["goal_passed"]
            self.assertEqual(tools.verify_change(candidate, spoof), verification)
            changed = copy.deepcopy(candidate)
            changed["acceptance"]["current_tail_error_a"]["value"] = 999
            with self.assertRaises(ValueError):
                tools.run_experiment(changed)
            altered = copy.deepcopy(result)
            altered["streams"]["control"]["samples"][2][1] += 1
            altered["raw_sha256"] = document_hash(altered["streams"])
            with self.assertRaises(ValueError):
                tools.verify_change(candidate, altered)
            with self.assertRaises(ValueError):
                tools.propose_change({"duration_s": 1})
            with self.assertRaises(ValueError):
                tools.propose_change({"bandwidth_per_s": 99999})

    def test_switching_peak_and_robot_tuning_scope_are_protected(self):
        spec = example()
        result = run_experiment(spec)
        result["streams"]["waveforms"] = {
            "columns": ["time_s", "id_a", "iq_a"], "units": ["s", "A", "A"],
            "samples": [[0, 0, 0], [0.010001, 0, 25]],
            "sample_semantics": "solver_samples",
        }
        spec["acceptance"]["current_peak_a"] = {"value": 20, "unit": "A"}
        metrics, numeric, passed = recompute(spec, result)
        self.assertTrue(numeric)
        self.assertEqual(metrics["current_peak_a"], 25)
        self.assertFalse(passed)
        with tempfile.TemporaryDirectory() as directory:
            tools = StudyTools(example("ur5e_joint_v1"), directory)
            with self.assertRaises(ValueError):
                tools.propose_change({"bandwidth_per_s": 2000})
            with self.assertRaises(ValueError):
                tools.propose_change({"current_limit_a": 30})
            candidate = tools.propose_change({"outer_kp_nm_per_rad": 300})
            self.assertEqual(candidate["settings"]["outer_kp_nm_per_rad"]["value"], 300)
