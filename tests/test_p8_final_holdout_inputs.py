"""Verify final holdout file identity and separation checks."""
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
    "p8_evaluate_final_holdout", BENCHMARKS / "p8_evaluate_final_holdout.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FinalHoldoutTest(unittest.TestCase):
    def test_fit_identity_and_reflected_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            paths = []
            for offset in (0, 10, 20):
                path = folder / f"points-{offset}.npz"
                current = np.arange(offset, offset + 4) + 1j
                flux = (np.arange(offset, offset + 4) / 10 + 0.1) + 0.2j
                np.savez(path, i_s_dq=current, psi_s_dq=flux)
                paths.append(path)
            hashes = {}
            for name in ("flux", "current"):
                path = folder / (name + "-model.npz")
                path.write_bytes(name.encode())
                hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            fit = {"input_sha256": {"train": module.digest(paths[0]),
                                    "validation": module.digest(paths[1])},
                   "model_sha256": hashes}
            (folder / "summary.json").write_text(json.dumps(fit))
            _, _, (current, _) = module.verify_inputs(folder, *paths)
            self.assertEqual(len(current), 4)
            with np.load(paths[2], allow_pickle=False) as data:
                flux = data["psi_s_dq"].copy()
            np.savez(paths[2], i_s_dq=np.arange(4) - 1j, psi_s_dq=flux)
            with self.assertRaises(ValueError):
                module.verify_inputs(folder, *paths)
            (folder / "flux-model.npz").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                module.verify_inputs(folder, *paths)
