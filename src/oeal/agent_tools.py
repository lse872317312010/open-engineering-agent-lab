"""Restricted experiment tools; no code, paths, acceptance edits or device access."""

import copy
from pathlib import Path

import numpy as np

from oeal.experiments import run_experiment
from oeal.ir import canonical, document_hash, validate_document
from oeal.metrics import b1_passes, current_step_metrics

_ALLOWED = frozenset({"bandwidth_per_s", "tracking_rate_per_s"})


class ExperimentTools:
    """Trusted host creates a session with a protected goal; proposals only tune gains."""

    def __init__(self, goal, ledger_dir: Path):
        validate_document(goal)
        if goal["mode"] != "foc" or goal["backend"] != "native":
            raise ValueError("agent session requires native FOC")
        if goal["settings"]["iq_reference_a"] != 5 or goal["settings"]["id_reference_a"] != 0:
            raise ValueError("v0.1 acceptance goal requires id=0 and iq=5 A")
        self._runs = set()
        self._goal = copy.deepcopy(goal)
        self._ledger = Path(ledger_dir)
        self._ledger.mkdir(parents=True, exist_ok=True)

    def inspect_model(self):
        return copy.deepcopy(self._goal["model"])

    def _check_scope(self, candidate):
        validate_document(candidate)
        protected = copy.deepcopy(candidate)
        for key in _ALLOWED:
            protected["settings"][key] = self._goal["settings"][key]
        if canonical(protected) != canonical(self._goal):
            raise ValueError("proposal modifies protected model, goal or acceptance context")

    def propose_change(self, patch):
        if not isinstance(patch, dict) or not patch or set(patch) - _ALLOWED:
            raise ValueError("only allowlisted controller tuning fields may change")
        for value in patch.values():
            if type(value) not in (int, float) or not 0 < value <= 5000:
                raise ValueError("gain proposal outside finite allowed range (0,5000]")
        candidate = copy.deepcopy(self._goal)
        candidate["settings"].update(patch)
        self._check_scope(candidate)
        return candidate

    def run_experiment(self, candidate):
        self._check_scope(candidate)
        result = run_experiment(candidate)
        self._runs.add(document_hash({
            "input": result["experiment_sha256"], "samples": result["samples"],
            "columns": result["columns"],
        }))
        self.record_evidence({"experiment": candidate, "result": result})
        return result

    def verify_change(self, candidate, result):
        self._check_scope(candidate)
        validate_document(result)
        if result["experiment_sha256"] != document_hash(candidate):
            raise ValueError("result bound to a different experiment")
        if result["columns"] != [
            "time_s", "id_a", "iq_a", "mechanical_speed_rad_s", "mechanical_angle_rad",
            "vd_v", "vq_v", "duty_a", "duty_b", "duty_c", "id_reference_a",
            "iq_reference_a", "voltage_limited",
        ]:
            raise ValueError("unexpected trace columns")
        raw_digest = document_hash({
            "input": result["experiment_sha256"], "samples": result["samples"],
            "columns": result["columns"],
        })
        if raw_digest not in self._runs:
            raise ValueError("trace was not produced by this trusted session")
        settings = self._goal["settings"]
        data = np.asarray(result["samples"], dtype=float)
        expected_times = np.arange(
            round(settings["duration_s"] / settings["control_period_s"]) + 1
        ) * settings["control_period_s"]
        if data.shape[0] != len(expected_times) or not np.allclose(
            data[:, 0], expected_times, rtol=0, atol=1e-14
        ):
            raise ValueError("trace does not cover the protected experiment")
        active = data[:, 0] >= settings["step_time_s"] - 1e-14
        if not np.allclose(data[active, 11], 5, atol=1e-12, rtol=0):
            raise ValueError("trace reference differs from protected target")
        metrics = current_step_metrics(
            data, settings["step_time_s"], 5, settings["vdc_v"] / (3 ** 0.5)
        )
        verification = {
            "passed": b1_passes(metrics), "metrics": metrics,
            "result_sha256": document_hash(result),
            "experiment_sha256": document_hash(candidate),
            "evidence_level": "model_simulated",
            "reason": "fixed B1 acceptance passed" if b1_passes(metrics)
            else "fixed B1 acceptance failed; inspect settling, error, overshoot or voltage",
        }
        self.record_evidence(verification)
        return verification

    def compare_results(self, left, right):
        return {
            "steady_error_change_a": right["metrics"]["steady_error_a"]
            - left["metrics"]["steady_error_a"],
            "left_passed": left["passed"], "right_passed": right["passed"],
        }

    def record_evidence(self, record):
        def check_level(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in {"level", "evidence_level"} and child != "model_simulated":
                        raise ValueError(
                            "agent tools cannot elevate evidence beyond model_simulated"
                        )
                    check_level(child)
            elif isinstance(value, list):
                for child in value:
                    check_level(child)

        check_level(record)
        # Filenames are derived only from canonical content; no caller-controlled paths.
        text = canonical(record) + "\n"
        digest = document_hash(record)
        path = self._ledger / (digest + ".json")
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(text)
        except FileExistsError:
            if path.read_text(encoding="utf-8") != text:
                raise ValueError("ledger object corruption") from None
        return digest


def run_design_iteration(goal, ledger_dir):
    """Assistant-authored offline proposal policy exercising the replaceable tool API."""
    tools = ExperimentTools(goal, ledger_dir)
    trace = []
    previous = None
    for bandwidth, explanation in (
        (50.0, "Probe low bandwidth; expected to fail the fixed 5 ms settling goal."),
        (2000.0, "Repair using ln(50)/bandwidth settling estimate, retaining fixed limits."),
    ):
        candidate = tools.propose_change({
            "bandwidth_per_s": bandwidth, "tracking_rate_per_s": bandwidth
        })
        result = tools.run_experiment(candidate)
        verification = tools.verify_change(candidate, result)
        entry = {
            "proposal": {"bandwidth_per_s": bandwidth, "tracking_rate_per_s": bandwidth},
            "hypothesis": explanation, "verification": verification,
        }
        if previous:
            entry["comparison"] = tools.compare_results(previous, verification)
        trace.append(entry)
        previous = verification
        if verification["passed"]:
            break
    report = {
        "policy": "assistant-authored offline regression; no hosted LLM",
        "goal_sha256": document_hash(goal), "trace": trace,
        "passed": trace[-1]["verification"]["passed"],
    }
    tools.record_evidence(report)
    return report
