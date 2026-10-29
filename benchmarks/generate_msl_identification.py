"""Generate three actual-MSL datasets; truth and measured training packet are separate files."""
import json
import subprocess

from msl_identification_protocol import SPLITS, truth
from msl_identification_simulator import OUT, measurements, simulate


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    private = OUT / "reference"
    private.mkdir(exist_ok=True)
    (private / "truth.json").write_text(json.dumps(truth(), indent=2))
    reports = []
    for case in SPLITS:
        destination = OUT / case["id"]
        data, report = simulate(case, truth(), destination)
        report["measurement_sha256"] = measurements(case, data, destination)
        reports.append(report)
    summary = dict(passed=all(c["passed"] for c in reports), cases=reports,
                   commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                   evidence_level="model_simulated",
                   scope="independent thermal excitation; not actual-drive endurance")
    (OUT / "generation.json").write_text(json.dumps(summary, indent=2))
    print("identification-generation: "+json.dumps(summary), flush=True)
    assert summary["passed"]


if __name__ == "__main__":
    main()
