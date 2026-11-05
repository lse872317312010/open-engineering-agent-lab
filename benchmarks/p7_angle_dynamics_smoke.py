"""Exercise angle-dependent dynamics against a synthetic periodic flux curve."""
import json
import math

from p7_angle_dynamics_simulation import OUT, main

OUT.mkdir(parents=True, exist_ok=True)
angles = (0., 5.625, 11.25, 16.875, 22.5, 28.125, 33.75, 39.375, 45.)
rows = [dict(angle_deg=angle, id_a=0, iq_a=0,
             actual_wb=[.065+.0002*math.cos(8*math.radians(angle)),
                        .0001*math.sin(8*math.radians(angle))]) for angle in angles]
(OUT / "fields.json").write_text(json.dumps(dict(evidence_passed=True, rows=rows)),
                                 encoding="utf-8")
(OUT / "model.json").write_text(json.dumps(
    dict(inductance_h=[[.0011, 0], [0, .00135]])), encoding="utf-8")
main()
result = json.loads((OUT / "dynamics.json").read_text())
assert result["passed"], result
assert all(len(case["rows"]) == 501 for case in result["cases"])
print("synthetic-dynamics-smoke: passed")
