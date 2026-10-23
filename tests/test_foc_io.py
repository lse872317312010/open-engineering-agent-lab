import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from oeal.cli import main
from oeal.metrics import b1_passes, current_step_metrics


class FOCIOTests(TestCase):
    def test_cli_writes_recomputable_metrics_and_open_trace(self):
        with TemporaryDirectory() as temp:
            output = Path(temp)
            self.assertEqual(main([
                "simulate-foc", "examples/foc_step.json", "--output", str(output)
            ]), 0)
            import numpy as np

            data = np.loadtxt(output / "trace.csv", delimiter=",", skiprows=1)
            report = json.loads((output / "summary.json").read_text())
            self.assertEqual(report["evidence_level"], "model_simulated")
            recomputed = current_step_metrics(data, 0.001, 5, 48 / (3 ** 0.5))
            self.assertEqual(report["metrics"], recomputed)
            self.assertTrue(b1_passes(recomputed))
            self.assertEqual(len(report["run_metadata"]["trace_sha256"]), 64)

    def test_metric_rejects_nonfinite_and_invalid_timestamps(self):
        import numpy as np

        data = np.zeros((2, 13))
        with self.assertRaises(ValueError):
            current_step_metrics(data, 0, 5, 24)
        data[1, 0] = 1
        data[0, 2] = np.nan
        with self.assertRaises(ValueError):
            current_step_metrics(data, 0, 5, 24)
