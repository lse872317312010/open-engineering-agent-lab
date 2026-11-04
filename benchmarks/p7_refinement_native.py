"""Four independently solved midpoint angles per shard, without changing the model."""
import subprocess
import sys

import p7_pyleecan as p


def main():
    shard = int(sys.argv[1])
    assert shard in (0, 1, 2)
    geo = p.geometry()
    indices = list(range(2*shard*4+1, 2*(shard+1)*4, 2))
    results = [p.solve(f"refine-{i:02d}", 2., angle=3.75*i) for i in indices]
    p.write(p.OUT / "refinement.json", dict(
        shard=shard, indices=indices, cases=results, geometry_passed=geo["passed"],
        passed=all(r["passed"] for r in results),
        commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()))
    assert all(r["passed"] for r in results)


if __name__ == "__main__":
    main()
