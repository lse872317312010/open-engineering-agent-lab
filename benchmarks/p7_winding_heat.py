"""Map audited copper energy to gross winding volumes; no thermal field solve."""
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

from oeal.heat_sources import loss_windows, polygon_area_m2, uniform_volume_source

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/cogging-source/fields.json"
TRACES = ROOT / "outputs/p7-cogging-report/period-crossing"
OUT = ROOT / "outputs/p7-winding-heat"
SOURCE_SHA = "ecfe1e9c2235811dfbe28967bc4226da7e90fb06f7ac2a8fa9f8e0ab615fae6f"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if digest(SOURCE) != SOURCE_SHA:
        raise ValueError("audited geometry source SHA256 mismatch")
    geometry = json.loads(SOURCE.read_text(encoding="utf-8"))["geometry"]
    if not geometry["passed"]:
        raise ValueError("source geometry validation failed")
    surfaces = [s for s in geometry["surfaces"] if s["label"].startswith("Stator-0_Winding_")]
    labels = [s["label"] for s in surfaces]
    areas = np.array([polygon_area_m2(s["points"]) for s in surfaces])
    volumes = areas*.05
    area_error = abs(sum(areas)/geometry["reference"]["winding_m2"]-1)
    if len(labels) != 24 or area_error > .001:
        raise ValueError("24 regions and independent winding area agreement required")
    uniform_volume_source(labels, volumes, 0.)
    OUT.mkdir(exist_ok=True)
    rows, audits, inputs = [], [], {str(SOURCE.relative_to(ROOT)): SOURCE_SHA}
    for name in ("forward-base", "forward-fine", "reverse-base", "reverse-fine"):
        path = TRACES / (name+".csv")
        inputs[str(path.relative_to(ROOT))] = digest(path)
        with path.open(encoding="utf-8", newline="") as fp:
            trace = list(csv.DictReader(fp))
        if len(trace) != 1001:
            raise ValueError("full 1001-endpoint trace required")
        times = [float(r["time_s"]) for r in trace]
        copper = [float(r["copper_j"]) for r in trace]
        endpoints, energy = loss_windows(times, copper)
        deposited = 0.
        for i, joules in enumerate(energy):
            duration = endpoints[i+1]-endpoints[i]
            density, powers = uniform_volume_source(labels, volumes, joules/duration)
            region_energy = powers*duration
            error = abs(float(sum(region_energy))-float(joules))
            if error > 1e-12:
                raise ValueError("spatial deposition energy mismatch")
            deposited += float(sum(region_energy))
            audits.append(dict(case=name, window=i, start_s=float(endpoints[i]),
                               end_s=float(endpoints[i+1]), copper_j=float(joules),
                               deposited_j=float(sum(region_energy)), error_j=error))
            for label, volume, power in zip(labels, volumes, powers, strict=True):
                rows.append(dict(case=name, window=i, region=label, volume_m3=float(volume),
                                 source_w_m3=density, power_w=float(power),
                                 energy_j=float(power*duration)))
        if abs(deposited-(copper[-1]-copper[0])) > 1e-12:
            raise ValueError("cumulative source energy mismatch")
    for filename, data in (("regions.csv", rows), ("windows.csv", audits)):
        with (OUT / filename).open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
    summary = dict(passed=True, evidence_kind="model_simulated", thermal_solve=False,
                   assumption="all copper loss uniformly deposited in gross slot winding regions",
                   stack_length_m=.05, area_relative_error=area_error,
                   total_volume_m3=float(sum(volumes)), regions=24, windows=len(audits),
                   rows=len(rows), max_window_error_j=max(a["error_j"] for a in audits),
                   input_sha256=inputs,
                   output_sha256={n: digest(OUT / n) for n in ("regions.csv", "windows.csv")},
                   source_sha256={"benchmark": digest(Path(__file__)),
                                  "mapper": digest(ROOT / "src/oeal/heat_sources.py")})
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
