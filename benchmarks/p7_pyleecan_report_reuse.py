"""Accept complete immutable native evidence only when numerical producers match."""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/p7-pyleecan"
PRODUCERS = ["benchmarks/p7_pyleecan.py", "benchmarks/p7_pyleecan_reference.py",
             "benchmarks/assets/pyleecan-spmsm001.json", "src"]


def main():
    sha = os.environ["PYLEECAN_SOURCE_COMMIT"]
    run = int(os.environ["PYLEECAN_SOURCE_RUN"])
    artifact = int(os.environ["PYLEECAN_SOURCE_ARTIFACT"])
    assert re.fullmatch("[0-9a-f]{40}", sha) and run > 0 and artifact > 0
    subprocess.run(["git", "fetch", "origin", sha, "--depth=1"], cwd=ROOT, check=True)
    subprocess.run(["git", "diff", "--exit-code", sha, "HEAD", "--", *PRODUCERS],
                   cwd=ROOT, check=True)
    validation = json.loads((SOURCE / "validation.json").read_text())
    geometry = json.loads((SOURCE / "geometry.json").read_text())
    assert validation["commit"] == sha and validation["passed"]
    assert geometry["passed"] and all(geometry["checks"].values())
    assert all(validation["checks"].values()) and len(validation["cases"]) == 12
    assert all(r["passed"] and all(r["checks"].values()) for r in validation["cases"])
    manifest = json.loads((SOURCE / "manifest.json").read_text())
    assert manifest
    verified = set()
    for name, digest in manifest.items():
        name = name.replace("\\", "/")
        assert not name.startswith("/") and ".." not in PurePosixPath(name).parts
        path = SOURCE / name
        assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest
        verified.add(name)
    native = {p for p in verified if p.endswith((".fem", ".ans"))}
    actual = {p.relative_to(SOURCE).as_posix() for p in SOURCE.rglob("*")
              if p.is_file() and p.suffix in {".fem", ".ans"}}
    assert native == actual and len(native) >= 24
    for result in validation["cases"]:
        assert len(result["native_files"]) >= 2
        for name, digest in result["native_files"].items():
            assert name in native
            assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == digest
    asset = ROOT / "benchmarks/assets/pyleecan-spmsm001.json"
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == geometry["asset_sha256"]
    proof = dict(passed=True, accepted_stage="native_numerical_only", source_commit=sha,
                 source_run_id=run, source_artifact_id=artifact, verified_files=len(verified),
                 native_files=len(native), producers_identical=True, report_must_rerun=True)
    (SOURCE / "report-reuse.json").write_text(json.dumps(proof, indent=2))
    print("p7-pyleecan-report-reuse: "+json.dumps(proof), flush=True)


if __name__ == "__main__":
    main()
