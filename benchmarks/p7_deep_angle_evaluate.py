"""Audit two deeper loaded angle refinements and compare all four levels."""
import csv
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path, PurePosixPath

from oeal.transforms import clarke, park

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-angle-dynamics"
PAIRS = ((0, 0), (0, 2))
FRAME = "541602aad016740d7263493d6062244edfae0923c2b59a1ac349889547c9234f"
EXE = "5e83cf0899cabae2017868ddcce338e3ba4ac25d1bf8e511eac77eda2bc92a21"


def main():
    source = os.environ["DEEP_COMMIT"]
    subprocess.run(["git", "fetch", "origin", source, "--depth=1"], check=True)
    subprocess.run(["git", "diff", "--exit-code", source, "HEAD", "--",
                    "benchmarks/p7_deep_angle_native.py", "benchmarks/p7_loaded_solver.py",
                    "benchmarks/p7_pyleecan.py", "benchmarks/assets/pyleecan-spmsm001.json",
                    "src/oeal/transforms.py"], check=True)
    previous = json.loads((OUT / "second.json").read_text())
    assert previous["evidence_passed"] and len(previous["rows"]) == 34
    records, counts = {}, []
    for r in previous["rows"]:
        item = dict(r)
        item["origin"] = "reused"
        records[(item["angle_deg"], (item["id_a"], item["iq_a"]))] = item
    for shard in range(16):
        stage, group = divmod(shard, 8)
        angles = ([1.40625+2.8125*(group*2+i) for i in range(2)] if stage == 0 else
                  [.703125+1.40625*(group*4+i) for i in range(4)])
        expected = [(angle, pair) for angle in angles for pair in PAIRS]
        folder = ROOT / f"outputs/deep/deep-angle-{shard}"
        manifest = json.loads((folder / "manifest.json").read_text())
        required = {"environment.json", "geometry.json", "frame.json", "deep-angle.json"}
        assert required <= set(manifest)
        for name, digest in manifest.items():
            path = PurePosixPath(name)
            assert not path.is_absolute() and ".." not in path.parts
            assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
        assert hashlib.sha256((folder / "frame.json").read_bytes()).hexdigest() == FRAME
        frame = json.loads((folder / "frame.json").read_text())
        env = json.loads((folder / "environment.json").read_text())
        assert env["source_commit"] == source and env["executable_sha256"] == EXE
        geo = json.loads((folder / "geometry.json").read_text())
        assert geo["passed"] and all(geo["checks"].values())
        assert geo["asset_sha256"] == (
            "beba1fd4ed50e8c1d13743209a7e345ecd21a0ee9e64960c22a08924511cea06")
        lane = json.loads((folder / "deep-angle.json").read_text())
        assert lane["evidence_passed"] and lane["shard"] == shard and lane["grid"] == 2.
        assert lane["stage"] == stage+3 and lane["commit"] == source
        assert lane["frame_sha256"] == FRAME and len(lane["cases"]) == len(expected)
        natives = {name for name in manifest if name.endswith((".fem", ".ans"))}
        seen = set()
        for i, (r, (angle, pair)) in enumerate(zip(lane["cases"], expected, strict=True)):
            electrical = 4*math.radians(angle)+frame["offset_rad"]
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
            assert (angle, pair) not in records
            records[(angle, pair)] = dict(
                angle_deg=angle, id_a=pair[0], iq_a=pair[1], actual_wb=list(flux),
                actual_id_a=actual[0], actual_iq_a=actual[1],
                zero_wb=zero, fe_torque_nm=r["torque_nm"],
                gap_torque_nm=r["gap_torque_nm"], nodes=r["nodes"], field=r["field"],
                phi_rad=r["phi_rad"], currents_a=r["native_currents_a"],
                actual_angle_rad=r["actual_angle_rad"], origin="new", commit=source)
        assert seen == natives and len(seen) == 2*len(expected)
        counts.append(len(manifest))
    angles = tuple(.703125*i for i in range(65))
    rows = []
    for angle in angles:
        baseline = records[(angle, (0, 0))]["fe_torque_nm"]
        for pair in PAIRS:
            r = records[(angle, pair)]
            r["index"] = len(rows)
            r["baseline_nm"] = baseline
            r["increment_nm"] = r["fe_torque_nm"]-baseline
            rows.append(r)
    levels = []
    for width, divisions in ((2.8125, 16), (1.40625, 32)):
        comparisons = []
        for segment in range(divisions):
            a, m, b = (width*segment, width*(segment+.5), width*(segment+1))
            for pair in PAIRS:
                left, mid, right = (records[(angle, pair)] for angle in (a, m, b))
                pred = [(left["actual_wb"][i]+right["actual_wb"][i])/2 for i in range(2)]
                df = math.dist(mid["actual_wb"], pred)/.05
                dt = abs(mid["fe_torque_nm"]-(left["fe_torque_nm"]+right["fe_torque_nm"])/2)
                di = abs(mid["increment_nm"]-(left["increment_nm"]+right["increment_nm"])/2)
                comparisons.append(dict(angle_deg=m, id_a=pair[0], iq_a=pair[1],
                                        flux_error=df, torque_error_nm=dt, increment_error_nm=di,
                                        passed=df <= .02 and dt <= .10))
        levels.append(dict(coarse_step_deg=width, midpoint_step_deg=width/2,
                           supported=all(r["passed"] for r in comparisons),
                           max_flux=max(r["flux_error"] for r in comparisons),
                           max_torque_nm=max(r["torque_error_nm"] for r in comparisons),
                           max_increment_nm=max(r["increment_error_nm"] for r in comparisons),
                           failed_indices=[i for i, r in enumerate(comparisons) if not r["passed"]],
                           comparisons=comparisons))
    prior = [dict(coarse_step_deg=11.25, midpoint_step_deg=5.625,
                  supported=all(r["passed"] for r in previous["previous_comparisons"]),
                  max_flux=previous["coarse_max_flux"],
                  max_torque_nm=previous["coarse_max_torque_nm"],
                  max_increment_nm=previous["coarse_max_increment_nm"],
                  comparisons=previous["previous_comparisons"]),
             dict(coarse_step_deg=5.625, midpoint_step_deg=2.8125,
                  supported=previous["angle_supported"], max_flux=previous["fine_max_flux"],
                  max_torque_nm=previous["fine_max_torque_nm"],
                  max_increment_nm=previous["fine_max_increment_nm"],
                  comparisons=previous["comparisons"])]
    assert len(rows) == 130 and len(levels[0]["comparisons"]) == 32
    assert len(levels[1]["comparisons"]) == 64
    data = dict(evidence_passed=True, rows=rows, angles=angles, levels=prior+levels,
                manifest_counts=counts, source_commit=source, source_run=os.environ["DEEP_RUN"])
    (OUT / "deep.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    with (OUT / "deep.csv").open("w", newline="", encoding="utf-8") as fp:
        keys = ["angle_deg", "id_a", "iq_a", "actual_id_a", "actual_iq_a", "fe_torque_nm",
                "baseline_nm", "increment_nm", "origin", "commit"]
        writer = csv.writer(fp)
        writer.writerow(keys+["actual_d_wb", "actual_q_wb"])
        for r in rows:
            writer.writerow([r[k] for k in keys]+r["actual_wb"])
    print("deep-angle-analysis: "+json.dumps(
        dict(evidence_passed=True, manifest_counts=counts, source_commit=source,
             source_run=os.environ["DEEP_RUN"],
             levels=[{k: v for k, v in level.items() if k != "comparisons"}
                     for level in prior+levels])), flush=True)


if __name__ == "__main__":
    main()
