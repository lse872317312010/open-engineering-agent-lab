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
