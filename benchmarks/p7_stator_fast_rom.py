"""Separate, frozen rational enrichment of the long-time stator POD space."""
import argparse
import csv
import json
import platform
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from p7_electric_thermal_replay import CASES, DT, window_power
from p7_stator_rom_study import OUT as BASE
from p7_stator_rom_study import full_replay, load_fom
from p7_winding_heat import OUT as HEAT
from p7_winding_heat import ROOT, digest
from scipy.sparse import diags
from scipy.sparse.linalg import factorized

from oeal.stator_rom import StatorThermalROM

OUT = ROOT / "outputs/p7-stator-fast-rom"
CONTRACT = ROOT / "docs/p7-stator-fast-rom-contract.md"
TIMES = (.0025, .01, .05, .25, 1.)
TRAIN_H = (5., 20., 80.)
ARTIFACTS = ("inference.npz", "offline-basis.npz")


def check_files(directory, hashes):
    for name, expected in hashes.items():
        if digest(directory / name) != expected:
            raise ValueError(f"frozen artifact changed: {name}")


def baseline():
    frozen = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    if not frozen["passed"]:
        raise ValueError("baseline training failed")
    check_files(BASE, frozen["frozen_sha256"])
    if digest(ROOT / "src/oeal/stator_rom.py") != frozen["inference_api_sha256"]:
        raise ValueError("baseline inference implementation changed")
    return frozen


def enrich_basis(fom, original):
    """Keep the original space; add fixed resolvents without validation data."""
    mass = fom["mass"]
    root_mass = np.sqrt(mass)
    vectors = list((original*root_mass[:, None]).T.copy())
    retained = []
    for h in TRAIN_H:
        stiffness = fom["bulk"]+h*fom["convection"]
        for tau in TIMES:
            solve = factorized((diags(mass)+tau*stiffness).tocsc())
            value = root_mass*solve(fom["forcing"])
            value /= np.linalg.norm(value)
            for _ in range(2):
                for previous in vectors:
                    value -= previous*(previous@value)
            norm = np.linalg.norm(value)
            retained.append(dict(h=h, tau_s=tau, residual_norm=float(norm),
                                 retained=bool(norm > 1e-10)))
            if norm > 1e-10:
                vectors.append(value/norm)
    weighted = np.array(vectors).T
    old = original*root_mass[:, None]
    orthogonality = float(np.max(abs(weighted.T@weighted-np.eye(len(vectors)))))
    inclusion = float(np.max(abs(old-weighted@(weighted.T@old))))
    if orthogonality > 1e-8 or inclusion > 1e-8 or weighted.shape[1] > 37:
        raise ValueError("enrichment basis contract failed")
    return weighted/root_mass[:, None], retained, orthogonality, inclusion


def train():
    frozen = baseline()
    fom = load_fom()
    if fom["upstream_sha256"] != frozen["upstream_sha256"]:
        raise ValueError("baseline upstream model changed")
    with np.load(BASE / "offline-basis.npz", allow_pickle=False) as data:
        original = data["basis"]
    basis, retained, orthogonality, inclusion = enrich_basis(fom, original)
    with np.load(BASE / "inference.npz", allow_pickle=False) as data:
        bundle = {key: data[key] for key in ("format_version", "h_bounds",
                                           "power_bounds_w", "ambient_c")}
    operators = dict(mass=basis.T@(fom["mass"][:, None]*basis),
                     bulk=basis.T@(fom["bulk"]@basis),
                     convection=basis.T@(fom["convection"]@basis))
    bundle.update({key: (value+value.T)/2 for key, value in operators.items()})
    bundle.update(forcing=basis.T@fom["forcing"], observations=fom["observations"]@basis)
    StatorThermalROM(bundle, h_w_m2_k=20., dt_s=DT)
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez(OUT / "inference.npz", **bundle)
    np.savez_compressed(OUT / "offline-basis.npz", basis=basis)
    metadata = dict(passed=True, dimensions=basis.shape[1], baseline_dimensions=original.shape[1],
                    full_nodes=len(fom["mass"]), training_h=TRAIN_H, times_s=TIMES,
                    retained=retained, mass_orthogonality_error=orthogonality,
                    baseline_inclusion_error=inclusion,
                    baseline_sha256=digest(BASE / "frozen.json"),
                    upstream_sha256=fom["upstream_sha256"],
                    inference_api_sha256=digest(ROOT / "src/oeal/stator_rom.py"),
                    producer_sha256=digest(Path(__file__)), contract_sha256=digest(CONTRACT),
                    frozen_sha256={name: digest(OUT / name) for name in ARTIFACTS})
    (OUT / "frozen.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print("fast-rom-frozen:", json.dumps(metadata), flush=True)


def verified_model():
    baseline()
    frozen = json.loads((OUT / "frozen.json").read_text(encoding="utf-8"))
    if not frozen["passed"] or set(frozen["frozen_sha256"]) != set(ARTIFACTS):
        raise ValueError("incomplete frozen model")
    check_files(OUT, frozen["frozen_sha256"])
    for path, key in ((BASE / "frozen.json", "baseline_sha256"),
                      (ROOT / "src/oeal/stator_rom.py", "inference_api_sha256"),
                      (Path(__file__), "producer_sha256"), (CONTRACT, "contract_sha256")):
        if digest(path) != frozen[key]:
            raise ValueError(f"frozen dependency changed: {key}")
    fom = load_fom()
    if fom["upstream_sha256"] != frozen["upstream_sha256"]:
        raise ValueError("upstream model changed after freezing")
    with np.load(OUT / "offline-basis.npz", allow_pickle=False) as data:
        basis = data["basis"]
    with np.load(BASE / "offline-basis.npz", allow_pickle=False) as data:
        old_basis = data["basis"]
    return frozen, fom, basis, old_basis


def holdout_powers(name, p0):
    ticks = np.arange(50)
    if name == "pulse":
        return np.where(ticks < 10, 1.5*p0, 0.)
    if name == "alternating":
        return np.where(ticks % 2 == 0, 1.75*p0, 0.)
    if name == "triangle":
        return p0*(1-abs(2*(ticks+.5)/50-1))
    raise ValueError("unknown holdout waveform")


def compare(fom, basis, model, old_basis, old_model, power, h):
    """Compare all endpoints, retaining temperature increments to avoid cancellation."""
    mass = fom["mass"]
    solve = factorized((diags(mass)+DT*(fom["bulk"]+h*fom["convection"])).tocsc())
    observations = fom["observations"].copy()
    observations[3] *= h
    state = np.zeros(len(mass))
    fields = [[state.copy()] for _ in range(3)]
    outputs = [[np.array([25., 25., 0., 0.])] for _ in range(3)]
    balances = [[0.] for _ in range(3)]
    energy = 0.
    out_j = np.zeros(3)
    for p in power:
        state = solve(mass*state+DT*fom["forcing"]*p)
        full = observations@state
        full[:2] += 25.
        reduced = model.step_average(float(p))
        old = old_model.step_average(float(p))
        energy += DT*p
        for i, (field, values) in enumerate(((state, full), (basis@model.state, reduced),
                                            (old_basis@old_model.state, old))):
            fields[i].append(field.copy())
            outputs[i].append(values)
            out_j[i] += DT*values[3]
            balances[i].append(energy-out_j[i]-values[2])
    ff, rf, bf = np.array(fields)
    fo, ro, bo = np.array(outputs)
    balance = np.array(balances)
    error, old_error = (float(np.max(abs(x-ff))) for x in (rf, bf))
    peak = float(np.max(abs(ff)))
    relative = error/peak if peak else float("inf")
    mean = float(np.max(abs(ro[:, :2]-fo[:, :2])))
    max_balance = float(np.max(abs(balance[:2])))
    metrics = dict(windows=len(power), input_j=float(energy), peak_rise_k=peak,
                   max_field_error_k=error, relative_field_error=relative,
                   baseline_field_error_k=old_error,
                   baseline_relative_field_error=old_error/peak if peak else None,
                   max_mean_error_k=mean, max_balance_j=max_balance,
                   baseline_max_balance_j=float(np.max(abs(balance[2]))),
                   passed=bool(np.isfinite(relative) and relative <= .05 and error <= 1e-5
                               and mean <= 1e-5 and max_balance <= 1e-8))
    arrays = dict(time_s=np.arange(len(power)+1)*DT, power_w=power,
                  full_fields=ff, rom_fields=rf, baseline_fields=bf,
                  full_outputs=fo, rom_outputs=ro, baseline_outputs=bo,
                  balance_j=balance)
    return metrics, arrays


def validate():
    frozen, fom, basis, old_basis = verified_model()
    frozen_sha = digest(OUT / "frozen.json")
    source = json.loads((HEAT / "summary.json").read_text(encoding="utf-8"))
    if not source["passed"]:
        raise ValueError("copper source validation failed")
    check_files(HEAT, {"windows.csv": source["output_sha256"]["windows.csv"]})
    with (HEAT / "windows.csv").open(encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))
    with np.load(OUT / "inference.npz", allow_pickle=False) as data:
        upper = float(data["power_bounds_w"][1])
    inputs = [(name, h, window_power(rows, name, upper), "drive_replay")
              for h in (12., 20., 40.) for name in CASES]
    inputs += [(name, h, holdout_powers(name, fom["p0"]), "new_holdout")
               for h in (8., 30., 65.) for name in ("pulse", "alternating", "triangle")]
    results = []
    for name, h, power, kind in inputs:
        model = StatorThermalROM.from_npz(OUT / "inference.npz", h_w_m2_k=h, dt_s=DT)
        old_model = StatorThermalROM.from_npz(BASE / "inference.npz", h_w_m2_k=h, dt_s=DT)
        metrics, arrays = compare(fom, basis, model, old_basis, old_model, power, h)
        metrics.update(name=name, h=h, kind=kind)
        results.append(metrics)
        np.savez_compressed(OUT / f"{name}-h{h:g}.npz", **arrays)
        print("short-case:", json.dumps(metrics), flush=True)
    long_cases = []
    for name, h in (("validation", 12.), ("holdout", 40.)):
        model = StatorThermalROM.from_npz(OUT / "inference.npz", h_w_m2_k=h, dt_s=1.)
        case = full_replay(fom, h, name, 1., basis=basis, model=model)
        np.savez_compressed(OUT / f"long-{name}.npz", **case)
        passed = (case["max_field_error_k"] <= 1e-4 and case["rmse_k"] <= 2e-5
                  and max(case["max_balance_j"], case["rom_balance_j"]) <= 1e-8)
        long_cases.append(dict(name=name, h=h, passed=bool(passed),
                               **{k: v for k, v in case.items() if k not in
                                  ("outputs", "snapshots")}))
        print("long-case:", json.dumps(long_cases[-1]), flush=True)
    timer = StatorThermalROM.from_npz(OUT / "inference.npz", h_w_m2_k=12., dt_s=DT)
    for _ in range(1000):
        timer.step_average(fom["p0"])
    durations = []
    for _ in range(5000):
        start = time.perf_counter_ns()
        timer.step_average(fom["p0"])
        durations.append(time.perf_counter_ns()-start)
    np.savetxt(OUT / "step-times-ns.csv", durations, fmt="%d", header="duration_ns", comments="")
    check_files(OUT, frozen["frozen_sha256"])
    if digest(OUT / "frozen.json") != frozen_sha:
        raise ValueError("frozen metadata changed during validation")
    summary = dict(passed=bool(all(r["passed"] for r in results+long_cases)
                               and np.percentile(durations, 95) <= 2.5e6),
                   cases=results, long_cases=long_cases, dimensions=frozen["dimensions"],
                   p95_ns=float(np.percentile(durations, 95)), platform=platform.platform(),
                   numpy_version=np.__version__, producer_sha256=digest(Path(__file__)),
                   frozen_sha256=frozen_sha, source_sha256=digest(HEAT / "windows.csv"),
                   contract_sha256=digest(CONTRACT), evidence_kind="model_simulated")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    figure(results)
    manifest = {p.name: digest(p) for p in OUT.iterdir()
                if p.is_file() and p.name != "manifest.json"}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("fast-rom-summary:", json.dumps(summary), flush=True)
    if not summary["passed"]:
        raise SystemExit(1)


def figure(results):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    labels = [f"{r['name']}\nh={r['h']:g}" for r in results]
    x = np.arange(len(results))
    for key, label in (("baseline_relative_field_error", "Original POD"),
                       ("relative_field_error", "Enriched ROM")):
        axes[0].semilogy(x, [100*r[key] for r in results], "o-", label=label)
    axes[0].axhline(5, color="k", linestyle="--", label="5% budget")
    axes[0].set(xticks=x, xticklabels=labels, ylabel="Max field error / peak FE rise (%)",
                title="All 21 short-time cases")
    axes[0].tick_params(axis="x", labelsize=5, rotation=90)
    axes[0].legend(fontsize=8)
    with np.load(OUT / "forward-base-h20.npz", allow_pickle=False) as data:
        for key, label in (("baseline_fields", "Original POD"), ("rom_fields", "Enriched ROM")):
            error = np.max(abs(data[key]-data["full_fields"]), axis=1)*1e6
            axes[1].plot(data["time_s"]*1000, error, label=label)
    axes[1].set(xlabel="Time (ms)", ylabel="Max nodal error (µK)",
                title="Drive forward-base, h=20")
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(OUT / "comparison.png", dpi=160)
    fig.savefig(OUT / "comparison.svg")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("train", "validate"))
    args = parser.parse_args()
    (train if args.stage == "train" else validate)()
