"""Check external drive's model identity, validation budget and domain inputs."""
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

BENCHMARKS = Path(__file__).parents[1] / "benchmarks"
sys.path.insert(0, str(BENCHMARKS))
spec = importlib.util.spec_from_file_location(
    "p8_run_external_drive", BENCHMARKS / "p8_run_external_drive.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ExternalDriveInputsTest(unittest.TestCase):
    def test_fit_hash_and_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            hashes = {}
            for name in ("flux", "current"):
                path = folder / f"{name}-model.npz"
                path.write_bytes(name.encode())
                hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            summary = {"model_sha256": hashes, "nominal": {"pole_pairs": 2},
                       "results": {"validation": {"flux_error_wb": {"rmse": 0.1},
                                                  "current_error_a": {"rmse": 0.2}}}}
            (folder / "summary.json").write_text(json.dumps(summary))
            cfg = {"max_validation_flux_rmse_wb": 0.1, "max_validation_current_rmse_a": 0.2}
            self.assertEqual(module.validate_fit(folder, cfg)[2], 2)
            cfg["max_validation_flux_rmse_wb"] = 0.09
            with self.assertRaises(ValueError):
                module.validate_fit(folder, cfg)
            cfg["max_validation_flux_rmse_wb"] = 0.1
            (folder / "flux-model.npz").write_bytes(b"modified")
            with self.assertRaises(ValueError):
                module.validate_fit(folder, cfg)

    def test_rectangle_and_invalid_bounds(self):
        limits = module.bounds({"domain": [-1, 2, -3, 4]}, "domain")
        allowed = module.rectangle(limits)(np.array([0j, 2 + 4j, 3 + 0j]))
        np.testing.assert_array_equal(allowed, [True, True, False])
        with self.assertRaises(ValueError):
            module.bounds({"domain": [0, 0, -1, 1]}, "domain")

    def test_final_evidence_identity_and_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            fit = {"input_sha256": {"train": "train-sha", "validation": "validation-sha"},
                   "model_sha256": {"flux": "flux-sha", "current": "current-sha"}}
            (folder / "summary.json").write_text(json.dumps(fit))
            holdout, budget, evidence = (folder / name for name in (
                "holdout.npz", "budget.json", "final.json"
            ))
            holdout.write_bytes(b"holdout")
            limits = {"flux_rmse_wb": 1.0, "flux_max_wb": 2.0,
                      "current_rmse_a": 3.0, "current_max_a": 4.0}
            budget.write_text(json.dumps(limits))
            report = {"passed": True, "points": 4,
                      "fit_summary_sha256": module.sha(folder / "summary.json"),
                      "model_sha256": fit["model_sha256"],
                      "input_sha256": {"train": "train-sha", "validation": "validation-sha",
                                       "holdout": module.sha(holdout), "budget": module.sha(budget)},
                      "errors": {"flux_wb": {"rmse": 0.1, "max": 0.2},
                                 "current_a": {"rmse": 0.3, "max": 0.4}},
                      "budgets": limits, "checks": {key: True for key in limits}}
            evidence.write_text(json.dumps(report))
            self.assertTrue(module.validate_final_evidence(folder, fit, holdout, budget, evidence))
            report["errors"]["current_a"]["max"] = 8.0
            evidence.write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                module.validate_final_evidence(folder, fit, holdout, budget, evidence)
            holdout.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                module.validate_final_evidence(folder, fit, holdout, budget, evidence)
