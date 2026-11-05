"""Audit new mixed-current native evidence and compare the unchanged local model."""
import csv
import hashlib
import json
import os
import subprocess
from pathlib import Path, PurePosixPath

from p7_angular_reference import evaluate
from p7_local_flux_model import LocalFluxModel

from oeal.transforms import clarke, park

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-current-report"
ANGLES = (0., 11.25, 22.5, 33.75)
PAIRS = ((0, .5), (0, -.5), (.5, 0), (-.5, 0),
         (1, 1), (1, -1), (-1, 1), (-1, -1))
FRAME = "541602aad016740d7263493d6062244edfae0923c2b59a1ac349889547c9234f"
MODEL = "dc8c5ca77d55c7fe876d7c18da1ad897896c9e0289b5d940417984fec1a6068e"
EXE = "5e83cf0899cabae2017868ddcce338e3ba4ac25d1bf8e511eac77eda2bc92a21"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = os.environ["CURRENT_COMMIT"]
    subprocess.run(["git", "fetch", "origin", source, "--depth=1"], check=True)
    subprocess.run(["git", "diff", "--exit-code", source, "HEAD", "--",
                    "benchmarks/p7_current_holdout_native.py", "benchmarks/p7_loaded_solver.py",
                    "benchmarks/p7_pyleecan.py", "benchmarks/assets/pyleecan-spmsm001.json",
                    "src/oeal/transforms.py"], check=True)
    previous = json.loads((ROOT / "outputs/p7-angular-report/validation.json").read_text())
    assert previous["evidence_passed"] and len(previous["rows"]) == 40
    model_path = ROOT / "outputs/frozen-model/model.json"
    assert hashlib.sha256(model_path.read_bytes()).hexdigest() == MODEL
    model_data = json.loads(model_path.read_text())
    model = LocalFluxModel(model_data["psi_wb"], model_data["inductance_h"])
    (OUT / "model.json").write_bytes(model_path.read_bytes())
    rows = []
    counts = []
    for shard, angle in enumerate(ANGLES):
        folder = ROOT / f"outputs/current/current-holdout-{shard}"
        manifest = json.loads((folder / "manifest.json").read_text())
        required = {"environment.json", "geometry.json", "frame.json", "current-holdout.json"}
        assert required <= set(manifest)
        for name, digest in manifest.items():
            path = PurePosixPath(name)
            assert not path.is_absolute() and ".." not in path.parts
            assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
        assert hashlib.sha256((folder / "frame.json").read_bytes()).hexdigest() == FRAME
        env = json.loads((folder / "environment.json").read_text())
        assert env["source_commit"] == source and env["executable_sha256"] == EXE
        geo = json.loads((folder / "geometry.json").read_text())
        assert geo["passed"] and all(geo["checks"].values())
        assert geo["asset_sha256"] == (
            "beba1fd4ed50e8c1d13743209a7e345ecd21a0ee9e64960c22a08924511cea06")
        lane = json.loads((folder / "current-holdout.json").read_text())
        assert lane["evidence_passed"] and lane["shard"] == shard
        assert lane["commit"] == source and lane["frame_sha256"] == FRAME
        assert len(lane["cases"]) == 8
        native = {n for n in manifest if n.endswith((".fem", ".ans"))}
        seen = set()
        anchors = [dict(r) for r in previous["rows"] if r["angle_deg"] == angle]
        assert len(anchors) == 5
        assert [(r["id_a"], r["iq_a"]) for r in anchors] == [
            (0, 0), (0, 2), (0, -2), (2, 0), (-2, 0)]
        baseline = anchors[0]["fe_torque_nm"]
        for r in anchors:
            r["index"] = len(rows)
            rows.append(r)
        for i, (r, pair) in enumerate(zip(lane["cases"], PAIRS, strict=True)):
            assert r["angle_deg"] == angle and (r["id_a"], r["iq_a"]) == pair
            assert r["case"] == f"loaded-{i}" and r["grid"] == 2. and r["length_m"] == .05
            assert r["passed"] and all(r["checks"].values())
            for name, digest in r["native_files"].items():
                assert name.startswith(r["case"]+"/") and name in native
                assert manifest[name] == digest
                seen.add(name)
            alpha, beta, _ = clarke(*r["native_currents_a"])
            actual = park(alpha, beta, r["electrical_rad"])
            assert max(abs(actual[0]-pair[0]), abs(actual[1]-pair[1])) <= 1e-10
            la, lb, zero = clarke(*r["flux_wb"])
            flux = park(la, lb, r["electrical_rad"])
            prediction = model.flux(pair)
            rows.append(dict(index=len(rows), angle_deg=angle, id_a=pair[0], iq_a=pair[1],
                             actual_id_a=actual[0], actual_iq_a=actual[1],
                             actual_wb=list(flux), predicted_wb=prediction.tolist(), zero_wb=zero,
                             fe_torque_nm=r["torque_nm"], baseline_nm=baseline,
                             increment_nm=r["torque_nm"]-baseline,
                             predicted_torque_nm=float(6*(prediction[0]*pair[1]
                                                         - prediction[1]*pair[0])),
                             raw_formula_nm=float(6*(flux[0]*pair[1]-flux[1]*pair[0])),
                             origin="new", role="current_holdout", commit=source,
                             currents_a=r["native_currents_a"], nodes=r["nodes"],
                             field=r["field"], phi_rad=r["phi_rad"],
                             actual_angle_rad=r["actual_angle_rad"]))
        assert seen == native and len(seen) == 16
        counts.append(len(manifest))
    assert len(rows) == 52
    gate = evaluate([r["actual_wb"] for r in rows], [r["predicted_wb"] for r in rows],
                    [r["increment_nm"] for r in rows], [r["predicted_torque_nm"] for r in rows])
    for i, r in enumerate(rows):
        r.update(flux_error=gate["flux_error"][i], torque_error_nm=gate["torque_error"][i],
                 supported=gate["supported"][i])
    envelopes = [dict(angle_deg=angle,
                      flux_error=max(r["flux_error"] for r in rows if r["angle_deg"] == angle),
                      torque_error_nm=max(r["torque_error_nm"] for r in rows
                                          if r["angle_deg"] == angle)) for angle in ANGLES]
    new = [r for r in rows if r["role"] == "current_holdout"]
    data = dict(evidence_passed=True, model_supported=gate["model_supported"],
                failed_indices=gate["failed_indices"], rows=rows, angles=ANGLES,
                geometry=previous["geometry"], envelopes=envelopes, manifest_counts=counts,
                new_cases=32, reused_cases=20, model_sha256=MODEL,
                new_supported=all(r["supported"] for r in new),
                max_new_flux_error=max(r["flux_error"] for r in new),
                max_new_torque_error_nm=max(r["torque_error_nm"] for r in new),
                max_flux_error=max(gate["flux_error"]),
                max_torque_error_nm=max(gate["torque_error"]), source_commit=source,
                source_run=os.environ["CURRENT_RUN"],
                report_commit=subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                      text=True).strip())
    (OUT / "validation.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    with (OUT / "angular.csv").open("w", newline="", encoding="utf-8") as fp:
        keys = ["angle_deg", "id_a", "iq_a", "actual_id_a", "actual_iq_a",
                "flux_error", "fe_torque_nm", "baseline_nm", "increment_nm",
                "predicted_torque_nm", "torque_error_nm", "supported", "origin", "role", "commit"]
        writer = csv.writer(fp)
        writer.writerow(keys+["actual_d_wb", "actual_q_wb", "predicted_d_wb", "predicted_q_wb"])
        for r in rows:
            writer.writerow([r[k] for k in keys]+r["actual_wb"]+r["predicted_wb"])
    print("current-analysis: "+json.dumps({k: v for k, v in data.items()
          if k not in {"rows", "geometry"}}), flush=True)


if __name__ == "__main__":
    main()
