"""Generate two further actual loaded angle refinements."""
import hashlib
import json
import math
import subprocess
import sys

import p7_pyleecan as base
from p7_loaded_solver import solve

from oeal.transforms import clarke, inverse_clarke, inverse_park, park

FRAME_SHA = "541602aad016740d7263493d6062244edfae0923c2b59a1ac349889547c9234f"
PAIRS = ((0, 0), (0, 2))


def main():
    shard = int(sys.argv[1])
    assert shard in range(16)
    frozen = base.ROOT / "outputs/frozen-frame/frame.json"
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == FRAME_SHA
    frame = json.loads(frozen.read_text())
    base.geometry()
    (base.OUT / "frame.json").write_bytes(frozen.read_bytes())
    stage, group = divmod(shard, 8)
    angles = ([1.40625+2.8125*(group*2+i) for i in range(2)] if stage == 0 else
              [.703125+1.40625*(group*4+i) for i in range(4)])
    cases = []
    for angle in angles:
        electrical = 4*math.radians(angle)+frame["offset_rad"]
        for d, q in PAIRS:
            abc = inverse_clarke(*inverse_park(d, q, electrical))
            r = solve(f"loaded-{len(cases)}", 2., angle=angle, currents_abc=abc)
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
    data = dict(evidence_passed=bool(evidence), shard=shard, stage=stage+3, grid=2.,
                frame_sha256=FRAME_SHA, cases=cases,
                commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
    base.write(base.OUT / "deep-angle.json", data)
    print("deep-angle: "+json.dumps({k: v for k, v in data.items() if k != "cases"}),
          flush=True)
    assert evidence


if __name__ == "__main__":
    main()
