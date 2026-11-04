"""Apply frozen dq currents at two actual rotor positions and retain native solutions."""
import hashlib
import json
import math
import subprocess
import sys

import p7_pyleecan as base
from p7_loaded_solver import solve

from oeal.transforms import clarke, inverse_clarke, inverse_park, park

FRAME_SHA = "541602aad016740d7263493d6062244edfae0923c2b59a1ac349889547c9234f"


def main():
    shard = int(sys.argv[1])
    assert shard in (0, 1)
    frozen = base.ROOT / "outputs/frozen-frame/frame.json"
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == FRAME_SHA
    frame = json.loads(frozen.read_text())
    base.geometry()
    (base.OUT / "frame.json").write_bytes(frozen.read_bytes())
    angle = 22.5*shard
    electrical = 4*math.radians(angle)+frame["offset_rad"]
    cases = []
    for i, (d, q) in enumerate(((0, 0), (0, 2), (0, -2), (2, 0), (-2, 0))):
        abc = inverse_clarke(*inverse_park(d, q, electrical))
        r = solve(f"loaded-{i}", 2., angle=angle, currents_abc=abc)
        alpha, beta, _ = clarke(*r["currents_a"])
        actual = park(alpha, beta, electrical)
        assert max(abs(actual[0]-d), abs(actual[1]-q)) <= 1e-10
        la, lb, zero = clarke(*r["flux_wb"])
        ld, lq = park(la, lb, electrical)
        r.update(id_a=d, iq_a=q, lambda_d_wb=ld, lambda_q_wb=lq, lambda_zero_wb=zero,
                 electrical_rad=electrical, fundamental_torque_nm=6*(ld*q-lq*d))
        cases.append(r)
    baseline = cases[0]["torque_nm"]
    for r in cases:
        r["increment_nm"] = r["torque_nm"]-baseline
        r["formula_error_nm"] = abs(r["increment_nm"]-r["fundamental_torque_nm"])
    checks = dict(points=all(r["passed"] for r in cases),
                  positive=cases[1]["increment_nm"] > .5,
                  negative=cases[2]["increment_nm"] < -.5,
                  direct=max(abs(cases[i]["increment_nm"]) for i in (3, 4)) <= .10,
                  formula=max(r["formula_error_nm"] for r in cases) <= .10,
                  frozen=hashlib.sha256(frozen.read_bytes()).hexdigest() == FRAME_SHA)
    data = dict(passed=all(checks.values()), checks=checks, shard=shard,
                frame_sha256=FRAME_SHA, cases=cases,
                commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
    base.write(base.OUT / "loaded.json", data)
    print("loaded-summary: "+json.dumps({k: v for k, v in data.items() if k != "cases"}),
          flush=True)
    assert data["passed"], checks


if __name__ == "__main__":
    main()
