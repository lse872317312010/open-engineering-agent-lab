"""Plot the source electromagnetic torque from a documented magnetic point NPZ."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("output directory must be empty")
    with np.load(args.map, allow_pickle=False) as data:
        current = np.asarray(data["i_s_dq"]).flatten()
        torque = np.asarray(data["torque_total_nm"]).flatten()
        manifest = json.loads(str(data["manifest_json"]))
    if (not manifest.get("source_torque_included")
            or manifest["metadata"].get("torque_convention") != "electromagnetic_total_Nm"):
        raise ValueError("source torque convention must be explicitly declared")
    if (current.size < 4 or current.shape != torque.shape or not np.iscomplexobj(current)
            or not np.isfinite(current).all() or not np.isfinite(torque).all()):
        raise ValueError("invalid source current/torque arrays")
    import matplotlib.pyplot as plt

    args.output.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 5))
    points = ax.scatter(current.real, current.imag, c=torque, cmap="coolwarm", s=20)
    ax.set(xlabel="d-axis current (A peak)", ylabel="q-axis current (A peak)",
           title="Source electromagnetic torque: measured/exported points")
    fig.colorbar(points, ax=ax, label="Total electromagnetic torque (Nm)")
    fig.tight_layout()
    fig.savefig(args.output / "source-torque.png", dpi=160)
    plt.close(fig)
    np.savez_compressed(args.output / "source-torque-points.npz",
                        current_dq=current, torque_total_nm=torque)
    report = {"input_sha256": hashlib.sha256(args.map.read_bytes()).hexdigest(),
              "points": int(current.size), "minimum_torque_nm": float(np.min(torque)),
              "maximum_torque_nm": float(np.max(torque)),
              "source_metadata": manifest["metadata"],
              "limitations": ["source data points only; no interpolation or physical validation",
                              "no independent model torque comparison or angle resolution"]}
    (args.output / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
