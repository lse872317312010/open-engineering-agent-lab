"""Audit medium-mesh spot checks at all actual loaded angle midpoints."""
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
ANGLES = (5.625, 16.875, 28.125, 39.375)
PAIRS = ((0, 0), (0, 2))
FRAME = "541602aad016740d7263493d6062244edfae0923c2b59a1ac349889547c9234f"
EXE = "5e83cf0899cabae2017868ddcce338e3ba4ac25d1bf8e511eac77eda2bc92a21"


def main():
    source = os.environ["MID_COMMIT"]
    subprocess.run(["git", "fetch", "origin", source, "--depth=1"], check=True)
    subprocess.run(["git", "diff", "--exit-code", source, "HEAD", "--",
                    "benchmarks/p7_midpoint_mesh_native.py", "benchmarks/p7_loaded_solver.py",
                    "benchmarks/p7_pyleecan.py", "benchmarks/assets/pyleecan-spmsm001.json",
                    "src/oeal/transforms.py"], check=True)
    fields = json.loads((OUT / "fields.json").read_text())
    assert fields["evidence_passed"]
    results, counts = [], []
    for shard, angle in enumerate(ANGLES):
        folder = ROOT / f"outputs/midpoint/midpoint-mesh-{shard}"
        manifest = json.loads((folder / "manifest.json").read_text())
        required = {"environment.json", "geometry.json", "frame.json", "midpoint-mesh.json"}
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
        lane = json.loads((folder / "midpoint-mesh.json").read_text())
        assert lane["evidence_passed"] and lane["shard"] == shard and lane["grid"] == 1.5
        assert lane["commit"] == source and lane["frame_sha256"] == FRAME
        assert len(lane["cases"]) == 2
        natives = {name for name in manifest if name.endswith((".fem", ".ans"))}
        seen = set()
        medium_base = lane["cases"][0]["torque_nm"]
        fine_base = next(r["fe_torque_nm"] for r in fields["rows"]
                         if r["angle_deg"] == angle and (r["id_a"], r["iq_a"]) == (0, 0))
        for i, (r, pair) in enumerate(zip(lane["cases"], PAIRS, strict=True)):
            assert r["angle_deg"] == angle and (r["id_a"], r["iq_a"]) == pair
            assert r["case"] == f"loaded-{i}" and r["grid"] == 1.5 and r["length_m"] == .05
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
            la, lb, _ = clarke(*r["flux_wb"])
            flux = park(la, lb, electrical)
            fine = next(v for v in fields["rows"] if v["angle_deg"] == angle
                        and (v["id_a"], v["iq_a"]) == pair)
            flux_error = math.dist(flux, fine["actual_wb"])/.05
            torque_error = abs(r["torque_nm"]-fine["fe_torque_nm"])
            results.append(dict(angle_deg=angle, id_a=pair[0], iq_a=pair[1],
                                medium_flux_wb=list(flux), fine_flux_wb=fine["actual_wb"],
                                medium_torque_nm=r["torque_nm"],
                                fine_torque_nm=fine["fe_torque_nm"],
                                medium_gap_torque_nm=r["gap_torque_nm"],
                                fine_gap_torque_nm=fine["gap_torque_nm"],
                                medium_nodes=r["nodes"], fine_nodes=fine["nodes"],
                                flux_error=flux_error, torque_error_nm=torque_error,
                                increment_error_nm=abs((r["torque_nm"]-medium_base)
                                    -(fine["fe_torque_nm"]-fine_base)),
                                passed=flux_error <= .03 and torque_error <= .05))
        assert seen == natives and len(seen) == 4
        counts.append(len(manifest))
    data = dict(evidence_passed=True, mesh_supported=all(r["passed"] for r in results),
                rows=results, manifest_counts=counts, source_commit=source,
                source_run=os.environ["MID_RUN"],
                max_flux_error=max(r["flux_error"] for r in results),
                max_torque_error_nm=max(r["torque_error_nm"] for r in results),
                max_increment_error_nm=max(r["increment_error_nm"] for r in results),
                failed_indices=[i for i, r in enumerate(results) if not r["passed"]])
    (OUT / "spot.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    with (OUT / "spot.csv").open("w", newline="", encoding="utf-8") as fp:
        keys = ["angle_deg", "id_a", "iq_a", "medium_torque_nm", "fine_torque_nm",
                "medium_gap_torque_nm", "fine_gap_torque_nm", "medium_nodes", "fine_nodes",
                "flux_error", "torque_error_nm", "increment_error_nm", "passed"]
        writer = csv.writer(fp)
        writer.writerow(keys)
        writer.writerows([[r[k] for k in keys] for r in results])
    print("midpoint-mesh-analysis: "+json.dumps({k: v for k, v in data.items() if k != "rows"}),
          flush=True)


if __name__ == "__main__":
    main()
