"""Partition actual native solves without changing equations, meshes or gates."""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys

import femm
import numpy as np
import p7_femm_nonlinear as n
from p7_femm_nonlinear_reference import BH


def commit():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def hashes(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob("*") if p.is_file() and p.name != "stage-manifest.json"}


def verify(folder, manifest):
    assert manifest and all(not p.startswith(("/", "../")) and "\\" not in p for p in manifest)
    assert all(hashlib.sha256((folder / p).read_bytes()).hexdigest() == h
               for p, h in manifest.items())


def main():
    stage = sys.argv[1]
    n.OUT.mkdir(parents=True, exist_ok=True)
    assert hashlib.sha256(n.Path(os.environ["FEMM_EXE"]).read_bytes()).hexdigest() == n.EXE_SHA
    if stage == "archive":
        folder = n.OUT / "worker-evidence" / sys.argv[2]
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("pip-install.json", "motulator-install.json", "installer-provenance.json",
                     "executable-version.txt"):
            path = n.OUT / name
            if path.exists():
                shutil.move(str(path), str(folder / name))
        n.write(folder / "source-host.json",
                dict(commit=commit(), platform=platform.platform(), cpu=platform.processor(),
                     exe_sha256=n.EXE_SHA, python=sys.version))
        (folder / "environment.txt").write_text(
            subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True))
        if sys.argv[2] == "material":
            root = n.Path(os.environ["FEMM_EXE"]).parents[1]
            for path in root.rglob("*"):
                if path.is_file() and any(k in path.name.lower()
                                          for k in ("license", "licence", "copyright")):
                    name = path.relative_to(root).as_posix().replace("/", "__")
                    shutil.copyfile(path, folder / name)
    elif stage == "material":
        femm.openfemm(1)
        try:
            rows = [n.uniform(h, b) for h in (2., 1., .5) for b in (1., 1.5, 2.)]
            reverse = n.uniform(.5, -1.5)
        finally:
            femm.closefemm()
        passed = all(r["passed"] for r in rows+[reverse])
        passed = passed and reverse["positive_direction_error"] > 1
        n.write(n.OUT / "material-validation.json",
                dict(passed=passed, cases=rows, reverse=reverse, commit=commit()))
        np.savetxt(n.OUT / "bh.csv", BH, delimiter=",", comments="", header="b_t,h_am")
        assert passed
    elif stage == "train":
        gi, ri = map(int, sys.argv[2:4])
        grid = n.core.GRIDS[gi+1]
        folder = n.OUT / f"grid{gi}"
        femm.openfemm(1)
        try:
            n.motor(grid)
            rows = [n.point(folder / f"train-{ri}-{j}", n.AXIS[ri], q, grid[0],
                            mst=gi == 1 and n.AXIS[ri] == 0 and abs(q) == 40)
                    for j, q in enumerate(n.AXIS)]
            femm.mi_close()
        finally:
            femm.closefemm()
        # Each partition owns disjoint native paths; same-run source identity is mandatory.
        native = {p: h for p, h in hashes(folder).items()
                  if p.startswith(f"train-{ri}-")}
        n.write(folder / f"part-{ri}.json",
                dict(commit=commit(), grid=gi, row=ri, rows=rows, manifest=native))
    elif stage == "freeze":
        material = json.loads((n.OUT / "material-validation.json").read_text())
        assert material["passed"] and material["commit"] == commit()
        for gi in range(2):
            folder = n.OUT / f"grid{gi}"
            rows = []
            for ri in range(5):
                part = json.loads((folder / f"part-{ri}.json").read_text())
                assert part["commit"] == commit() and part["grid"] == gi and part["row"] == ri
                verify(folder, part["manifest"])
                assert len([p for p in part["manifest"] if p.endswith((".fem", ".ans"))]) == 10
                assert [(r["id_a"], r["iq_a"]) for r in part["rows"]] == [
                    (n.AXIS[ri], q) for q in n.AXIS]
                rows.extend(part["rows"])
            values = np.array([n.flux(r) for r in rows]).reshape(5, 5, 2)
            assert np.all(np.isfinite(values))
            payload = dict(axis_a=n.AXIS, flux_wb=values.tolist(), training_points=25,
                           commit=commit(), evidence_level="model_simulated",
                           source_kind="synthetic",
                           interpolation="bounded bilinear; no extrapolation",
                           bh_table_si=BH.tolist())
            n.write(folder / "flux-map.json", payload)
            digest = hashlib.sha256((folder / "flux-map.json").read_bytes()).hexdigest()
            n.write(folder / "training-frozen.json",
                    dict(commit=commit(), map_sha256=digest, rows=rows))
        n.write(n.OUT / "stage-manifest.json", hashes(n.OUT))
        print("p7-nonlinear-training-frozen: both complete maps; holdouts not yet run", flush=True)
    elif stage == "validate":
        gi = int(sys.argv[2])
        verify(n.OUT, json.loads((n.OUT / "stage-manifest.json").read_text()))
        frozen = json.loads((n.OUT / f"grid{gi}/training-frozen.json").read_text())
        assert frozen["commit"] == commit()
        femm.openfemm(1)
        try:
            result = n.grid_case(gi, n.core.GRIDS[gi+1], frozen["rows"], frozen["map_sha256"])
        finally:
            femm.closefemm()
        assert result["passed"], result["checks"]
    elif stage == "assemble":
        verify(n.OUT, json.loads((n.OUT / "stage-manifest.json").read_text()))
        os.environ["OEAL_NL_ASSEMBLE"] = "1"
        n.main()
    else:
        raise ValueError(stage)


if __name__ == "__main__":
    main()
