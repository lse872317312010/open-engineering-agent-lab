"""Solve frozen mixed-current holdout cases using actual PYLEECAN/FEMM."""
import hashlib
import json
import math
import subprocess
import sys

import p7_pyleecan as base
from p7_loaded_solver import solve

from oeal.transforms import clarke, inverse_clarke, inverse_park, park

FRAME_SHA = "541602aad016740d7263493d6062244edfae0923c2b59a1ac349889547c9234f"
ANGLES = (0., 11.25, 22.5, 33.75)
PAIRS = ((0, .5), (0, -.5), (.5, 0), (-.5, 0),
         (1, 1), (1, -1), (-1, 1), (-1, -1))


def main():
    shard = int(sys.argv[1])
    assert shard in range(4)
    frozen = base.ROOT / "outputs/frozen-frame/frame.json"
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == FRAME_SHA
    frame = json.loads(frozen.read_text())
    base.geometry()
    (base.OUT / "frame.json").write_bytes(frozen.read_bytes())
    angle = ANGLES[shard]
    electrical = 4*math.radians(angle)+frame["offset_rad"]
    cases = []
    for i, (d, q) in enumerate(PAIRS):
        abc = inverse_clarke(*inverse_park(d, q, electrical))
        r = solve(f"loaded-{i}", 2., angle=angle, currents_abc=abc)
        alpha, beta, _ = clarke(*r["native_currents_a"])
        actual = park(alpha, beta, electrical)
        assert max(abs(actual[0]-d), abs(actual[1]-q)) <= 1e-10
        la, lb, zero = clarke(*r["flux_wb"])
        ld, lq = park(la, lb, electrical)
        r.update(id_a=d, iq_a=q, actual_id_a=actual[0], actual_iq_a=actual[1],
                 lambda_d_wb=ld, lambda_q_wb=lq, lambda_zero_wb=zero,
                 electrical_rad=electrical, fundamental_torque_nm=6*(ld*q-lq*d))
        cases.append(r)
    evidence = all(r["passed"] for r in cases)
    data = dict(evidence_passed=bool(evidence), shard=shard, frame_sha256=FRAME_SHA,
                cases=cases,
                commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
    base.write(base.OUT / "current-holdout.json", data)
    print("current-holdout: "+json.dumps({k: v for k, v in data.items() if k != "cases"}),
          flush=True)
    assert evidence


if __name__ == "__main__":
    main()
