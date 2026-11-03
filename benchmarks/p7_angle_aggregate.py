"""Verify three immutable native archives and derive quasi-static back EMF."""
import csv
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path, PurePosixPath

import numpy as np
from p7_angle_reference import periodic_back_emf

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/angle-lanes"
OUT = ROOT / "outputs/p7-angle-report"
SPEED = 600 * 2 * math.pi / 60
SCALE = SPEED * 4 * .05


def read_lane(index, grid):
    folder = SOURCE / f"angle-lane-{index}"
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest
    for name, digest in manifest.items():
        assert not name.startswith("/") and ".." not in PurePosixPath(name).parts
        path = folder / name
        assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest
    lane = json.loads((folder / "angle-lane.json").read_text())
    assert lane["grid"] == grid and lane["passed"] and lane["geometry_passed"]
    expected = os.environ["ANGLE_FINE_COMMIT"] if index == 2 else os.environ["ANGLE_SOURCE_COMMIT"]
    assert lane["commit"] == expected
    assert len(lane["cases"]) == 13
    natives = {name for name in manifest if name.endswith((".fem", ".ans"))}
    assert len(natives) == 26
    seen_native = set()
    for i, case in enumerate(lane["cases"]):
        assert case["case"] == f"angle-{i:02d}" and case["angle_deg"] == 7.5*i
        assert case["grid"] == grid and case["passed"] and all(case["checks"].values())
        assert len(case["native_files"]) == 2
        for name, digest in case["native_files"].items():
            assert name.startswith(case["case"] + "/")
            assert name in natives and manifest[name] == digest
            seen_native.add(name)
    assert seen_native == natives
    return lane, json.loads((folder / "geometry.json").read_text()), len(manifest)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    loaded = [read_lane(i, g) for i, g in enumerate((1., 1.5, 2.))]
    lanes = [item[0] for item in loaded]
    flux = np.array([[r["flux_wb"] for r in lane["cases"]] for lane in lanes])
    nodes = [lane["cases"][0]["nodes"] for lane in lanes]
    e12 = np.array([periodic_back_emf(v[:12], SPEED) for v in flux])
    e6 = np.array([periodic_back_emf(v[:12:2], SPEED) for v in flux])
    closure = np.linalg.norm(flux[:, 12] - flux[:, 0], axis=1) / .05
    mesh_flux = float(np.max(np.linalg.norm(flux[1, :12]-flux[2, :12], axis=1))/.05)
    mesh_emf = float(np.max(np.abs(e12[1]-e12[2]))/SCALE)
    angle_error = [float(np.max(np.abs(e12[i, ::2]-e6[i]))/SCALE) for i in range(3)]
    harmonic = np.fft.fft(flux[2, :12], axis=0)[1] * (2/12)
    amplitudes = np.abs(harmonic)
    phase = np.angle(harmonic / harmonic[0])
    phase_b, phase_c = float(phase[1]), float(phase[2])
    phase_error = min(max(abs(phase_b-2*math.pi/3), abs(phase_c+2*math.pi/3)),
                      max(abs(phase_b+2*math.pi/3), abs(phase_c-2*math.pi/3)))
    reverse = periodic_back_emf(flux[2, :12], -SPEED)
    double = periodic_back_emf(flux[2, :12], 2*SPEED)
    speed_error = float(max(np.max(abs(reverse+e12[2])),
                            np.max(abs(double-2*e12[2])))/SCALE)
    checks = dict(native=True, mesh_nodes=all(a < b for a, b in zip(
                      nodes[:-1], nodes[1:], strict=True)),
                  closure=bool(np.max(closure) <= .02), mesh_flux=mesh_flux <= .03,
                  mesh_emf=mesh_emf <= .05, angle_step=max(angle_error[1:]) <= .30,
                  fundamental=bool(np.min(amplitudes) > .01 and phase_error <= math.radians(10)),
                  speed_scaling=speed_error <= 1e-12)
    data = dict(passed=all(checks.values()), checks=checks, nodes=nodes,
                closure=closure.tolist(), mesh_flux=mesh_flux, mesh_emf=mesh_emf,
                angle_error=angle_error, fundamental_wb=amplitudes.tolist(),
                phase_deg=np.rad2deg(phase).tolist(), phase_error_deg=math.degrees(phase_error),
                speed_error=speed_error, scale_v=SCALE, speed_rad_s=SPEED,
                lanes=lanes, geometry=loaded[2][1],
                manifest_counts=[x[2] for x in loaded],
                source_commit=os.environ["ANGLE_SOURCE_COMMIT"],
                fine_commit=os.environ["ANGLE_FINE_COMMIT"],
                fine_run_id=os.environ["ANGLE_FINE_RUN"],
                report_commit=subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                      text=True).strip(),
                source_run_id=os.environ.get("ANGLE_SOURCE_RUN", os.environ["GITHUB_RUN_ID"]),
                e12=e12.tolist(), e6=e6.tolist())
    with (OUT / "angle-data.json").open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
    with (OUT / "angle-scan.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["grid", "relative_angle_deg", "actual_angle_rad", "nodes",
                         "lambda_a_wb", "lambda_b_wb", "lambda_c_wb",
                         "torque_nm", "emf_a_v_600rpm", "emf_b_v_600rpm",
                         "emf_c_v_600rpm"])
        for j, lane in enumerate(lanes):
            for i, r in enumerate(lane["cases"]):
                writer.writerow([lane["grid"], r["angle_deg"], r["actual_angle_rad"], r["nodes"],
                                 *r["flux_wb"], r["torque_nm"],
                                 *(e12[j, i] if i < 12 else ["", "", ""])])
    print("angle-summary: " + json.dumps({k: v for k, v in data.items()
                                          if k not in {"lanes", "geometry", "e12", "e6"}}),
          flush=True)
    assert data["passed"], checks


if __name__ == "__main__":
    main()
