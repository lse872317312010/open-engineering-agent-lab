"""Static actual-field and energy figure; no invented temperature surface."""
import csv
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from p7_stator_thermal import OUT
from p7_winding_heat import SOURCE, digest


def main():
    folder = OUT / "mesh-2/forward-base/half"
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    for path in (OUT / "summary.json", folder / "ledger.csv", folder / "field-snapshots.npz"):
        if digest(path) != manifest[path.relative_to(OUT).as_posix()]:
            raise ValueError("thermal figure source integrity failure")
    summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    with np.load(folder / "field-snapshots.npz", allow_pickle=False) as data:
        points, triangles = data["points"].T*1000, data["triangles"].T
        index = np.flatnonzero(np.isclose(data["time_s"], .05, rtol=0, atol=1e-12))[0]
        rise = data["rise_k"][index]*1e6
    with (folder / "ledger.csv").open(encoding="utf-8", newline="") as fp:
        raw = list(csv.DictReader(fp))
    rows = {k: np.array([float(r[k]) for r in raw]) for k in raw[0]}
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.7), layout="constrained")
    fig.suptitle("Public stator geometry | synthetic thermal materials | 50 ms copper pulse",
                 fontsize=14)
    field = axes[0].tripcolor(points[:, 0], points[:, 1], triangles, rise,
                              shading="gouraud", cmap="inferno", vmin=0)
    geometry = json.loads(SOURCE.read_text(encoding="utf-8"))["geometry"]
    for surface in geometry["surfaces"][1:25]:
        polygon = np.array(surface["points"]+[surface["points"][0]])*1000
        axes[0].plot(*polygon.T, color="#888888", lw=.25, alpha=.7)
    axes[0].set(aspect="equal", xlabel="x [mm]", ylabel="y [mm]",
                title="Actual FE temperature rise at 50 ms")
    fig.colorbar(field, ax=axes[0], label="Temperature rise [µK]", shrink=.8)
    for key, label in (("winding_c", "Winding mean"), ("core_c", "Core mean"),
                       ("peak_c", "Nodal peak")):
        axes[1].plot(rows["time_s"], (rows[key]-25)*1e6, label=label)
    axes[1].axvline(.05, color="#888888", ls="--", lw=.8)
    axes[1].set(xlabel="Time [s]", ylabel="Temperature rise [µK]",
                title="50 ms heating, then 1 s source-off replay")
    axes[1].legend(fontsize=8)
    for key, label in (("source_j", "Input copper energy"), ("stored_j", "Stored heat")):
        axes[2].plot(rows["time_s"], rows[key]*1000, label=label,
                      lw=2.5 if key == "source_j" else 1.,
                      ls="--" if key == "source_j" else "-")
    axes[2].set(xlabel="Time [s]", ylabel="Energy [mJ]", title="Discrete thermal energy ledger")
    axes[2].legend(fontsize=8)
    axes[2].text(.04, .1, f"Accepted: {summary['passed']}\n"
                 f"Mesh sensitivity: {summary['mesh_difference_k']:.2e} K\n"
                 f"Ambient heat out: {rows['ambient_out_j'][-1]*1e6:.3f} µJ\n"
                 "Very small rise; no measured accuracy claim",
                 transform=axes[2].transAxes, fontsize=8)
    for ax in axes[1:]:
        ax.grid(alpha=.2)
    fig.savefig(OUT / "stator-thermal.png", dpi=180)
    fig.savefig(OUT / "stator-thermal.svg")
    plt.close(fig)
    for name in ("stator-thermal.png", "stator-thermal.svg"):
        manifest[name] = digest(OUT / name)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
