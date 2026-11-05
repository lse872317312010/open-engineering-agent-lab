"""Verify FEMM coenergy readbacks and independently recompute virtual work."""
import csv
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

from p7_cogging_model import FourierSeries
from p7_native_coenergy_ref import compare

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-cogging-report"
EXE = "5e83cf0899cabae2017868ddcce338e3ba4ac25d1bf8e511eac77eda2bc92a21"
DEEP = "4030532a05a932b3c84f7742218d23130be2f819"
SECOND = "ec41e9b79de7d918c11a04a5c4ae455a7b900938"


def main():
    source = os.environ["NATIVE_COMMIT"]
    subprocess.run(["git", "fetch", "origin", source, "--depth=1"], check=True)
    subprocess.run(["git", "diff", "--exit-code", source, "HEAD", "--",
                    "benchmarks/p7_native_coenergy.py", "benchmarks/p7_native_coenergy_ref.py"],
                   check=True)
    model = json.loads((OUT / "coenergy-model.json").read_text())
    fields = json.loads((OUT / "fields.json").read_text())
    assert hashlib.sha256((OUT / "coenergy-model.json").read_bytes()).hexdigest() == (
        fields["model_sha256"])
    cog = FourierSeries(model["cog_a"], model["cog_b"])
    rows = []
    for shard in range(8):
        folder = ROOT / f"outputs/native-results/native-coenergy-{shard}"
        manifest = json.loads((folder / "manifest.json").read_text())
        assert set(manifest) == {"native-coenergy.json"}
        path = folder / "native-coenergy.json"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["native-coenergy.json"]
        data = json.loads(path.read_text())
        center = 2.8125+5.625*shard
        assert data["evidence_passed"] and data["shard"] == shard and data["center_deg"] == center
        assert data["commit"] == source and data["source_commits"] == [DEEP, SECOND]
        assert data["executable_sha256"] == EXE and len(data["samples"]) == 5
        samples = data["samples"]
        assert [r["angle_deg"] for r in samples] == [
            center-1.40625, center-.703125, center, center+.703125, center+1.40625]
        assert all(r["area_m2"] > 0 and r["gap_energy_j"] > 0
                   and max(abs(i) for i in r["currents_a"]) <= 1e-10 for r in samples)
        result = compare([r["block_coenergy_j"] for r in samples],
                         [r["gap_energy_j"] for r in samples],
                         samples[2]["stress_torque_nm"], samples[2]["gap_torque_nm"])
        for key, value in result.items():
            previous = data["comparison"][key]
            assert previous == value if isinstance(value, bool) else math.isclose(
                previous, value, rel_tol=1e-13, abs_tol=1e-13)
        archive = OUT / f"native-evidence/shard-{shard}"
        archive.mkdir(parents=True, exist_ok=True)
        (archive / "native-coenergy.json").write_bytes(path.read_bytes())
        (archive / "manifest.json").write_bytes((folder / "manifest.json").read_bytes())
        rows.append(dict(index=shard, center_deg=center, samples=samples, **result,
                         native_coenergy_j=samples[2]["block_coenergy_j"]
                         +samples[2]["gap_energy_j"],
                         reconstructed_coenergy_j=float(cog.integral(math.radians(center))[0])))
    baseline_native = rows[0]["native_coenergy_j"]
    baseline_model = rows[0]["reconstructed_coenergy_j"]
    for r in rows:
        r["native_relative_j"] = r["native_coenergy_j"]-baseline_native
        r["reconstructed_relative_j"] = r["reconstructed_coenergy_j"]-baseline_model
        r["relative_coenergy_error_j"] = abs(r["native_relative_j"]-r["reconstructed_relative_j"])
    data = dict(evidence_passed=True, supported=all(r["passed"] for r in rows),
                rows=rows, source_commit=source, source_run=os.environ["NATIVE_RUN"],
                max_fine_error_nm=max(r["error_nm"] for r in rows),
                max_coarse_error_nm=max(r["coarse_error_nm"] for r in rows),
                max_refinement_nm=max(r["refinement_nm"] for r in rows),
                max_gap_omission_effect_nm=max(r["gap_omission_effect_nm"] for r in rows),
                max_relative_coenergy_error_j=max(r["relative_coenergy_error_j"] for r in rows),
                failed_indices=[r["index"] for r in rows if not r["passed"]])
    (OUT / "native.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    with (OUT / "native.csv").open("w", newline="", encoding="utf-8") as fp:
        keys = ["center_deg", "energy_torque_nm", "coarse_torque_nm", "block_only_torque_nm",
                "stress_torque_nm", "gap_torque_nm", "error_nm", "coarse_error_nm",
                "refinement_nm", "gap_omission_effect_nm", "native_relative_j",
                "reconstructed_relative_j", "relative_coenergy_error_j", "passed"]
        writer = csv.writer(fp)
        writer.writerow(keys)
        writer.writerows([[r[k] for k in keys] for r in rows])
    with (OUT / "native-samples.csv").open("w", newline="", encoding="utf-8") as fp:
        keys = ["angle_deg", "block_coenergy_j", "block_energy_j", "gap_energy_j", "area_m2",
                "nodes", "stress_torque_nm", "gap_torque_nm", "fem", "ans"]
        writer = csv.writer(fp)
        writer.writerow(["center_deg"]+keys)
        for r in rows:
            for sample in r["samples"]:
                writer.writerow([r["center_deg"]]+[sample[k] for k in keys])
    print("native-coenergy-summary: "+json.dumps({k: v for k, v in data.items() if k != "rows"}),
          flush=True)


if __name__ == "__main__":
    main()
