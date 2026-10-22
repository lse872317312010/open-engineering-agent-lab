import copy
import json
import math
from pathlib import Path
from unittest import TestCase

from oeal.experiments import run_experiment
from oeal.ir import canonical, document_hash, validate_document


class IRTests(TestCase):
    def setUp(self):
        self.spec = json.loads(Path("examples/ir/foc-experiment.json").read_text())

    def test_round_trip_and_execution(self):
        validate_document(self.spec)
        restored = json.loads(canonical(self.spec))
        self.assertEqual(restored, self.spec)
        self.assertEqual(document_hash(restored), document_hash(self.spec))
        result = run_experiment(restored)
        self.assertEqual(result["kind"], "SimulationResult")
        self.assertLess(result["metrics"]["steady_error_a"], 0.05)

    def test_reject_wrong_units_clocks_unknown_fields_and_code(self):
        changes = [
            lambda s: s["model"]["parameters"]["q_inductance_h"].update(unit="mH"),
            lambda s: s["model"]["clocks"]["pwm"].update(value=7e-6),
            lambda s: s["settings"].update(control_period_s=100e-6),
            lambda s: s.update(callback="__import__('os')"),
            lambda s: s["model"].update(dynamics="arbitrary_python"),
            lambda s: s.update(backend="shell"),
            lambda s: s.update(budget_steps=1),
            lambda s: s.update(seed=1),
            lambda s: s["model"]["parameters"]["pole_pairs"].update(value=True),
            lambda s: s["settings"].update(vdc_v=math.nan),
        ]
        for change in changes:
            spec = copy.deepcopy(self.spec)
            change(spec)
            with self.subTest(change=change):
                with self.assertRaises(Exception):
                    validate_document(spec)

    def test_other_contracts_and_result_shape(self):
        zero = "0" * 64
        artifact = dict(
            version="0.1", kind="CodeArtifact", target="host", abi="double",
            compiler="gcc", flags=["-O2"], source_sha256=zero,
            binary_sha256=zero, resource_report_sha256=zero,
        )
        self.assertEqual(validate_document(artifact), artifact)
        evidence = dict(
            version="0.1", kind="Evidence", level="model_simulated",
            subject_sha256=zero, source_commit="test", command=["oeal"],
            environment={"python": "test"}, passed=True, limitations=[],
            artifact_hashes={"trace": zero},
        )
        self.assertEqual(validate_document(evidence), evidence)
        result = run_experiment(self.spec)
        result["samples"][1][0] = 0.0
        with self.assertRaises(ValueError):
            validate_document(result)

    def test_pathsim_foc_rejected_before_import(self):
        self.spec["backend"] = "pathsim"
        with self.assertRaisesRegex(ValueError, "open_loop"):
            run_experiment(self.spec)
