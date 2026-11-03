"""Run actual zero-current PYLEECAN/FEMM cases for one frozen mesh lane."""
import json
import subprocess
import sys

import p7_pyleecan as p


def main():
    grid = float(sys.argv[1])
    if grid not in (1.0, 1.5, 2.0):
        raise ValueError("unknown mesh lane")
    geo = p.geometry()
    results = [p.solve(f"angle-{i:02d}", grid, angle=7.5*i) for i in range(13)]
    data = dict(grid=grid, cases=results, geometry_passed=geo["passed"],
                commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                passed=all(r["passed"] for r in results))
    p.write(p.OUT / "angle-lane.json", data)
    print("angle-lane: " + json.dumps(dict(grid=grid, count=len(results),
                                           passed=data["passed"])), flush=True)
    assert data["passed"]


if __name__ == "__main__":
    main()
