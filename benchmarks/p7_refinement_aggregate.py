"""Verify midpoint evidence and compare 12/24 point derivatives on the same FE mesh."""
import csv
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path, PurePosixPath

import numpy as np
from p7_angle_aggregate import read_lane
from p7_angle_reference import periodic_back_emf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-refinement-report"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    old, geometry, count = read_lane(2, 2.)
    subprocess.run(["git", "fetch", "origin", os.environ["ANGLE_FINE_COMMIT"],
                    "--depth=1"], check=True)
    subprocess.run(["git", "diff", "--exit-code", os.environ["ANGLE_FINE_COMMIT"],
                    "HEAD", "--", "benchmarks/p7_pyleecan.py",
                    "benchmarks/p7_pyleecan_reference.py",
                    "benchmarks/assets/pyleecan-spmsm001.json"], check=True)
    cases = {2*i: c for i, c in enumerate(old["cases"][:12])}
    manifests = [count]
    for shard in range(3):
        folder = ROOT / f"outputs/refined/refinement-{shard}"
        manifest = json.loads((folder / "manifest.json").read_text())
        for name, digest in manifest.items():
            assert not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts
            assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
        record = json.loads((folder / "refinement.json").read_text())
        assert record["commit"] == os.environ["REFINEMENT_COMMIT"]
        assert record["passed"] and record["geometry_passed"] and record["shard"] == shard
        expected = list(range(8*shard+1, 8*(shard+1), 2))
        assert record["indices"] == expected and len(record["cases"]) == 4
        natives = {n for n in manifest if n.endswith((".fem", ".ans"))}
        seen = set()
        for index, case in zip(expected, record["cases"], strict=True):
            assert index not in cases and case["angle_deg"] == index*3.75
            assert case["passed"] and all(case["checks"].values())
            assert case["grid"] == 2. and case["length_m"] == .05
            assert all(i == 0 for i in case["currents_a"])
            for name, digest in case["native_files"].items():
                assert name.startswith(f"refine-{index:02d}/")
                assert name in natives and manifest[name] == digest
                seen.add(name)
            cases[index] = case
        assert len(seen) == 8 and seen == natives
        manifests.append(len(manifest))
    assert sorted(cases) == list(range(24))
    ordered = [cases[i] for i in range(24)]
    flux = np.array([c["flux_wb"] for c in ordered])
    speed = 20*math.pi
    scale = speed*4*.05
    e24 = periodic_back_emf(flux, speed)
    e12 = periodic_back_emf(flux[::2], speed)
    e6 = periodic_back_emf(flux[::4], speed)
    previous = float(np.max(abs(e12[::2]-e6))/scale)
    difference = float(np.max(abs(e24[::2]-e12))/scale)
    harmonic = np.fft.fft(flux, axis=0)[1]*2/24
    phase = np.angle(harmonic/harmonic[0])
    phase_error = min(max(abs(phase[1]-2*math.pi/3), abs(phase[2]+2*math.pi/3)),
                      max(abs(phase[1]+2*math.pi/3), abs(phase[2]-2*math.pi/3)))
    algebra = float(max(np.max(abs(periodic_back_emf(flux, -speed)+e24)),
                        np.max(abs(periodic_back_emf(flux, 2*speed)-2*e24)))/scale)
    checks = dict(native=True, angle_step=difference <= .10 and difference < previous,
                  fundamental=bool(np.min(abs(harmonic)) > .01
                                   and phase_error <= math.radians(10)),
                  speed_scaling=algebra <= 1e-12)
    data = dict(passed=all(checks.values()), checks=checks, lanes=[dict(cases=ordered)],
                geometry=geometry, e12=[e24.tolist()], coarse_emf=e12.tolist(),
                angle_difference=difference, previous_difference=previous,
                difference_v=difference*scale, improvement=previous/difference,
                peak_v=float(np.max(abs(e24))), manifest_counts=manifests,
                fundamental_wb=abs(harmonic).tolist(), phase_deg=np.rad2deg(phase).tolist(),
                scale_v=scale, source_commit=os.environ["ANGLE_FINE_COMMIT"],
                fine_commit=os.environ["REFINEMENT_COMMIT"], source_run_id="41602596148",
                fine_run_id=os.environ["REFINEMENT_RUN"],
                report_commit=subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                      text=True).strip())
    (OUT / "angle-data.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    with (OUT / "angle-scan.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["relative_deg", "absolute_rad", "lambda_a", "lambda_b", "lambda_c",
                         "emf_a_600rpm", "emf_b_600rpm", "emf_c_600rpm", "source_commit"])
        for i, case in enumerate(ordered):
            source = data["source_commit"] if i % 2 == 0 else data["fine_commit"]
            writer.writerow([case["angle_deg"], case["actual_angle_rad"], *case["flux_wb"],
                             *e24[i], source])
    print("refinement-summary: "+json.dumps({k: v for k, v in data.items()
          if k not in {"lanes", "geometry", "e12", "coarse_emf"}}), flush=True)
    assert data["passed"], checks


if __name__ == "__main__":
    main()
