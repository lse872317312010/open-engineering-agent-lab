import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from oeal.cli import run_simulation


class CLITests(TestCase):
    def test_cli_runner_writes_agent_readable_outputs(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "run"
            trace_path, summary_path = run_simulation(
                repo_root / "examples" / "pmsm_step.json", output_dir
            )
            self.assertTrue(trace_path.is_file())
            self.assertTrue(summary_path.is_file())
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["run_metadata"]["oeal_version"], "0.1.0")
            self.assertEqual(len(summary["run_metadata"]["config_sha256"]), 64)
            self.assertEqual(summary["simulation"]["sample_count"], 2001)
            self.assertGreater(summary["metrics"]["peak_abs_iq_a"], 0)
            self.assertGreater(summary["final_state"]["mechanical_speed_rad_s"], 0)
            self.assertTrue(
                trace_path.read_text(encoding="utf-8").startswith("time_s,id_a,iq_a,")
            )

