"""Replay actual simulated copper-energy windows into frozen stator FE and ROM."""
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from p7_stator_rom_study import OUT as ROM
from p7_stator_rom_study import load_fom
from p7_winding_heat import OUT as HEAT
from p7_winding_heat import ROOT, digest
from scipy.sparse import diags
from scipy.sparse.linalg import factorized

from oeal.stator_rom import StatorThermalROM

OUT = ROOT / "outputs/p7-electric-thermal-replay"
CASES = ("forward-base", "forward-fine", "reverse-base", "reverse-fine")
DT = .0025


def window_power(rows, case, upper):
    selected = [r for r in rows if r["case"] == case]
    if len(selected) != 20:
        raise ValueError("twenty complete copper windows required")
    values = []
    for i, row in enumerate(selected):
        start, end, energy = (float(row[k]) for k in ("start_s", "end_s", "copper_j"))
        deposited, error = float(row["deposited_j"]), float(row["error_j"])
        if (int(row["window"]) != i or not np.isfinite([start, end, energy, deposited, error]).all()
                or abs(start-i*DT) > 1e-10 or abs(end-(i+1)*DT) > 1e-10
                or energy < 0 or abs(deposited-energy) > 1e-12 or abs(error) > 1e-12):
            raise ValueError("invalid copper window")
        power = energy/DT
        if power > upper:
            raise ValueError("copper power outside frozen ROM domain")
        values.append(power)
    return np.array(values)


def main():
    frozen_path = ROM / "frozen.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    if not frozen["passed"]:
        raise ValueError("training failed")
    for name, expected in frozen["frozen_sha256"].items():
        if digest(ROM / name) != expected:
            raise ValueError("frozen ROM integrity failure")
    if digest(ROOT / "src/oeal/stator_rom.py") != frozen["inference_api_sha256"]:
        raise ValueError("frozen inference implementation changed")
    source = json.loads((HEAT / "summary.json").read_text(encoding="utf-8"))
    if not source["passed"] or digest(HEAT / "windows.csv") != source["output_sha256"]["windows.csv"]:
        raise ValueError("copper source integrity failure")
    with (HEAT / "windows.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    fom = load_fom()
    if fom["upstream_sha256"] != frozen["upstream_sha256"]:
        raise ValueError("frozen upstream model changed")
    with np.load(ROM / "offline-basis.npz", allow_pickle=False) as data:
        basis = data["basis"]
    with np.load(ROM / "inference.npz", allow_pickle=False) as data:
        upper = float(data["power_bounds_w"][1])
    powers = {name: window_power(rows, name, upper) for name in CASES}
    OUT.mkdir(parents=True, exist_ok=True)
    all_results = []
    for h in (12., 20., 40.):
        stiffness = fom["bulk"]+h*fom["convection"]
        solve = factorized((diags(fom["mass"])+DT*stiffness).tocsc())
        observations = fom["observations"].copy()
        observations[3] *= h
        for case in CASES:
            model = StatorThermalROM.from_npz(ROM / "inference.npz", h_w_m2_k=h, dt_s=DT)
            state = np.zeros(len(fom["mass"]))
            full_fields, reduced_fields = [state.copy()], [state.copy()]
            full_outputs = [np.array([25., 25., 0., 0.])]
            rom_outputs = [np.array([25., 25., 0., 0.])]
            full_balance, rom_balance = [0.], [0.]
            energy = full_out = rom_out = 0.
            for power in powers[case]:
                state = solve(fom["mass"]*state+DT*fom["forcing"]*power)
                full = observations@state
                full[:2] += 25.
                reduced = model.step_average(float(power))
                energy += DT*power
                full_out += DT*full[3]
                rom_out += DT*reduced[3]
                full_balance.append(energy-full_out-full[2])
                rom_balance.append(energy-rom_out-reduced[2])
                full_fields.append(state.copy())
                reduced_fields.append(basis@model.state)
                full_outputs.append(full)
                rom_outputs.append(reduced)
            ff, rf = np.array(full_fields), np.array(reduced_fields)
            fo, ro = np.array(full_outputs), np.array(rom_outputs)
            max_field = float(np.max(abs(ff-rf)))
            max_mean = float(np.max(abs(fo[:, :2]-ro[:, :2])))
            peak = float(np.max(abs(ff)))
            balance = float(max(np.max(abs(np.array(full_balance))),
                                np.max(abs(np.array(rom_balance)))))
            result = dict(case=case, h=h, windows=20, endpoints=21,
                          input_j=float(energy), max_field_error_k=max_field,
                          max_mean_error_k=max_mean, peak_rise_k=peak,
                          relative_field_error=max_field/peak if peak else None,
                          max_balance_j=balance,
                          passed=bool(max_field <= 1e-5 and max_mean <= 1e-5
                                      and balance <= 1e-8))
            all_results.append(result)
            np.savez_compressed(OUT / f"{case}-h{h:g}.npz", time_s=np.arange(21)*DT,
                                power_w=powers[case], full_fields=ff, rom_fields=rf,
                                full_outputs=fo, rom_outputs=ro,
                                full_balance_j=full_balance, rom_balance_j=rom_balance)
    summary = dict(passed=all(r["passed"] for r in all_results), cases=all_results,
                   frozen_sha256=digest(frozen_path), source_sha256=digest(HEAT / "windows.csv"),
                   source_summary_sha256=digest(HEAT / "summary.json"),
                   producer_sha256=digest(Path(__file__)),
                   evidence_kind="model_simulated", dt_s=DT)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    time_ms = np.arange(1, 21)*DT*1000
    for case in CASES:
        axes[0].step(time_ms, powers[case], where="post", label=case)
    axes[0].set(xlabel="Time (ms)", ylabel="Mean copper loss (W)", title="Drive loss windows")
    axes[0].legend(fontsize=7)
    for case in CASES:
        with np.load(OUT / f"{case}-h20.npz") as data:
            axes[1].plot(data["time_s"]*1000,
                         (data["full_outputs"][:, 0]-25)*1e6, label=case)
    axes[1].set(xlabel="Time (ms)", ylabel="Winding mean rise (µK)",
                title="Same-geometry FE, h=20")
    axes[1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "replay.png", dpi=160)
    fig.savefig(OUT / "replay.svg")
    plt.close(fig)
    manifest = {p.name: digest(p) for p in OUT.iterdir()
                if p.is_file() and p.name != "manifest.json"}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("electric-thermal-summary:", json.dumps(summary), flush=True)
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
