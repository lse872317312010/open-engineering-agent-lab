"""Protected design sessions shared by all registered IR 0.2 backends."""

import copy
from pathlib import Path

from oeal.agent_tools import ExperimentTools
from oeal.experiments import run_experiment
from oeal.ir import canonical, document_hash, validate_document
from oeal.studies import recompute

BOUNDS = {
    "bandwidth_per_s": (1.0, 5000.0), "tracking_rate_per_s": (1.0, 5000.0),
    "outer_kp_nm_per_rad": (50.0, 1200.0), "outer_kd_nms_per_rad": (5.0, 100.0),
}


class StudyTools:
    """Host owns the fixed experiment, assets, budget and goals; proposals tune gains."""

    def __init__(self, goal, ledger_dir, assets_root=None):
        validate_document(goal)
        if goal.get("kind") != "ExperimentSpec" or goal["version"] != "0.2":
            raise ValueError("IR 0.2 ExperimentSpec required")
        self._goal = copy.deepcopy(goal)
        self._assets_root = assets_root
        self._ledger = Path(ledger_dir)
        self._ledger.mkdir(parents=True, exist_ok=True)
        self._trusted = set()
        allowed = ({"outer_kp_nm_per_rad", "outer_kd_nms_per_rad"}
                   if goal["model"]["profile"] in {"ur5e_joint_v1", "fmi_servo_v2"} else set(BOUNDS))
        self._allowed = allowed.intersection(goal["settings"])
        self._bounds = ({"outer_kp_nm_per_rad": (10., 200.), "outer_kd_nms_per_rad": (.5, 10.)}
                        if goal["model"]["profile"] == "fmi_servo_v2" else BOUNDS)

    def inspect_model(self):
        return copy.deepcopy(self._goal["model"])

    def _check_scope(self, candidate):
        validate_document(candidate)
        protected = copy.deepcopy(candidate)
        for key in self._allowed:
            protected["settings"][key] = self._goal["settings"][key]
        if canonical(protected) != canonical(self._goal):
            raise ValueError("proposal changes protected model, target, clock, seed or budget")

    def propose_change(self, patch):
        if not isinstance(patch, dict) or not patch or set(patch) - self._allowed:
            raise ValueError("only declared, allowlisted control gains may change")
        candidate = copy.deepcopy(self._goal)
        for key, value in patch.items():
            low, high = self._bounds[key]
            if type(value) not in (int, float) or not low <= value <= high:
                raise ValueError("proposal exceeds the fixed tuning bounds")
            candidate["settings"][key]["value"] = value
        self._check_scope(candidate)
        self.record_evidence({"proposal": patch, "candidate_sha256": document_hash(candidate)})
        return candidate

    @staticmethod
    def _token(result):
        return document_hash({
            "experiment": result["experiment_sha256"], "streams": result["streams"],
            "context": result["context"], "primary": result["primary_stream"],
            "backend": result["backend"], "profile": result["profile"],
        })

    def run_experiment(self, candidate):
        self._check_scope(candidate)
        result = run_experiment(candidate, self._assets_root)
        self._trusted.add(self._token(result))
        self.record_evidence({"experiment": candidate, "result": result})
        return result

    def verify_change(self, candidate, result):
        self._check_scope(candidate)
        validate_document(result)
        if result["experiment_sha256"] != document_hash(candidate):
            raise ValueError("result belongs to another input")
        if self._token(result) not in self._trusted:
            raise ValueError("raw data or context was not produced by this trusted session")
        metrics, numeric, passed = recompute(candidate, result)
        verification = {
            "passed": passed, "numeric_passed": numeric, "metrics": metrics,
            "experiment_sha256": document_hash(candidate),
            "raw_sha256": document_hash(result["streams"]),
            "evidence_level": "model_simulated",
        }
        self.record_evidence(verification)
        return verification

    def compare_results(self, left, right):
        common = set(left["metrics"]).intersection(right["metrics"])
        return {
            "left_passed": left["passed"], "right_passed": right["passed"],
            "metric_changes": {key: right["metrics"][key] - left["metrics"][key]
                               for key in sorted(common)},
        }

    def record_evidence(self, record):
        return ExperimentTools.record_evidence(self, record)
