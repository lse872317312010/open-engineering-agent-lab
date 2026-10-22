import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from oeal.agent_tools import ExperimentTools, run_design_iteration
from oeal.ir import document_hash


class AgentToolTests(TestCase):
    def setUp(self):
        self.goal = json.loads(Path("examples/ir/foc-experiment.json").read_text())

    def test_failure_diagnosis_repair_is_reproducible(self):
        with TemporaryDirectory() as temp:
            first = run_design_iteration(self.goal, Path(temp))
            second = run_design_iteration(self.goal, Path(temp))
            self.assertEqual(document_hash(first), document_hash(second))
            self.assertFalse(first["trace"][0]["verification"]["passed"])
            self.assertTrue(first["trace"][-1]["verification"]["passed"])

    def test_reject_goal_mutation_code_paths_and_excessive_gains(self):
        with TemporaryDirectory() as temp:
            tools = ExperimentTools(self.goal, Path(temp))
            for patch in (
                {"iq_reference_a": 1}, {"acceptance": {}}, {"shell": "true"},
                {"bandwidth_per_s": float("inf")}, {"bandwidth_per_s": True},
                {"bandwidth_per_s": 10000},
            ):
                with self.assertRaises(ValueError):
                    tools.propose_change(patch)
            candidate = copy.deepcopy(self.goal)
            candidate["settings"]["iq_reference_a"] = 1
            with self.assertRaises(ValueError):
                tools.run_experiment(candidate)

    def test_recompute_acceptance_ignores_forged_metrics_and_checks_binding(self):
        with TemporaryDirectory() as temp:
            tools = ExperimentTools(self.goal, Path(temp))
            candidate = tools.propose_change({"bandwidth_per_s": 50})
            result = tools.run_experiment(candidate)
            result["metrics"]["steady_error_a"] = 0
            result["metrics"]["settling_time_s"] = 0
            result["metrics"]["overshoot_a"] = 0
            self.assertFalse(tools.verify_change(candidate, result)["passed"])
            tampered = copy.deepcopy(result)
            tampered["samples"][-1][2] = 5.0
            with self.assertRaisesRegex(ValueError, "trusted session"):
                tools.verify_change(candidate, tampered)
            result["experiment_sha256"] = "0" * 64
            with self.assertRaises(ValueError):
                tools.verify_change(candidate, result)

    def test_ledger_immutable_and_inspection_returns_copy(self):
        with TemporaryDirectory() as temp:
            tools = ExperimentTools(self.goal, Path(temp))
            model = tools.inspect_model()
            model["id"] = "changed"
            self.assertNotEqual(tools.inspect_model()["id"], "changed")
            with self.assertRaisesRegex(ValueError, "elevate"):
                tools.record_evidence({"evidence_level": "PIL_measured"})
            digest = tools.record_evidence({"message": "test"})
            path = Path(temp) / (digest + ".json")
            path.write_text("corrupted")
            with self.assertRaisesRegex(ValueError, "corruption"):
                tools.record_evidence({"message": "test"})
