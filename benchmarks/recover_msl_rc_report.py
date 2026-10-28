"""Rebuild RC report after frozen scientific-source and full raw-file verification."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCIENCE = "ee39dcd32e8aa9eac8c07239455df21940a33947"
RUN = 40618818207
ALLOWED = {
    "reports/msl-rc.html", "benchmarks/recover_msl_rc_report.py",
    ".github/workflows/msl-rc.yml", "README.md",
}


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    changed = subprocess.check_output(["git", "diff", "--name-only", SCIENCE, "HEAD"],
                                      text=True).splitlines()
    unexpected = [p for p in changed if p not in ALLOWED and not p.startswith("docs/")]
    assert not unexpected, ("full scientific run required for changed physics/dependencies", unexpected)
    out = ROOT / "outputs"
    data = json.loads((out / "msl-rc/validation.json").read_text())
    assert data["passed"] and all(c["passed"] for c in data["cases"])
    assert data["linear_limits"]["passed"] and data["fixed_asset_pairing"]["passed"]
    assert data["metadata"]["commit"] == SCIENCE
    for name, expected in data["metadata"]["source_sha256"].items():
        assert sha(ROOT / name) == expected, ("scientific source differs", name)
    manifest = json.loads((out / "msl-rc/manifest.json").read_text())
    verified = 0
    for name, expected in manifest.items():
        if name.startswith("msl-rc-report/"):
            continue  # Unvalidated report was not included in the raw archive.
        assert sha(out / name) == expected, ("raw evidence differs", name)
        verified += 1
    print("rc-report-source-gate: "+json.dumps(dict(passed=True, verified_files=verified,
                                                  scientific_commit=SCIENCE, changed=changed)),
          flush=True)
    from build_msl_cooling_drive_report import main as build

    build(source=out / "msl-rc", output=out / "msl-rc-report", template="reports/msl-rc.html",
          contract="docs/msl-rc-contract.md",
          fmu="outputs/msl-parametric/OEALMSLParametric.fmu")
    assert json.loads((out / "msl-rc-report/ui-validation.json").read_text())["passed"]
    provenance = dict(passed=True, scientific_commit=SCIENCE, scientific_run=RUN,
                      raw_artifact_id=12786074257, verified_files=verified,
                      report_commit=subprocess.check_output(
                          ["git", "rev-parse", "HEAD"], text=True).strip(),
                      changed_files=changed,
                      scientific_source_sha256=data["metadata"]["source_sha256"])
    (out / "msl-rc-report/recovery-provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2))
    print("msl-rc-report-recovery: "+json.dumps(provenance), flush=True)


if __name__ == "__main__":
    main()
