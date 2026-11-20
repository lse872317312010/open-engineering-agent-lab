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
            metadata = {"source_software": "example", "source_version": "1",
                        "model_id": "motor", "pole_pairs": 2, "temperature_c": None,
                        "temperature_note": "not supplied", "phase_sequence": "abc",
                        "dq_convention": "motulator_peak_d_plus_jq", "domain": "points"}
            manifest = {"format": "oeal-magnetic-points-v1", "metadata": metadata,
                        "source_csv_sha256": "a" * 64, "metadata_sha256": "b" * 64}
            paths = []
            for offset in (0, 10, 20):
                path = folder / f"points-{offset}.npz"
                current = np.arange(offset, offset + 4) + 1j
                flux = (np.arange(offset, offset + 4) / 10 + 0.1) + 0.2j
                np.savez(path, i_s_dq=current, psi_s_dq=flux,
                         manifest_json=np.asarray(json.dumps(manifest)))
                paths.append(path)
            hashes = {}
            for name in ("flux", "current"):
                path = folder / (name + "-model.npz")
                path.write_bytes(name.encode())
                hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            fit = {"input_sha256": {"train": module.digest(paths[0]),
                                    "validation": module.digest(paths[1])},
                   "model_sha256": hashes, "nominal": {"pole_pairs": 2},
                   "source_manifests": {"train": manifest, "validation": manifest}}
            (folder / "summary.json").write_text(json.dumps(fit))
            _, _, (current, _), holdout_manifest = module.verify_inputs(folder, *paths)
            self.assertEqual(len(current), 4)
            self.assertEqual(holdout_manifest, manifest)
            other = json.loads(json.dumps(manifest))
            other["metadata"]["model_id"] = "wrong-motor"
            np.savez(paths[2], i_s_dq=np.arange(20, 24) + 1j,
                     psi_s_dq=np.arange(20, 24) / 10 + 0.1 + 0.2j,
                     manifest_json=np.asarray(json.dumps(other)))
            with self.assertRaisesRegex(ValueError, "incompatible source metadata: model_id"):
                module.verify_inputs(folder, *paths)
            with np.load(paths[2], allow_pickle=False) as data:
                flux = data["psi_s_dq"].copy()
            np.savez(paths[2], i_s_dq=np.arange(4) - 1j, psi_s_dq=flux,
                     manifest_json=np.asarray(json.dumps(manifest)))
            with self.assertRaisesRegex(ValueError, "overlaps across splits"):
                module.verify_inputs(folder, *paths)
            (folder / "flux-model.npz").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "flux model does not match"):
                module.verify_inputs(folder, *paths)
