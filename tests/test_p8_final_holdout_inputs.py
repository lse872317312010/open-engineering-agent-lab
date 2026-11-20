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
            _, _, (train, _), (current, _), holdout_manifest = module.verify_inputs(folder, *paths)
            np.testing.assert_array_equal(train, np.arange(4) + 1j)
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


@unittest.skipUnless(importlib.util.find_spec("scipy"), "optional SciPy")
class TrainingCoverageTest(unittest.TestCase):
    def test_affine_interpolation_compares_only_supported_points(self):
        train = np.array([0j, 1 + 0j, 1j, 1 + 1j])
        holdout = np.array([0.25 + 0.25j, 0.5 + 0j, 2 + 0.25j])
        target = 2 * holdout + 1j
        predicted = target + np.array([1, 1, 4])
        result, labels, linear = module.compare_training_coverage(
            train, 2 * train + 1j, holdout, target, predicted, 2.0
        )
        np.testing.assert_array_equal(labels, ["inside", "inside", "outside"])
        np.testing.assert_allclose(linear[:2], target[:2])
        self.assertTrue(np.isnan(linear[2]))
        self.assertEqual(result["coverage"]["outside"]["gradnet_errors"]["rmse_pu"], 2.0)
        comparison = result["linear_comparison"]
        self.assertEqual(comparison["points"], 2)
        self.assertEqual(comparison["gradnet_same_points"]["mae"], 1.0)
        self.assertEqual(comparison["linear_errors"]["rmse"], 0.0)

    def test_degenerate_geometry_and_conflicting_samples_are_reported(self):
        holdout = np.array([0.25 + 0.25j])
        collinear = np.arange(4, dtype=complex)
        result, labels, linear = module.compare_training_coverage(
            collinear, collinear, holdout, holdout, holdout, 1.0
        )
        np.testing.assert_array_equal(labels, ["unavailable"])
        self.assertTrue(np.isnan(linear).all())
        self.assertEqual(result["coverage"]["unavailable"]["points"], 1)
        self.assertEqual(result["linear_comparison"]["points"], 0)

        train = np.array([0j, 1 + 0j, 1j, 1 + 1j, 0j])
        target = train.copy()
        target[-1] = 10
        result, labels, linear = module.compare_training_coverage(
            train, target, holdout, holdout, holdout, 1.0
        )
        np.testing.assert_array_equal(labels, ["inside"])
        self.assertTrue(np.isnan(linear).all())
        self.assertEqual(result["linear_comparison"]["unavailable_reason"],
                         "conflicting_targets_at_duplicate_training_inputs")
