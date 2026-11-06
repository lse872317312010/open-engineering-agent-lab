"""Frozen-model multi-period mechanical validation; no new field solves."""
import csv
import hashlib
import json
import math
import platform
import sys
from pathlib import Path

import numpy as np
import p7_cogging_model as cogging
import scipy
from p7_cogging_simulation import OUT, simulate


def main():
    fields = json.loads((OUT / "fields.json").read_text(encoding="utf-8"))
    path = OUT / "coenergy-model.json"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != fields["model_sha256"]:
        raise ValueError("frozen model SHA256 mismatch")
    parameters = json.loads(path.read_text(encoding="utf-8"))
    motor = cogging.CoggingMotor(
        cogging.FourierSeries(parameters["psi_a"], parameters["psi_b"]),
        cogging.FourierSeries(parameters["cog_a"], parameters["cog_b"]),
        parameters["inductance_h"])
    destination = OUT / "period-crossing"
    destination.mkdir(exist_ok=True)
    cases, refinements = [], {}
    for direction, name in ((1., "forward"), (-1., "reverse")):
        pair = []
        for dt, suffix in ((5e-6, "base"), (2.5e-6, "fine")):
            case = simulate(motor, direction, dt, initial_theta=.1, initial_omega=40*direction)
            case["name"] = name+"-"+suffix
            case["travel_periods"] = direction*(case["final_theta_rad"]-.1)/cogging.PERIOD
            with (destination / (case["name"]+".csv")).open(
                    "w", newline="", encoding="utf-8") as fp:
                writer = csv.DictWriter(fp, fieldnames=list(case["rows"][0]))
                writer.writeheader()
                writer.writerows(case["rows"])
            pair.append(case)
        if all(c["completed"] for c in pair):
            refinements[name] = {
                key: max(abs(a[key]-b[key]) for a, b in
                         zip(pair[0]["rows"], pair[1]["rows"], strict=True))
                for key in ("id_a", "iq_a", "theta_rad", "omega_rad_s")}
        cases.extend(pair)
    checks = dict(
        model_supported=bool(fields["model_supported"]),
        completed=all(c["completed"] and c["commands"] == 1000
                      and c["samples"] == 1001 for c in cases),
        crossing=all(c["travel_periods"] >= 2 for c in cases),
        replay=all(c["max_current_error_a"] <= 1e-4 and c["max_angle_error_rad"] <= 1e-5
                   and c["max_speed_error_rad_s"] <= 1e-3 for c in cases),
        refinement=len(refinements) == 2 and all(
            max(r["id_a"], r["iq_a"]) <= 1e-4 and r["theta_rad"] <= 1e-5
            and r["omega_rad_s"] <= 1e-3 for r in refinements.values()),
        energy=all(c["max_balance_j"] <= 1e-5 for c in cases),
        domain=all(c["max_l1_current_a"] <= 2 for c in cases),
        voltage=all(c["max_voltage_v"] <= 48/math.sqrt(3)+1e-12 for c in cases),
        model_frozen=hashlib.sha256(path.read_bytes()).hexdigest() == digest)
    data = dict(passed=all(checks.values()), checks=checks, refinement=refinements,
                model_sha256=digest, evidence_kind="model_simulated",
                python=sys.version, platform=platform.platform(), numpy=np.__version__,
                scipy=scipy.__version__,
                source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (
                    Path(__file__), Path(cogging.__file__),
                    Path(__file__).with_name("p7_cogging_simulation.py"))},
                cases=[{k: v for k, v in c.items() if k != "rows"} for c in cases])
    (destination / "summary.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(data, indent=2), flush=True)
    if not data["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
