"""Exercise every registered backend through the shared versioned API and CLI."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from oeal.experiments import run_experiment
from oeal.ir import document_hash, validate_document
from oeal.studies import catalog

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/unified"
ASSETS = ROOT / "outputs/open-models"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    for profile in catalog():
        source = ROOT / "examples/studies" / (profile + ".json")
        spec = json.loads(source.read_text())
        validate_document(spec)
        result = run_experiment(spec, ASSETS)
        assert result["numeric_passed"], result["context"]
        (OUT / (profile + ".json")).write_text(json.dumps(result, allow_nan=False))
        results[profile] = {
            "input_sha256": document_hash(spec), "raw_sha256": result["raw_sha256"],
            "metrics": result["metrics"], "goal_passed": result["goal_passed"],
            "backend": result["backend"], "numeric_passed": result["numeric_passed"],
            "streams": list(result["streams"]),
        }
        print("unified-case.json: " + json.dumps({"profile": profile, **results[profile]}),
              flush=True)
    native = json.loads((ROOT / "examples/studies/native_foc_v1.json").read_text())
    native["settings"]["delay_samples"] = {"value": 0, "unit": "1"}
    reference = run_experiment(native)
    external = copy.deepcopy(native)
    external["model"]["profile"] = "motulator_pmsm_v1"
    external["backend"] = "motulator"
    external["settings"]["pwm"] = False
    external["settings"]["thermal_feedback"] = False
    other = run_experiment(external)
    left = np.asarray(reference["streams"]["control"]["samples"])
    right = np.asarray(other["streams"]["control"]["samples"])
    cross = float(np.max(np.abs(left[:, 1:3] - right[:, 1:3])))
    assert cross < 1e-5, cross
    exported = OUT / "cli-native.json"
    subprocess.run(
        [sys.executable, "-m", "oeal", "run-experiment",
         str(ROOT / "examples/studies/native_foc_v1.json"), "--output", str(exported),
         "--csv-dir", str(OUT / "cli-csv")],
        check=True,
    )
    cli = json.loads(exported.read_text())
    assert cli["raw_sha256"] == results["native_foc_v1"]["raw_sha256"]
    assert (OUT / "cli-csv/control.csv").read_text().startswith("time_s,id_a,iq_a")
    assert json.loads((OUT / "cli-csv/streams.json").read_text())["raw_sha256"] == cli["raw_sha256"]
    report = {"passed": True, "profiles": results, "cross_backend_current_error_a": cross,
              "scope": "IR 0.2 native, motulator and UR5e registered adapters"}
    (OUT / "summary.json").write_text(json.dumps(report, indent=2))
    print("unified.json: " + json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
