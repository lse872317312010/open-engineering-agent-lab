"""Rebuild reports only after verifying frozen science source and every retained data hash."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCIENCE = "37fb10c8d82bd2488d15e7e91813231c9cbb9aaf"
RUN = 40613204776
ALLOWED = {
    "benchmarks/build_msl_cooling_drive_report.py",
    "benchmarks/recover_msl_configured_report.py",
    "reports/msl-configured-drive.html",
    ".github/workflows/msl-configured-drive.yml",
    "README.md",
}


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    changed = subprocess.check_output(["git", "diff", "--name-only", SCIENCE, "HEAD"],
                                      text=True).splitlines()
    unexpected = [p for p in changed if p not in ALLOWED and not p.startswith("docs/")]
    assert not unexpected, ("physics/dependency changes require a full scientific run", unexpected)
    out = ROOT / "outputs"
    data = json.loads((out / "msl-configured-drive/validation.json").read_text())
    assert data["passed"] and all(c["passed"] for c in data["cases"])
    assert data["metadata"]["commit"] == SCIENCE
    for path, expected in data["metadata"]["source_sha256"].items():
        assert sha(ROOT / path) == expected, ("scientific source differs", path)
    manifest = json.loads((out / "msl-configured-drive/manifest.json").read_text())
    verified = 0
    for path, expected in manifest.items():
        # The raw archive deliberately omits the unvalidated configured report.
        if path.startswith("msl-configured-drive-report/"):
            continue
        assert sha(out / path) == expected, ("retained evidence differs", path)
        verified += 1
    legacy = json.loads((out / "msl-cooling-drive/validation.json").read_text())
    assert legacy["passed"] and all(c["passed"] for c in legacy["cases"])
    print("report-recovery-source-gate: "+json.dumps(dict(
        passed=True, scientific_commit=SCIENCE, scientific_run=RUN,
        verified_files=verified, changed_files=changed)), flush=True)
    from build_msl_cooling_drive_report import main as build

    build()
    build(source=out / "msl-configured-drive", output=out / "msl-configured-drive-report",
          template="reports/msl-configured-drive.html",
          contract="docs/msl-configured-drive-contract.md")
    for folder in ("msl-cooling-drive-report", "msl-configured-drive-report"):
        assert json.loads((out / folder / "ui-validation.json").read_text())["passed"]
    provenance = dict(passed=True, scientific_commit=SCIENCE, scientific_run=RUN,
                      raw_artifact_id=12785420445, verified_files=verified,
                      report_commit=subprocess.check_output(
                          ["git", "rev-parse", "HEAD"], text=True).strip(),
                      changed_files=changed,
                      scientific_source_sha256=data["metadata"]["source_sha256"])
    (out / "msl-configured-drive-report/recovery-provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2))
    print("configured-report-recovery: "+json.dumps(provenance), flush=True)


if __name__ == "__main__":
    main()
