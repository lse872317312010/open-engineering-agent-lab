"""Accept immutable complete native lanes without accepting the derived report."""
import json
import os
import re
import subprocess

from p7_angle_aggregate import OUT, read_lane


def main():
    sha = os.environ["ANGLE_SOURCE_COMMIT"]
    run = int(os.environ["ANGLE_SOURCE_RUN"])
    assert re.fullmatch("[0-9a-f]{40}", sha) and run > 0
    fine = os.environ["ANGLE_FINE_COMMIT"]
    assert re.fullmatch("[0-9a-f]{40}", fine)
    subprocess.run(["git", "fetch", "origin", sha, fine, "--depth=1"], check=True)
    subprocess.run(["git", "diff", "--exit-code", sha, "HEAD", "--",
                    "benchmarks/p7_angle_native.py", "benchmarks/p7_pyleecan.py",
                    "benchmarks/p7_pyleecan_reference.py",
                    "benchmarks/assets/pyleecan-spmsm001.json"], check=True)
    subprocess.run(["git", "diff", "--exit-code", sha, fine, "--",
                    "benchmarks/p7_angle_native.py", "benchmarks/p7_pyleecan.py",
                    "benchmarks/p7_pyleecan_reference.py",
                    "benchmarks/assets/pyleecan-spmsm001.json"], check=True)
    lanes = [read_lane(i, g) for i, g in enumerate((1., 1.5, 2.))]
    OUT.mkdir(parents=True, exist_ok=True)
    proof = dict(passed=True, accepted_stage="native_only", source_commit=sha, source_run=run,
                 fine_source_commit=fine, fine_source_run=int(os.environ["ANGLE_FINE_RUN"]),
                 manifest_counts=[x[2] for x in lanes], native_files=78,
                 producers_identical=True, analysis_and_browser_must_rerun=True)
    (OUT / "reuse-proof.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print("angle-native-reuse: "+json.dumps(proof), flush=True)


if __name__ == "__main__":
    main()
