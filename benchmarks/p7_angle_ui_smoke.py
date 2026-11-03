"""Prepare explicitly synthetic report-only fixture; never accepted as physical evidence."""
import json
import math
from pathlib import Path

from p7_angle_reference import periodic_back_emf

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/angle-lanes"
OUT = ROOT / "outputs/p7-angle-report"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    lanes = [json.loads((SOURCE / f"angle-lane-{i}/angle-lane.json").read_text())
             for i in (0, 1)]
    lanes.append(lanes[1])
    geometry = json.loads((SOURCE / "angle-lane-1/geometry.json").read_text())
    flux = [[r["flux_wb"] for r in lane["cases"][:12]] for lane in lanes]
    speed = 600*2*math.pi/60
    data = dict(passed=True, fixture_only=True, checks={"native": False}, lanes=lanes,
                geometry=geometry,
                e12=[periodic_back_emf(v, speed).tolist() for v in flux],
                e6=[periodic_back_emf(v[::2], speed).tolist() for v in flux],
                mesh_flux=0., mesh_emf=0., angle_error=[0., 0., 0.],
                scale_v=speed*4*.05, fundamental_wb=[.06, .06, .06],
                phase_deg=[0., -120., 120.], source_commit="synthetic-fixture",
                fine_commit="synthetic-fixture", report_commit="synthetic-fixture",
                source_run_id="41601354282", fine_run_id="41601354282")
    (OUT / "angle-data.json").write_text(json.dumps(data), encoding="utf-8")
    (OUT / "angle-scan.csv").write_text("fixture_only\ntrue\n", encoding="utf-8")
    print("synthetic UI smoke fixture; not an accepted physical result", flush=True)


if __name__ == "__main__":
    main()
