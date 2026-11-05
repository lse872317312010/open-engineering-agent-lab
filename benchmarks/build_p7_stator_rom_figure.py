"""Actual boundary sensitivity, frozen holdout errors and measured inference times."""
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from p7_stator_rom_study import OUT
from p7_winding_heat import digest


def main():
    manifest = json.loads((OUT / "manifest.json").read_text())
    for name in ("training.npz", "summary.json", "validation.npz", "holdout.npz",
                 "step-times-ns.csv"):
        if digest(OUT / name) != manifest[name]:
            raise ValueError("ROM figure input integrity failure")
    summary = json.loads((OUT / "summary.json").read_text())
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), layout="constrained")
    fig.suptitle("Same-stator frozen ROM | preset mean-copper replay | synthetic materials")
    with np.load(OUT / "training.npz", allow_pickle=False) as data:
        for i, h in enumerate(data["h"]):
            axes[0].plot(np.arange(1201), data["outputs"][i, :, 0]-25,
                          label=f"h = {h:g} W/(m² K)")
    axes[0].axvline(600, color="#888888", ls="--", lw=.8)
    axes[0].set(xlabel="Replay time [s]", ylabel="Winding mean rise [K]",
                title="Full-order boundary sensitivity")
    axes[0].legend(fontsize=8)
    for name in ("validation", "holdout"):
        with np.load(OUT / (name+".npz"), allow_pickle=False) as data:
            error = (data["outputs"][::200, :2]-data["fom_dt_half"][:, :2])*1e6
            axes[1].plot(np.arange(len(error))*.5, error[:, 0], label=name+" winding")
            axes[1].plot(np.arange(len(error))*.5, error[:, 1], ls="--", label=name+" core")
    axes[1].axhline(100, color="#b33b3b", ls=":", label="Fixed 100 µK budget")
    axes[1].set(xlabel="Replay time [s]", ylabel="Mean temperature error [µK]",
                title="400 Hz ROM vs 0.5 s full-order model")
    axes[1].legend(fontsize=7)
    samples = np.loadtxt(OUT / "step-times-ns.csv", skiprows=1)/1000
    axes[2].hist(samples, bins=np.geomspace(min(samples), max(samples), 35), color="#356b87")
    axes[2].axvline(summary["p95_ns"]/1000, color="#d98426", ls="--", label="Measured p95")
    axes[2].set(xscale="log", xlabel="State update + four outputs [µs]", ylabel="Count",
                title=f"{summary['dimensions']} states; 5000 host timing samples")
    axes[2].legend(fontsize=8)
    axes[2].text(.97, .7, f"p95 = {summary['p95_ns']/1000:.1f} µs\n"
                 "Compute budget = 2500 µs\nNo wall-clock deadline proof",
                 ha="right", va="top", transform=axes[2].transAxes, fontsize=8)
    for axis in axes:
        axis.grid(alpha=.2)
    for suffix in ("png", "svg"):
        name = "stator-rom."+suffix
        fig.savefig(OUT / name, dpi=180)
        manifest[name] = digest(OUT / name)
    plt.close(fig)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
