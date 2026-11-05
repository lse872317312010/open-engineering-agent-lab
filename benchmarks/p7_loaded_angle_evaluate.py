"""Re-audit prior fields and actual loaded angular midpoint/closure evidence."""
import csv
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path, PurePosixPath

from p7_angular_reference import evaluate
from p7_local_flux_model import LocalFluxModel

from oeal.transforms import clarke, park

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-angle-dynamics"
NEW_ANGLES = (5.625, 16.875, 28.125, 39.375, 45.)
ANGLES = tuple(5.625*i for i in range(9))
PAIRS = ((0, 0), (0, 2), (1, 1), (-1, 1))
FRAME = "541602aad016740d7263493d6062244edfae0923c2b59a1ac349889547c9234f"
MODEL = "dc8c5ca77d55c7fe876d7c18da1ad897896c9e0289b5d940417984fec1a6068e"
EXE = "5e83cf0899cabae2017868ddcce338e3ba4ac25d1bf8e511eac77eda2bc92a21"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = os.environ["REFINE_COMMIT"]
    subprocess.run(["git", "fetch", "origin", source, "--depth=1"], check=True)
    subprocess.run(["git", "diff", "--exit-code", source, "HEAD", "--",
                    "benchmarks/p7_loaded_angle_native.py", "benchmarks/p7_loaded_solver.py",
                    "benchmarks/p7_pyleecan.py", "benchmarks/assets/pyleecan-spmsm001.json",
                    "src/oeal/transforms.py"], check=True)
    previous = json.loads((ROOT / "outputs/p7-current-report/validation.json").read_text())
    assert previous["evidence_passed"] and len(previous["rows"]) == 52
    frozen = ROOT / "outputs/frozen-model/model.json"
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == MODEL
    parameters = json.loads(frozen.read_text())
    model = LocalFluxModel(parameters["psi_wb"], parameters["inductance_h"])
    (OUT / "model.json").write_bytes(frozen.read_bytes())
    records, counts = {}, []
    for shard, angle in enumerate(NEW_ANGLES):
        folder = ROOT / f"outputs/refine/loaded-angle-{shard}"
        manifest = json.loads((folder / "manifest.json").read_text())
        required = {"environment.json", "geometry.json", "frame.json", "angle-refine.json"}
        assert required <= set(manifest)
        for name, digest in manifest.items():
            path = PurePosixPath(name)
            assert not path.is_absolute() and ".." not in path.parts
            assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
        assert hashlib.sha256((folder / "frame.json").read_bytes()).hexdigest() == FRAME
        frame = json.loads((folder / "frame.json").read_text())
        electrical = 4*math.radians(angle)+frame["offset_rad"]
        env = json.loads((folder / "environment.json").read_text())
        assert env["source_commit"] == source and env["executable_sha256"] == EXE
        geo = json.loads((folder / "geometry.json").read_text())
        assert geo["passed"] and all(geo["checks"].values())
        assert geo["asset_sha256"] == (
            "beba1fd4ed50e8c1d13743209a7e345ecd21a0ee9e64960c22a08924511cea06")
        lane = json.loads((folder / "angle-refine.json").read_text())
        assert lane["evidence_passed"] and lane["shard"] == shard and lane["grid"] == 2.
        assert lane["commit"] == source and lane["frame_sha256"] == FRAME
        assert len(lane["cases"]) == 4
        natives = {name for name in manifest if name.endswith((".fem", ".ans"))}
        seen = set()
        for i, (r, pair) in enumerate(zip(lane["cases"], PAIRS, strict=True)):
            assert r["angle_deg"] == angle and (r["id_a"], r["iq_a"]) == pair
            assert r["case"] == f"loaded-{i}" and r["grid"] == 2. and r["length_m"] == .05
            assert r["passed"] and all(r["checks"].values())
            assert abs(r["electrical_rad"]-electrical) <= 1e-12
            assert abs(r["actual_angle_rad"]-(math.pi/8+math.radians(angle))) <= 1e-12
            assert abs(r["native_depth_m"]-1.) <= 1e-12
            assert max(abs(a-.05*b) for a, b in zip(
                r["flux_wb"], r["native_flux_wb"], strict=True)) <= 1e-10
            assert abs(r["torque_nm"]-.05*r["native_torque_nm"]) <= 1e-10
            for name, digest in r["native_files"].items():
                assert name.startswith(r["case"]+"/") and name in natives
                assert manifest[name] == digest
                seen.add(name)
            alpha, beta, _ = clarke(*r["native_currents_a"])
            actual = park(alpha, beta, electrical)
            assert max(abs(actual[0]-pair[0]), abs(actual[1]-pair[1])) <= 1e-10
            la, lb, zero = clarke(*r["flux_wb"])
            flux = park(la, lb, electrical)
            records[(angle, pair)] = dict(
                angle_deg=angle, id_a=pair[0], iq_a=pair[1],
                actual_id_a=actual[0], actual_iq_a=actual[1], actual_wb=list(flux),
                zero_wb=zero, fe_torque_nm=r["torque_nm"],
                gap_torque_nm=r["gap_torque_nm"], nodes=r["nodes"],
                field=r["field"], phi_rad=r["phi_rad"], currents_a=r["native_currents_a"],
                actual_angle_rad=r["actual_angle_rad"], origin="new", commit=source)
        assert seen == natives and len(seen) == 8
        counts.append(len(manifest))
    for angle in (0., 11.25, 22.5, 33.75):
        for pair in PAIRS:
            matches = [r for r in previous["rows"] if r["angle_deg"] == angle
                       and (r["id_a"], r["iq_a"]) == pair]
            assert len(matches) == 1
            r = dict(matches[0])
            r["origin"] = "reused"
            records[(angle, pair)] = r
    rows = []
    for angle in ANGLES:
        base = records[(angle, (0, 0))]["fe_torque_nm"]
        for pair in PAIRS:
            r = records[(angle, pair)]
            r["index"] = len(rows)
            r["baseline_nm"] = base
            r["increment_nm"] = r["fe_torque_nm"]-base
            prediction = model.flux(pair)
            r["predicted_wb"] = prediction.tolist()
            r["predicted_torque_nm"] = float(6*(prediction[0]*pair[1]-prediction[1]*pair[0]))
            rows.append(r)
    gate = evaluate([r["actual_wb"] for r in rows], [r["predicted_wb"] for r in rows],
                    [r["increment_nm"] for r in rows], [r["predicted_torque_nm"] for r in rows])
    for i, r in enumerate(rows):
        r.update(flux_error=gate["flux_error"][i], torque_error_nm=gate["torque_error"][i],
                 supported=gate["supported"][i])
    comparisons = []
    for segment in range(4):
        a, m, b = ANGLES[2*segment:2*segment+3]
        for pair in PAIRS:
            left, mid, right = (records[(angle, pair)] for angle in (a, m, b))
            interp = [(left["actual_wb"][i]+right["actual_wb"][i])/2 for i in range(2)]
            flux_error = math.dist(mid["actual_wb"], interp)/.05
            torque_error = abs(mid["fe_torque_nm"]
                               -(left["fe_torque_nm"]+right["fe_torque_nm"])/2)
            comparisons.append(dict(angle_deg=m, id_a=pair[0], iq_a=pair[1],
                                    interp_wb=interp, flux_error=flux_error,
                                    torque_error_nm=torque_error,
                                    increment_error_nm=abs(mid["increment_nm"]
                                        -(left["increment_nm"]+right["increment_nm"])/2),
                                    passed=flux_error <= .02 and torque_error <= .10))
    endpoint = []
    for pair in PAIRS:
        a, b = records[(0., pair)], records[(45., pair)]
        endpoint.append(dict(id_a=pair[0], iq_a=pair[1],
                             flux_diff=math.dist(a["actual_wb"], b["actual_wb"]),
                             torque_diff_nm=abs(a["fe_torque_nm"]-b["fe_torque_nm"])))
    data = dict(evidence_passed=True, model_supported=gate["model_supported"],
                angle_supported=all(r["passed"] for r in comparisons),
                rows=rows, comparisons=comparisons, endpoint=endpoint, angles=ANGLES,
                geometry=previous["geometry"], manifest_counts=counts,
                model_sha256=MODEL, source_commit=source, source_run=os.environ["REFINE_RUN"],
                max_mid_flux=max(r["flux_error"] for r in comparisons),
                max_mid_torque_nm=max(r["torque_error_nm"] for r in comparisons),
                max_mid_increment_nm=max(r["increment_error_nm"] for r in comparisons),
                worst_mid_torque=max(comparisons, key=lambda r: r["torque_error_nm"]),
                max_model_flux=max(gate["flux_error"]),
                max_model_torque_nm=max(gate["torque_error"]),
                report_commit=subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                      text=True).strip())
    (OUT / "fields.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    with (OUT / "fields.csv").open("w", newline="", encoding="utf-8") as fp:
        keys = ["angle_deg", "id_a", "iq_a", "actual_id_a", "actual_iq_a",
                "fe_torque_nm", "baseline_nm", "increment_nm", "predicted_torque_nm",
                "flux_error", "torque_error_nm", "supported", "origin", "commit"]
        writer = csv.writer(fp)
        writer.writerow(keys+["actual_d_wb", "actual_q_wb", "predicted_d_wb", "predicted_q_wb"])
        for r in rows:
            writer.writerow([r[k] for k in keys]+r["actual_wb"]+r["predicted_wb"])
    print("loaded-angle-analysis: "+json.dumps({k: v for k, v in data.items()
          if k not in {"rows", "geometry", "comparisons"}}), flush=True)


if __name__ == "__main__":
    main()
