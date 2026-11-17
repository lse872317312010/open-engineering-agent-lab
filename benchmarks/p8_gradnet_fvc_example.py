"""Run the pinned upstream FEM GradNet flux-vector-control example."""
import hashlib
import json
import runpy
from importlib.metadata import version
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def main():
    upstream = Path("upstream-motulator")
    example = upstream / "examples/drive/flux_vector/plot_6kw_pmsyrm_gn_fvc_fem_harm.py"
    out = Path("outputs/p8-gradnet-fvc")
    out.mkdir(parents=True, exist_ok=True)
    data = runpy.run_path(str(example))
    result = data["res"]
    if not result.success:
        raise RuntimeError("upstream simulation failed")
    time = np.asarray(result.mdl.t)
    speed = np.asarray(result.mdl.machine.w_M)
    torque = np.asarray(result.mdl.machine.tau_M)
    if time[-1] < 1.749 or not all(np.isfinite(x).all() for x in (time, speed, torque)):
        raise ValueError("incomplete or nonfinite simulation output")
    np.savez_compressed(out / "trajectory.npz", time_s=time, speed_rad_s=speed, torque_nm=torque)
    figures = []
    for n in plt.get_fignums():
        name = f"upstream-figure-{n}.png"
        plt.figure(n).savefig(out / name, dpi=150, bbox_inches="tight")
        figures.append(name)
    inputs = [
        example,
        example.parent / "trained_models/baldor_fem_curr_map_harm_softmax_d48_sub10.npz",
        example.parent / "trained_models/baldor_fem_flux_map_pnorm_d12_sub20.npz",
    ]
    report = {
        "upstream_commit": "9971fcb77a08cc8d1f1603554a047ff5a59291e9",
        "inputs_sha256": {str(p.relative_to(upstream)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in inputs},
        "versions": {n: version(n) for n in ("motulator", "numpy", "scipy", "matplotlib")},
        "samples": len(time), "final_time_s": float(time[-1]),
        "final_speed_rad_s": float(speed[-1]), "final_torque_nm": float(torque[-1]),
        "figures": figures,
        "limitations": [
            "upstream pre-trained FEM models; not the project CSV importer or trained holdouts",
            "no independent physical accuracy or solver-stage domain verification",
            "no control optimization or inverter device nonlinearity",
        ],
    }
    (out / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
