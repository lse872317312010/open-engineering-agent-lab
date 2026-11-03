"""Verify immutable numerical evidence before rebuilding only the offline report."""
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/p7-femm-nonlinear"
SOURCE_COMMIT = "57b5958e6e8824d9a75b923b20073e9d619aee49"
PRODUCERS = ["benchmarks/p7_femm_nonlinear.py", "benchmarks/p7_femm_nonlinear_batch.py",
             "benchmarks/p7_femm_nonlinear_reference.py", "benchmarks/p7_femm_motor.py",
             "benchmarks/p7_femm_probe.py", "benchmarks/p7_femm_reference.py",
             "benchmarks/p7_femm_sampling.py", "src"]


def main():
    assert re.fullmatch("[0-9a-f]{40}", SOURCE_COMMIT)
    subprocess.run(["git", "fetch", "origin", SOURCE_COMMIT, "--depth=1"], cwd=ROOT, check=True)
    subprocess.run(["git", "diff", "--exit-code", SOURCE_COMMIT, "HEAD", "--", *PRODUCERS],
                   cwd=ROOT, check=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    assert data["commit"] == SOURCE_COMMIT and data["passed"]
    assert all(data["checks"].values())
    assert all(g["commit"] == SOURCE_COMMIT and g["passed"] and all(g["checks"].values())
               for g in data["grids"])
    manifest = json.loads((SOURCE / "manifest.json").read_text())
    verified = []
    for name, digest in manifest.items():
        name = name.replace("\\", "/")
        prefix = "p7-femm-nonlinear/"
        if not name.startswith(prefix):
            continue
        relative = name[len(prefix):]
        assert not relative.startswith("/") and ".." not in PurePosixPath(relative).parts
        path = SOURCE / relative
        assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest
        verified.append(relative)
    native = {p for p in verified if p.endswith((".fem", ".ans"))}
    actual = {p.relative_to(SOURCE).as_posix() for p in SOURCE.rglob("*")
              if p.is_file() and p.suffix in {".fem", ".ans"}}
    assert len(verified) > 184 and len(native) == 184 and native == actual
    for g in data["grids"]:
        path = SOURCE / f"grid{g['grid']}/flux-map.json"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == g["map_sha256"]
    assert json.loads((SOURCE / "material-validation.json").read_text())["passed"]
    proof = dict(passed=True, accepted_stage="numerical_only", source_commit=SOURCE_COMMIT,
                 source_run_id=41575606304, source_artifact_id=13205251106,
                 verified_raw_files=len(verified), native_files=len(native),
                 producers_identical=True, source_ui_accepted=False, report_must_rerun=True)
    (SOURCE / "report-reuse.json").write_text(json.dumps(proof, indent=2))
    print("p7-nonlinear-report-reuse: "+json.dumps(proof), flush=True)


if __name__ == "__main__":
    main()
