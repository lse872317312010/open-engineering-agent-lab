"""Check open magnetic point interchange and invalid input."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location(
    "import_magnetic_points", Path(__file__).parents[1] / "benchmarks/import_magnetic_points.py"
)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class MagneticPointsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "map.csv"
        self.meta = self.root / "meta.json"
        self.output = self.root / "output.npz"
        self.source.write_text("id_A,iq_A,psi_d_Wb,psi_q_Wb\n-1,2,0.1,0.2\n0,3,0.3,0.4\n")
        self.meta.write_text(json.dumps(dict(
            source_software="example", source_version="1", model_id="demo", pole_pairs=2,
            temperature_c=25, dq_convention="motulator_peak_d_plus_jq",
            phase_sequence="abc", domain="two source points",
        )))

    def test_round_trip_and_provenance(self):
        adapter.convert(self.source, self.meta, self.output)
        with np.load(self.output, allow_pickle=False) as data:
            np.testing.assert_array_equal(data["i_s_dq"], [-1 + 2j, 3j])
            np.testing.assert_array_equal(data["psi_s_dq"], [0.1 + 0.2j, 0.3 + 0.4j])
            manifest = json.loads(str(data["manifest_json"]))
            self.assertEqual(manifest["source_csv_sha256"],
                             hashlib.sha256(self.source.read_bytes()).hexdigest())
            self.assertEqual(manifest["metadata_sha256"],
                             hashlib.sha256(self.meta.read_bytes()).hexdigest())
            self.assertEqual(manifest["point_count"], 2)

    def test_invalid_point_data(self):
        for rows in (
            "id_A,iq_A,psi_d_Wb,psi_q_Wb\n1,2,3,nan\n",
            "id_A,iq_A,psi_d_Wb,psi_q_Wb\n1,2,3,4\n1,2,5,6\n",
            "id_A,id_A,psi_d_Wb,psi_q_Wb\n1,2,3,4\n",
        ):
            with self.subTest(rows=rows):
                self.source.write_text(rows)
                with self.assertRaises(ValueError):
                    adapter.convert(self.source, self.meta, self.output)

    def test_wrong_convention_and_input_overwrite(self):
        data = json.loads(self.meta.read_text())
        data["dq_convention"] = "unknown"
        self.meta.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            adapter.convert(self.source, self.meta, self.output)
        original = self.source.read_bytes()
        with self.assertRaises(ValueError):
            adapter.convert(self.source, self.meta, self.source)
        self.assertEqual(self.source.read_bytes(), original)
