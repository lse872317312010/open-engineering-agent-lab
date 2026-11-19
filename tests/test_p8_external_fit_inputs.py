"""Check input pairing and symmetry-aware split checks for external fitting."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location(
    "p8_fit_external", Path(__file__).parents[1] / "benchmarks/p8_fit_external.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ExternalFitInputTest(unittest.TestCase):
    def test_loads_complex_paired_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "map.npz"
            current = np.array([0j, 1j, 1 + 1j, 2 + 1j])
            flux = current * 0.1 + 0.2
            np.savez(path, i_s_dq=current, psi_s_dq=flux)
            loaded_current, loaded_flux = module.load_points(path)
            np.testing.assert_array_equal(loaded_current, current)
            np.testing.assert_array_equal(loaded_flux, flux)

    def test_rejects_q_reflection_across_splits(self):
        train = (np.array([1 + 2j]), np.array([0.1 + 0.2j]))
        validation = (np.array([1 - 2j]), np.array([0.3 + 0.4j]))
        with self.assertRaises(ValueError):
            module.check_exact_separation(train, validation)
        validation = (np.array([2 + 3j]), np.array([0.1 - 0.2j]))
        with self.assertRaises(ValueError):
            module.check_exact_separation(train, validation)

    def test_rejects_invalid_nominal(self):
        for value in (0, -1, float("nan"), True, "3"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.positive_number({"current_a": value}, "current_a")

    def test_source_manifest_and_cross_split_compatibility(self):
        metadata = {"source_software": "example", "source_version": "1",
                    "model_id": "motor", "phase_sequence": "abc", "domain": "points",
                    "dq_convention": "motulator_peak_d_plus_jq", "pole_pairs": 2,
                    "temperature_c": None, "temperature_note": "not supplied"}
        manifest = {"format": "oeal-magnetic-points-v1", "metadata": metadata,
                    "source_csv_sha256": "a" * 64, "metadata_sha256": "b" * 64}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "map.npz"
            np.savez(path, manifest_json=np.asarray(json.dumps(manifest)))
            loaded = module.load_source_manifest(path)
            module.check_source_compatibility(loaded, loaded, 2)
            with self.assertRaises(ValueError):
                module.check_source_compatibility(loaded, loaded, 3)
            other = json.loads(json.dumps(loaded))
            other["metadata"]["phase_sequence"] = "acb"
            with self.assertRaises(ValueError):
                module.check_source_compatibility(loaded, other, 2)
            metadata.pop("temperature_note")
            np.savez(path, manifest_json=np.asarray(json.dumps(manifest)))
            with self.assertRaises(ValueError):
                module.load_source_manifest(path)
