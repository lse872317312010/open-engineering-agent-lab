"""Verify user-labelled magnetic splits and traceability."""
import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

BENCHMARKS = Path(__file__).parents[1] / "benchmarks"
sys.path.insert(0, str(BENCHMARKS))
spec = importlib.util.spec_from_file_location("p8_split_points", BENCHMARKS / "p8_split_points.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MagneticSplitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.csv"
        self.meta = self.root / "meta.json"
        self.out = self.root / "split"
        self.meta.write_text(json.dumps(dict(
            source_software="example", source_version="1", model_id="demo", pole_pairs=2,
            temperature_c=None, temperature_note="not supplied",
            dq_convention="motulator_peak_d_plus_jq", phase_sequence="abc", domain="example",
        )))
        with self.source.open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["id_A", "iq_A", "psi_d_Wb", "psi_q_Wb", "split"])
            for role_index, role in enumerate(("train", "validation", "holdout")):
                for number in range(4):
                    writer.writerow([role_index * 10 + number, 1, role_index + number / 10, 0.1,
                                     role])

    def test_split_retains_identity_and_rows(self):
        module.split_points(self.source, self.meta, self.out)
        manifest = json.loads((self.out / "split-manifest.json").read_text())
        self.assertEqual(manifest["counts"], {"train": 4, "validation": 4, "holdout": 4})
        for role in module.ROLES:
            with np.load(self.out / f"{role}.npz", allow_pickle=False) as data:
                self.assertEqual(len(data["i_s_dq"]), 4)
        with self.assertRaises(ValueError):
            module.split_points(self.source, self.meta, self.out)

    def test_rejects_reflected_input_without_publishing_partial_bundle(self):
        with self.source.open() as stream:
            rows = list(csv.reader(stream))
        rows[5][0], rows[5][1] = rows[1][0], "-1"
        with self.source.open("w", newline="") as stream:
            csv.writer(stream).writerows(rows)
        with self.assertRaises(ValueError):
            module.split_points(self.source, self.meta, self.out)
        self.assertFalse(self.out.exists())

    def test_source_torque_is_retained_in_every_split(self):
        with self.source.open() as stream:
            rows = list(csv.reader(stream))
        rows[0].append("torque_Nm")
        for index, row in enumerate(rows[1:], start=1):
            row.append(str(index))
        with self.source.open("w", newline="") as stream:
            csv.writer(stream).writerows(rows)
        with self.assertRaises(ValueError):
            module.split_points(self.source, self.meta, self.out)
        self.assertFalse(self.out.exists())
        metadata = json.loads(self.meta.read_text())
        metadata["torque_convention"] = "electromagnetic_total_Nm"
        self.meta.write_text(json.dumps(metadata))
        module.split_points(self.source, self.meta, self.out)
        for index, role in enumerate(module.ROLES):
            with np.load(self.out / f"{role}.npz", allow_pickle=False) as data:
                expected = np.arange(index * 4 + 1, index * 4 + 5)
                np.testing.assert_array_equal(data["torque_total_nm"], expected)
        manifest = json.loads((self.out / "split-manifest.json").read_text())
        self.assertTrue(manifest["source_torque_included"])
