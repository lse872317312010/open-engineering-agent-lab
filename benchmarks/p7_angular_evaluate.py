"""Audit actual angular load cases and test the unchanged frozen local model."""
import csv
import hashlib
import json
import os
import subprocess
from pathlib import Path, PurePosixPath

import numpy as np
from p7_angular_reference import evaluate
from p7_local_flux_model import LocalFluxModel

from oeal.transforms import clarke, park

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-angular-report"
ANGLES = (11.25, 33.75, 45., 56.25, 67.5, 78.75)
PAIRS = ((0, 0), (0, 2), (0, -2), (2, 0), (-2, 0))
MODEL_SHA = "dc8c5ca77d55c7fe876d7c18da1ad897896c9e0289b5d940417984fec1a6068e"
FRAME_SHA = "541602aad016740d7263493d6062244edfae0923c2b59a1ac349889547c9234f"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frozen_path = ROOT / "outputs/frozen-model/model.json"
    assert hashlib.sha256(frozen_path.read_bytes()).hexdigest() == MODEL_SHA
    parameters = json.loads(frozen_path.read_text())
    model = LocalFluxModel(parameters["psi_wb"], parameters["inductance_h"])
    (OUT / "model.json").write_bytes(frozen_path.read_bytes())
    native_commit = os.environ["ANGULAR_COMMIT"]
    subprocess.run(["git", "fetch", "origin", native_commit, "--depth=1"], check=True)
    subprocess.run(["git", "diff", "--exit-code", native_commit, "HEAD", "--",
                    "benchmarks/p7_angular_native.py", "benchmarks/p7_loaded_solver.py",
                    "benchmarks/p7_pyleecan.py", "src/oeal/transforms.py",
                    "benchmarks/assets/pyleecan-spmsm001.json"], check=True)
    old = json.loads((ROOT / "outputs/p7-loaded-report/validation.json").read_text())
    assert old["passed"] and len(old["rows"]) == 10
    records = [(r, "reused", old["source_commit"]) for r in old["rows"]]
    counts = old["manifest_counts"].copy()
    geometry = None
    for shard, angle in enumerate(ANGLES):
        folder = ROOT / f"outputs/angular/angular-{shard}"
        manifest = json.loads((folder / "manifest.json").read_text())
        assert manifest
        for name, digest in manifest.items():
            assert not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts
            assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
        lane = json.loads((folder / "angular.json").read_text())
        assert lane["evidence_passed"] and lane["shard"] == shard
        assert lane["commit"] == native_commit and lane["frame_sha256"] == FRAME_SHA
        assert len(lane["cases"]) == 5
        assert hashlib.sha256((folder / "frame.json").read_bytes()).hexdigest() == FRAME_SHA
        env = json.loads((folder / "environment.json").read_text())
        assert env["source_commit"] == native_commit
        assert env["executable_sha256"] == (
            "5e83cf0899cabae2017868ddcce338e3ba4ac25d1bf8e511eac77eda2bc92a21")
        geo = json.loads((folder / "geometry.json").read_text())
        assert geo["passed"] and all(geo["checks"].values())
        assert geo["asset_sha256"] == (
            "beba1fd4ed50e8c1d13743209a7e345ecd21a0ee9e64960c22a08924511cea06")
        geometry = geo
        natives = {n for n in manifest if n.endswith((".fem", ".ans"))}
        seen = set()
        for i, (r, pair) in enumerate(zip(lane["cases"], PAIRS, strict=True)):
            assert r["angle_deg"] == angle and (r["id_a"], r["iq_a"]) == pair
            assert r["case"] == f"loaded-{i}"
            assert r["passed"] and all(r["checks"].values())
            assert r["grid"] == 2. and r["length_m"] == .05
            for name, digest in r["native_files"].items():
                assert name.startswith(r["case"]+"/") and name in natives
                assert manifest[name] == digest
                seen.add(name)
            records.append((r, "new", native_commit))
        assert seen == natives and len(seen) == 10
        counts.append(len(manifest))
    rows = []
    angles = [11.25*i for i in range(8)]
    assert len(records) == 40
    for angle in angles:
        selected = [r for r in records if r[0]["angle_deg"] == angle]
        assert len(selected) == 5
        baseline = next(r[0]["torque_nm"] for r in selected
                        if (r[0]["id_a"], r[0]["iq_a"]) == (0, 0))
        for pair in PAIRS:
            matches = [r for r in selected if (r[0]["id_a"], r[0]["iq_a"]) == pair]
            assert len(matches) == 1
            r, origin, commit = matches[0]
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
                             origin=origin, commit=commit, currents_a=r["native_currents_a"],
                             nodes=r["nodes"], field=r["field"], phi_rad=r["phi_rad"],
                             actual_angle_rad=r["actual_angle_rad"]))
    gate = evaluate([r["actual_wb"] for r in rows], [r["predicted_wb"] for r in rows],
                    [r["increment_nm"] for r in rows], [r["predicted_torque_nm"] for r in rows])
    for i, r in enumerate(rows):
        r.update(flux_error=gate["flux_error"][i], torque_error_nm=gate["torque_error"][i],
                 supported=gate["supported"][i])
    envelopes = [dict(angle_deg=angle,
                      flux_error=max(r["flux_error"] for r in rows if r["angle_deg"] == angle),
                      torque_error_nm=max(r["torque_error_nm"] for r in rows
                                          if r["angle_deg"] == angle))
                 for angle in angles]
    assert hashlib.sha256(frozen_path.read_bytes()).hexdigest() == MODEL_SHA
    data = dict(evidence_passed=True, model_supported=gate["model_supported"],
                failed_indices=gate["failed_indices"], rows=rows, angles=angles,
                geometry=geometry, envelopes=envelopes, manifest_counts=counts,
                native_files=80, new_cases=30, reused_cases=10, model_sha256=MODEL_SHA,
                max_flux_error=max(gate["flux_error"]),
                max_torque_error_nm=max(gate["torque_error"]),
                source_commit=native_commit, source_run=os.environ["ANGULAR_RUN"],
                report_commit=subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                      text=True).strip())
    (OUT / "validation.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    with (OUT / "angular.csv").open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow(["angle_deg", "id_a", "iq_a", "actual_id_a", "actual_iq_a",
                         "actual_d_wb", "actual_q_wb", "predicted_d_wb", "predicted_q_wb",
                         "flux_error_over_0p05wb", "fe_torque_nm", "baseline_nm", "increment_nm",
                         "predicted_torque_nm", "raw_formula_nm", "torque_error_nm",
                         "supported", "origin", "commit"])
        for r in rows:
            writer.writerow([r["angle_deg"], r["id_a"], r["iq_a"], r["actual_id_a"],
                             r["actual_iq_a"], *r["actual_wb"], *r["predicted_wb"],
                             *[r[k] for k in ("flux_error", "fe_torque_nm", "baseline_nm",
                                              "increment_nm", "predicted_torque_nm",
                                              "raw_formula_nm", "torque_error_nm", "supported",
                                              "origin", "commit")]])
    print("angular-analysis: "+json.dumps({k:v for k, v in data.items()
          if k not in {"rows", "geometry"}}), flush=True)


if __name__ == "__main__":
    main()
