"""Affine-Rc POD training, guarded NumPy inference and unseen-parameter evaluation."""
import argparse
import importlib.metadata
import json
import platform
import resource
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
from p7_contact import solve_contact
from p7_layered import mesh_case
from p7_rom import COLUMNS, audit, hashes, inputs, rms, simulate
from p7_transient import CONFIG
from scipy.sparse import load_npz

from oeal.thermal_rom import AffineThermalROM

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-param-rom"
OLD = ROOT / "outputs/p7-rom"
CASES = [
    ("validation-r.03", .03, "validation"), ("validation-r.3", .3, "validation"),
    ("holdout-r.02", .02, "holdout"), ("holdout-r.07", .07, "holdout"),
    ("holdout-r.2", .2, "holdout"), ("holdout-r.7", .7, "holdout"),
    ("below-range", .005, "validation"), ("above-range", 2., "validation"),
]
EXTRA_COLUMNS = ["fixed_left_c", "fixed_right_c", "fixed_interface_w",
                 "fixed_left_j", "fixed_right_j"]


def generate():
    folder = OUT / "train"
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("mass.npz", "stiffness.npz", "contact-stiffness.npz", "public.npz"):
        shutil.copyfile(OLD / "train" / name, folder / name)
    public = np.load(folder / "public.npz")
    mass, stiffness, contact = (load_npz(folder / n) for n in
                                ("mass.npz", "stiffness.npz", "contact-stiffness.npz"))
    free = public["free"]
    _, mesh, tags, facets, _ = mesh_case(32, folder / "control-mesh")
    controls = []
    for rc in (.01, .3, 1.):
        direct = solve_contact(mesh, tags, facets, dict(CONFIG, rc=rc))["matrix"]
        affine = stiffness+(.1/rc-1)*contact
        difference = float(abs(direct-affine).max())
        controls.append(dict(rc=rc, max_matrix_error_w_k=difference))
        assert difference <= 1e-11
    times = np.arange(321)*.05
    training = []
    for rc in (.01, .1, 1.):
        actual_k = stiffness+(.1/rc-1)*contact
        for name in ("train-left", "train-right"):
            key = f"rc{rc:g}-{name}"
            signal = inputs(name, times)
            states = simulate(mass[free][:, free], actual_k[free][:, free],
                              public["forcing"][free], times, signal)
            np.savez_compressed(folder / (key+".npz"), times=times, inputs=signal,
                                relative_c=states)
            training.append(dict(id=key, rc=rc))
    metadata = dict(training=training, controls=controls, config=CONFIG,
                    nodes=len(public["points"]),
                    free_nodes=len(free), snapshot_stride=4, pod_snapshots=486,
                    old_input_sha256=hashes(OLD / "train"))
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2))
    print("p7-param-generated: "+json.dumps({k:v for k, v in metadata.items()
                                          if k != "old_input_sha256"}), flush=True)


def fit():
    from pymor.algorithms.gram_schmidt import gram_schmidt
    from pymor.algorithms.pod import pod
    from pymor.operators.numpy import NumpyMatrixOperator
    from pymor.vectorarrays.numpy import NumpyVectorSpace

    assert importlib.metadata.version("pymor") == "2026.1.1"
    folder, target = OUT / "train", OUT / "model"
    target.mkdir(parents=True, exist_ok=True)
    meta = json.loads((folder / "metadata.json").read_text())
    public = np.load(folder / "public.npz")
    free, offset = public["free"], int(public["offset"])
    mass, stiffness, contact = (load_npz(folder / n)[free][:, free] for n in
                                ("mass.npz", "stiffness.npz", "contact-stiffness.npz"))
    snapshots = np.concatenate([
        np.load(folder / (r["id"]+".npz"))["relative_c"][::4] for r in meta["training"]])
    assert len(snapshots) == 486
    space, product = NumpyVectorSpace(len(free)), NumpyMatrixOperator(mass)
    modes, singular = pod(space.from_numpy(snapshots.T.copy()), product=product,
                          modes=20, rtol=1e-10, orth_tol=1e-10)
    vectors = space.from_numpy(np.column_stack([free < offset, free >= offset]).astype(float))
    vectors.append(modes)
    basis = gram_schmidt(vectors, product=product, check_tol=1e-10).to_numpy().copy()
    mr = basis.T@(mass@basis)
    orthogonality = float(np.max(abs(mr-np.eye(len(mr)))))
    assert len(mr) <= 22 and orthogonality <= 1e-9
    np.savez_compressed(
        target / "rom.npz", format_version=np.array(1), basis=basis, mass=mr,
        bulk_stiffness=basis.T@((stiffness-contact)@basis),
        contact_stiffness=basis.T@(contact@basis), forcing=basis.T@public["forcing"][free],
        observations=public["observations"][:, free]@basis, rc_bounds=[.01, 1.],
        reference_rc=np.array(.1), ambient_c=np.array(25.), singular_values=singular)
    metadata = dict(dimension=len(mr), pod_modes=len(modes), orthogonality=orthogonality,
                    rc_bounds=[.01, 1.], reference_rc=.1, config=CONFIG,
                    training=meta["training"], pod_snapshots=486,
                    commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
    (target / "metadata.json").write_text(json.dumps(metadata, indent=2))
    frozen = dict(training_sha256=hashes(folder), model_sha256=hashes(target))
    (target / "freeze.json").write_text(json.dumps(frozen, indent=2))
    print("p7-param-fitted: "+json.dumps(metadata), flush=True)


def runtime_states(path, rc, signal):
    model = AffineThermalROM.from_npz(path, rc=rc, dt_s=.025)
    history = np.zeros((len(signal), len(model.state)))
    outputs = np.zeros((len(signal), 6))
    outputs[0, :4] = 25.
    for i in range(1, len(signal)):
        outputs[i] = model.step(signal[i])
        history[i] = model.state
    return history, outputs


def profile(path, rc):
    model = AffineThermalROM.from_npz(path, rc=rc, dt_s=.0025)
    samples = []
    prepared = np.column_stack([.5+.5*np.sin(np.arange(5100)*.013),
                                .5+.5*np.cos(np.arange(5100)*.021)])
    for i, value in enumerate(prepared):
        start = time.perf_counter_ns()
        output = model.step(value)
        elapsed = time.perf_counter_ns()-start
        assert np.all(np.isfinite(output))
        if i >= 100:
            samples.append(elapsed)
    return np.array(samples)


def validate():
    folder, target = OUT / "train", OUT / "model"
    freeze = json.loads((target / "freeze.json").read_text())
    assert freeze["training_sha256"] == hashes(folder)
    assert freeze["model_sha256"] == hashes(target, exclude=("freeze.json",))
    public, rom = np.load(folder / "public.npz"), np.load(target / "rom.npz")
    old = np.load(OLD / "model/rom.npz")
    metadata = json.loads((target / "metadata.json").read_text())
    free = public["free"]
    mass, stiffness, contact = (load_npz(folder / n) for n in
                                ("mass.npz", "stiffness.npz", "contact-stiffness.npz"))
    mf, forcing = mass[free][:, free], public["forcing"][free]
    times = np.arange(641)*.025
    results, timing = [], {}
    for name, rc, split in CASES:
        case = OUT / name
        case.mkdir(parents=True, exist_ok=True)
        signal = inputs(split, times)
        actual_k = stiffness+(.1/rc-1)*contact
        try:
            AffineThermalROM.from_npz(target / "rom.npz", rc=rc, dt_s=.025)
            supported, reason = True, ""
        except ValueError as error:
            supported, reason = False, str(error)
        kr = rom["bulk_stiffness"]+.1/rc*rom["contact_stiffness"]
        assert np.allclose(kr, kr.T, atol=1e-9, rtol=1e-10)
        assert min(np.linalg.eigvalsh(kr)) > 0
        if supported:
            reduced, runtime_output = runtime_states(target / "rom.npz", rc, signal)
        else:
            # Explicitly bypass the rejected interface for counterfactual evidence only.
            reduced = simulate(rom["mass"], kr, rom["forcing"], times, signal)
        truth = simulate(mf, actual_k[free][:, free], forcing, times, signal)
        fixed_reduced = simulate(old["mass"], old["stiffness"], old["forcing"], times, signal)
        predicted, fixed = reduced@rom["basis"].T, fixed_reduced@old["basis"].T
        whole = []
        for values in (truth, predicted, fixed):
            u = np.zeros((len(times), len(public["points"])))
            u[:, free] = values
            whole.append(u)
        fa, ra = [audit(u, mass, actual_k, public, times, signal, contact_scale=.1/rc)
                  for u in whole[:2]]
        ba = audit(whole[2], mass, stiffness, public, times, signal)
        if supported:
            assert np.max(abs(runtime_output-ra["observed"])) <= 1e-9
        metrics = dict(
            id=name, split=split, rc=rc, supported=supported, guard_reason=reason,
            guard_status="supported" if supported else "rejected",
            rows=len(times), nodes=len(public["points"]),
            rms_relative=rms(predicted-truth, truth, mf),
            peak_error_k=float(np.max(abs(predicted-truth))),
            fixed_rms_relative=rms(fixed-truth, truth, mf),
            fixed_peak_error_k=float(np.max(abs(fixed-truth))),
            mean_peak_error_k=float(np.max(abs(fa["observed"][:, :2]-ra["observed"][:, :2]))),
            interface_power_error_over_scale=float(
                np.max(abs(fa["observed"][:, 4]-ra["observed"][:, 4]))/.16),
            fom_max_balance_j=fa["max_balance_j"], rom_max_balance_j=ra["max_balance_j"])
        if supported:
            fine_times = np.arange(1281)*.0125
            fine = simulate(mf, actual_k[free][:, free], forcing, fine_times,
                            inputs(split, fine_times))[::2]
            metrics.update(time_refinement_rms_relative=rms(truth-fine, fine, mf),
                           time_refinement_peak_k=float(np.max(abs(truth-fine))))
            sample = profile(target / "rom.npz", rc)
            np.savetxt(OUT / (name+"-latency.csv"), sample, delimiter=",", comments="",
                       header="elapsed_ns")
            timing[name] = dict(samples=5000, warmup=100, dt_s=.0025,
                                p50_ns=float(np.percentile(sample, 50)),
                                p95_ns=float(np.percentile(sample, 95)),
                                p99_ns=float(np.percentile(sample, 99)), max_ns=int(max(sample)))
        metrics["accuracy_passed"] = bool(
            metrics["rms_relative"] <= .01 and metrics["peak_error_k"] <= .05
            and metrics["mean_peak_error_k"] <= .02
            and metrics["interface_power_error_over_scale"] <= .05)
        metrics["energy_passed"] = max(fa["max_balance_j"], ra["max_balance_j"]) <= 1e-8
        metrics["accepted"] = bool(supported and metrics["accuracy_passed"]
                                   and metrics["energy_passed"])
        columns = [times, signal[:, 0], signal[:, 1]]
        for i in range(4):
            columns.extend([fa["observed"][:, i], ra["observed"][:, i]])
        for i in range(2):
            columns.extend([fa["energy"][:, i], ra["energy"][:, i]])
        columns.extend([fa["observed"][:, 4], ra["observed"][:, 4],
                        fa["cumulative"][:, :2].sum(axis=1),
                        ra["cumulative"][:, :2].sum(axis=1)])
        for i in (2, 3):
            columns.extend([fa["cumulative"][:, i], ra["cumulative"][:, i]])
        columns.extend([fa["balances"][:, 0], ra["balances"][:, 0],
                        ba["observed"][:, 0], ba["observed"][:, 1], ba["observed"][:, 4],
                        ba["energy"][:, 0], ba["energy"][:, 1]])
        np.savetxt(case / "timeseries.csv", np.column_stack(columns), delimiter=",", comments="",
                   header=",".join(COLUMNS+EXTRA_COLUMNS))
        error = whole[1]-whole[0]
        np.savetxt(case / "node-errors.csv", np.column_stack([
            np.arange(metrics["nodes"]), public["points"], np.max(abs(error), axis=0),
            np.sqrt(np.mean(error**2, axis=0))]), delimiter=",", comments="",
            header="node_id,x_m,y_m,peak_error_k,rms_error_k")
        np.savez_compressed(case / "fields.npz", times=times, points=public["points"],
                            triangles=public["triangles"], fom_temperature_c=whole[0]+25,
                            rom_temperature_c=whole[1]+25, fixed_temperature_c=whole[2]+25,
                            reduced_states=reduced, inputs=signal)
        (case / "result.json").write_text(json.dumps(metrics, indent=2))
        results.append(metrics)
        print("p7-param-case: "+json.dumps(metrics), flush=True)
    checks = dict(
        supported_cases=all(r["accepted"] for r in results[:6]),
        domain_guard=all(not r["supported"] and not r["accepted"] for r in results[-2:]),
        time_refinement=all(r["time_refinement_rms_relative"] <= .002
                            and r["time_refinement_peak_k"] <= .002 for r in results
                            if r["supported"]),
        host_budget=len(timing) == 6 and all(v["p95_ns"] <= 2_500_000
                                             for v in timing.values()),
        frozen_training=freeze["training_sha256"] == hashes(folder),
        frozen_model=freeze["model_sha256"] == hashes(target, exclude=("freeze.json",)))
    report = dict(
        passed=bool(all(checks.values())), checks=checks, model=metadata, cases=results,
        timing=timing, columns=COLUMNS+EXTRA_COLUMNS, evidence_level="model_simulated",
        source_kind="synthetic", scope="constant Rc per trajectory; empirical parameter points",
        commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        versions={p:importlib.metadata.version(p) for p in
                  ("pymor", "gmsh", "scikit-fem", "scipy", "numpy")},
        host=dict(platform=platform.platform(), cpu_info=Path("/proc/cpuinfo").read_text(),
                  peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
    (OUT / "validation.json").write_text(json.dumps(report, indent=2))
    print("p7-param-summary: "+json.dumps({k:v for k, v in report.items()
                                        if k not in {"cases", "host"}}), flush=True)
    assert report["passed"], checks


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("generate", "fit", "validate"))
    {"generate":generate, "fit":fit, "validate":validate}[parser.parse_args().phase]()
