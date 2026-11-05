"""Audit loaded native meshes and compare with previously audited fine-mesh cases."""
import csv
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path, PurePosixPath

from p7_loaded_mesh_reference import compare

from oeal.transforms import clarke, park

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-loaded-mesh-report"
ANGLES = (0., 11.25, 22.5, 33.75)
PAIRS = ((0, 0), (0, 2), (1, 1), (-1, 1))
GRIDS = (1., 1.5, 2.)
FRAME = "541602aad016740d7263493d6062244edfae0923c2b59a1ac349889547c9234f"
EXE = "5e83cf0899cabae2017868ddcce338e3ba4ac25d1bf8e511eac77eda2bc92a21"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = os.environ["MESH_COMMIT"]
    subprocess.run(["git", "fetch", "origin", source, "--depth=1"], check=True)
    subprocess.run(["git", "diff", "--exit-code", source, "HEAD", "--",
                    "benchmarks/p7_loaded_mesh_native.py", "benchmarks/p7_loaded_solver.py",
                    "benchmarks/p7_pyleecan.py", "benchmarks/assets/pyleecan-spmsm001.json",
                    "src/oeal/transforms.py"], check=True)
    previous = json.loads((ROOT / "outputs/p7-current-report/validation.json").read_text())
    assert previous["evidence_passed"] and len(previous["rows"]) == 52
    records, counts = {}, []
    for shard in range(8):
        angle, grid = ANGLES[shard % 4], GRIDS[shard // 4]
        folder = ROOT / f"outputs/mesh/loaded-mesh-{shard}"
        manifest = json.loads((folder / "manifest.json").read_text())
        required = {"environment.json", "geometry.json", "frame.json", "loaded-mesh.json"}
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
        lane = json.loads((folder / "loaded-mesh.json").read_text())
        assert lane["evidence_passed"] and lane["shard"] == shard and lane["grid"] == grid
        assert lane["commit"] == source and lane["frame_sha256"] == FRAME
        assert len(lane["cases"]) == 4
        natives = {name for name in manifest if name.endswith((".fem", ".ans"))}
        seen = set()
        for i, (r, pair) in enumerate(zip(lane["cases"], PAIRS, strict=True)):
            assert r["angle_deg"] == angle and (r["id_a"], r["iq_a"]) == pair
            assert r["case"] == f"loaded-{i}" and r["grid"] == grid and r["length_m"] == .05
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
            records[(angle, pair, grid)] = dict(
                angle_deg=angle, id_a=pair[0], iq_a=pair[1], grid=grid,
                actual_id_a=actual[0], actual_iq_a=actual[1], actual_wb=list(flux),
                zero_wb=zero, fe_torque_nm=r["torque_nm"], nodes=r["nodes"],
                field=r["field"], phi_rad=r["phi_rad"], currents_a=r["native_currents_a"],
                actual_angle_rad=r["actual_angle_rad"], origin="new", commit=source)
        assert seen == natives and len(seen) == 8
        counts.append(len(manifest))
    for angle in ANGLES:
        for pair in PAIRS:
            matches = [r for r in previous["rows"] if r["angle_deg"] == angle
                       and (r["id_a"], r["iq_a"]) == pair]
            assert len(matches) == 1
            r = dict(matches[0])
            r["grid"], r["origin"] = 2., "reused"
            records[(angle, pair, 2.)] = r
    rows, comparisons = [], []
    for angle in ANGLES:
        for pair in PAIRS:
            selected = [records[(angle, pair, grid)] for grid in GRIDS]
            for r in selected:
                base = records[(angle, (0, 0), r["grid"])]["fe_torque_nm"]
                r["baseline_nm"] = base
                r["increment_nm"] = r["fe_torque_nm"]-base
                r["index"] = len(rows)
                rows.append(r)
            result = compare([r["actual_wb"] for r in selected],
                             [r["fe_torque_nm"] for r in selected],
                             [r["nodes"] for r in selected])
            result.update(angle_deg=angle, id_a=pair[0], iq_a=pair[1],
                          increment_diff_nm=[
                              abs(selected[i+1]["increment_nm"]-selected[i]["increment_nm"])
                              for i in range(2)])
            comparisons.append(result)
    assert len(rows) == 48 and len(comparisons) == 16
    data = dict(evidence_passed=True, mesh_supported=all(r["passed"] for r in comparisons),
                rows=rows, comparisons=comparisons, angles=ANGLES, grids=GRIDS,
                geometry=previous["geometry"], manifest_counts=counts,
                source_commit=source, source_run=os.environ["MESH_RUN"],
                failed_indices=[i for i, r in enumerate(comparisons) if not r["passed"]],
                max_flux_fine=max(r["flux_diff"][1] for r in comparisons),
                max_torque_fine_nm=max(r["torque_diff_nm"][1] for r in comparisons),
                max_increment_fine_nm=max(r["increment_diff_nm"][1] for r in comparisons),
                report_commit=subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                      text=True).strip())
    (OUT / "validation.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    with (OUT / "mesh.csv").open("w", newline="", encoding="utf-8") as fp:
        keys = ["angle_deg", "id_a", "iq_a", "grid", "actual_id_a", "actual_iq_a",
                "fe_torque_nm", "baseline_nm", "increment_nm", "nodes", "origin", "commit"]
        writer = csv.writer(fp)
        writer.writerow(keys+["actual_d_wb", "actual_q_wb"])
        for r in rows:
            writer.writerow([r[k] for k in keys]+r["actual_wb"])
    print("mesh-analysis: "+json.dumps({k: v for k, v in data.items()
          if k not in {"rows", "geometry", "comparisons"}}), flush=True)


if __name__ == "__main__":
    main()
