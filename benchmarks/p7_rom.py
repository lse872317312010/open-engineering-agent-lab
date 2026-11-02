"""Isolated pyMOR POD training and contact-slab ROM validation."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import resource
import subprocess
import time
from pathlib import Path

import numpy as np
from p7_transient import CONFIG, assemble
from p7_transient_reference import pulse
from scipy.linalg import lu_factor, lu_solve
from scipy.sparse import coo_matrix, issparse, load_npz, save_npz
from scipy.sparse.linalg import factorized

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-rom"
NAMES = ["train-left", "train-right", "validation", "holdout", "out-of-domain"]
COLUMNS = [
    "time_s", "input_left", "input_right", "fom_left_c", "rom_left_c",
    "fom_right_c", "rom_right_c", "fom_interface_left_c", "rom_interface_left_c",
    "fom_interface_right_c", "rom_interface_right_c", "fom_left_j", "rom_left_j",
    "fom_right_j", "rom_right_j", "fom_interface_w", "rom_interface_w",
    "fom_input_j", "rom_input_j", "fom_left_out_j", "rom_left_out_j",
    "fom_right_out_j", "rom_right_out_j", "fom_balance_j", "rom_balance_j",
]


def hashes(folder, exclude=()):
    return {str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file() and p.name not in exclude}


def inputs(name, times):
    if name == "train-left":
        return np.column_stack([pulse(times), np.zeros(len(times))])
    if name == "train-right":
        return np.column_stack([np.zeros(len(times)), pulse(times)])
    if name in {"validation", "out-of-domain"}:
        return np.column_stack([1.2*pulse(times, 6), .8*pulse(times-1, 4)])
    if name == "holdout":
        return np.column_stack([.6*pulse(times-.5, 2), 1.5*pulse(times-2, 3)])
    raise ValueError("unknown fixed input case")


def kernel(mass, stiffness, forcing, dt):
    advance, rhs_input = mass-dt/2*stiffness, dt*forcing
    if issparse(mass):
        inverse = factorized((mass+dt/2*stiffness).tocsc())

        def step(state, average_input):
            return inverse(advance@state+rhs_input@average_input)
    else:
        factors = lu_factor(mass+dt/2*stiffness)

        def step(state, average_input):
            return lu_solve(factors, advance@state+rhs_input@average_input, check_finite=False)
    return step


def simulate(mass, stiffness, forcing, times, signal):
    step = kernel(mass, stiffness, forcing, times[1]-times[0])
    states = np.zeros((len(times), mass.shape[0]))
    for i in range(1, len(times)):
        states[i] = step(states[i-1], (signal[i-1]+signal[i])/2)
    return states


def generate():
    folder = OUT / "train"
    folder.mkdir(parents=True, exist_ok=True)
    data = assemble(32, [1000., 2000.], folder / "mesh")
    mass, stiffness = data["mass"], data["matrix"]
    free, fixed, offset = data["free"], data["fixed"], data["offset"]
    forcing = np.zeros((len(data["weights"]), 2))
    forcing[:offset, 0] = data["load"][:offset]
    forcing[offset:, 1] = data["load"][offset:]
    energy = np.zeros((2, len(forcing)))
    energy[0, :offset], energy[1, offset:] = data["weights"][:offset], data["weights"][offset:]
    observations = np.vstack([energy[0]/data["capacities"][0],
                              energy[1]/data["capacities"][1], data["il"], data["ir"],
                              data["contact"], data["right_op"]])
    rows, cols, values = [], [], []
    for _, left, right, _, edge_mass in data["segments"]:
        for a, sa in ((left, 1), (right, -1)):
            for b, sb in ((left, 1), (right, -1)):
                for i in range(2):
                    for j in range(2):
                        rows.append(int(a[i]))
                        cols.append(int(b[j]))
                        values.append(.01/.1*sa*sb*edge_mass[i, j])
    contact = coo_matrix((values, (rows, cols)), shape=mass.shape).tocsr()
    for name, matrix in (("mass", mass), ("stiffness", stiffness),
                         ("contact-stiffness", contact)):
        save_npz(folder / (name+".npz"), matrix)
    np.savez_compressed(folder / "public.npz", forcing=forcing, energy=energy,
                        observations=observations, points=data["points"],
                        triangles=data["triangles"], free=free, fixed=fixed, offset=offset,
                        capacities=data["capacities"], source_powers=data["sources"])
    times = np.arange(321)*.05
    for name in NAMES[:2]:
        signal = inputs(name, times)
        states = simulate(mass[free][:, free], stiffness[free][:, free], forcing[free],
                          times, signal)
        np.savez_compressed(folder / (name+".npz"), relative_c=states, times=times, inputs=signal)
    metadata = dict(training_names=NAMES[:2], config=CONFIG, n=32, dt_s=.05,
                    free_nodes=len(free), nodes=len(forcing), snapshots=642,
                    volumetric_capacity_j_m3_k=[1000., 2000.], source_kind="synthetic")
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2))
    print("p7-rom-generated: "+json.dumps(metadata), flush=True)


def fit():
    from pymor.algorithms.gram_schmidt import gram_schmidt
    from pymor.algorithms.pod import pod
    from pymor.operators.numpy import NumpyMatrixOperator
    from pymor.vectorarrays.numpy import NumpyVectorSpace

    assert importlib.metadata.version("pymor") == "2026.1.1"
    started = time.perf_counter()
    source, target = OUT / "train", OUT / "model"
    target.mkdir(parents=True, exist_ok=True)
    public = np.load(source / "public.npz")
    free, offset = public["free"], int(public["offset"])
    mass = load_npz(source / "mass.npz")[free][:, free]
    stiffness = load_npz(source / "stiffness.npz")[free][:, free]
    snapshots = np.concatenate([np.load(source / (n+".npz"))["relative_c"] for n in NAMES[:2]])
    space, product = NumpyVectorSpace(len(free)), NumpyMatrixOperator(mass)
    modes, singular = pod(space.from_numpy(snapshots.T.copy()), product=product,
                          modes=12, rtol=1e-10, orth_tol=1e-10)
    seeds = np.column_stack([free < offset, free >= offset]).astype(float)
    augmented = space.from_numpy(seeds)
    augmented.append(modes)
    basis = gram_schmidt(augmented, product=product, atol=1e-13, rtol=1e-12,
                         check_tol=1e-10).to_numpy().copy()
    mr, kr = basis.T@(mass@basis), basis.T@(stiffness@basis)
    fr = basis.T@public["forcing"][free]
    orthogonality = float(np.max(abs(mr-np.eye(len(mr)))))
    assert len(mr) <= 14 and orthogonality <= 1e-9
    assert min(np.linalg.eigvalsh(mr)) > 0 and min(np.linalg.eigvalsh(kr)) > 0
    np.savez_compressed(target / "rom.npz", basis=basis, mass=mr, stiffness=kr, forcing=fr,
                        singular_values=singular,
                        observations=public["observations"][:, free]@basis)
    metadata = dict(dimension=len(mr), pod_modes=len(modes), orthogonality=orthogonality,
                    min_mass_eigenvalue=float(min(np.linalg.eigvalsh(mr))),
                    min_stiffness_eigenvalue=float(min(np.linalg.eigvalsh(kr))),
                    mass_symmetry=float(np.max(abs(mr-mr.T))),
                    stiffness_symmetry=float(np.max(abs(kr-kr.T))),
                    training_names=NAMES[:2], config=CONFIG,
                    fit_elapsed_s=time.perf_counter()-started,
                    commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                    pymor_version=importlib.metadata.version("pymor"))
    (target / "metadata.json").write_text(json.dumps(metadata, indent=2))
    frozen = dict(training_sha256=hashes(source), model_sha256=hashes(target))
    (target / "freeze.json").write_text(json.dumps(frozen, indent=2))
    print("p7-rom-fitted: "+json.dumps(metadata), flush=True)


def audit(states, mass, stiffness, public, times, signal, contact_scale=1.):
    dt = times[1]-times[0]
    middle, derivative = (states[1:]+states[:-1])/2, (states[1:]-states[:-1])/dt
    average = (signal[1:]+signal[:-1])/2
    fixed = public["fixed"]
    sm = np.asarray(mass[fixed].sum(axis=0)).ravel()
    sk = np.asarray(stiffness[fixed].sum(axis=0)).ravel()
    sf = public["forcing"][fixed].sum(axis=0)
    left = -derivative@sm-middle@sk+average@sf
    right = middle@public["observations"][5]
    contact = middle@public["observations"][4]*contact_scale
    source = average*public["source_powers"]
    cumulative = np.vstack([np.zeros(4),
                             dt*np.cumsum(np.column_stack([source, left, right]), axis=0)])
    interface = np.r_[0., dt*np.cumsum(contact)]
    energy = states@public["energy"].T
    balances = np.column_stack([
        energy.sum(axis=1)-cumulative[:, :2].sum(axis=1)+cumulative[:, 2:].sum(axis=1),
        energy[:, 0]-cumulative[:, 0]+cumulative[:, 2]+interface,
        energy[:, 1]-cumulative[:, 1]+cumulative[:, 3]-interface])
    observed = states@public["observations"].T
    observed[:, :4] += 25
    observed[:, 4] *= contact_scale
    return dict(energy=energy, observed=observed, cumulative=cumulative,
                balances=balances, max_balance_j=float(np.max(abs(balances))))


def rms(error, truth, mass):
    return float(np.sqrt(np.sum(error*(mass@error.T).T)/np.sum(truth*(mass@truth.T).T)))


def measure(step, output, count, dimension, basis=None):
    state = np.zeros(dimension)
    prepared = np.column_stack([.5+.5*np.sin(np.arange(count+100)*.013),
                                .5+.5*np.cos(np.arange(count+100)*.021)])
    samples, checksum = [], 0.
    for i, a in enumerate(prepared):
        start = time.perf_counter_ns()
        state = step(state, a)
        outputs = output@state
        if basis is not None:
            full = basis@state
        elapsed = time.perf_counter_ns()-start
        checksum += float(outputs[0])+(float(full[0]) if basis is not None else 0.)
        if i >= 100:
            samples.append(elapsed)
    assert np.isfinite(checksum)
    return np.array(samples)


def validate():
    source, model = OUT / "train", OUT / "model"
    frozen = json.loads((model / "freeze.json").read_text())
    assert frozen["training_sha256"] == hashes(source)
    assert frozen["model_sha256"] == hashes(model, exclude=("freeze.json",))
    public, rom = np.load(source / "public.npz"), np.load(model / "rom.npz")
    metadata = json.loads((model / "metadata.json").read_text())
    free = public["free"]
    mass, stiffness = load_npz(source / "mass.npz"), load_npz(source / "stiffness.npz")
    contact = load_npz(source / "contact-stiffness.npz")
    mf, kf, forcing = mass[free][:, free], stiffness[free][:, free], public["forcing"][free]
    times = np.arange(641)*.025
    results = []
    for name in NAMES:
        folder = OUT / name
        folder.mkdir(parents=True, exist_ok=True)
        signal = inputs(name, times)
        rc = 10. if name == "out-of-domain" else .1
        supported = rc == metadata["config"]["rc"]
        actual_k = stiffness+(.1/rc-1)*contact
        truth = simulate(mf, actual_k[free][:, free], forcing, times, signal)
        reduced = simulate(rom["mass"], rom["stiffness"], rom["forcing"], times, signal)
        predicted = reduced@rom["basis"].T
        error = predicted-truth
        full_truth = np.zeros((len(times), len(public["points"])))
        full_rom = np.zeros_like(full_truth)
        full_truth[:, free], full_rom[:, free] = truth, predicted
        fa = audit(full_truth, mass, actual_k, public, times, signal, contact_scale=.1/rc)
        ra = audit(full_rom, mass, stiffness, public, times, signal)
        metrics = dict(
            id=name, split=name, supported=supported, actual_rc_m2_k_w=rc,
            guard_status="supported" if supported else "rejected_parameter_mismatch",
            guard_reason="" if supported else "actual Rc=10 differs from frozen Rc=0.1",
            rms_relative=rms(error, truth, mf), peak_error_k=float(np.max(abs(error))),
            mean_peak_error_k=float(np.max(abs(fa["observed"][:, :2]-ra["observed"][:, :2]))),
            interface_power_error_over_scale=float(
                max(abs(fa["observed"][:, 4]-ra["observed"][:, 4]))/.16),
            fom_max_balance_j=fa["max_balance_j"], rom_max_balance_j=ra["max_balance_j"],
            rows=len(times), nodes=len(public["points"]))
        if name in {"validation", "holdout"}:
            fine_times = np.arange(1281)*.0125
            finer = simulate(mf, kf, forcing, fine_times, inputs(name, fine_times))[::2]
            metrics.update(time_refinement_rms_relative=rms(truth-finer, finer, mf),
                           time_refinement_peak_k=float(np.max(abs(truth-finer))))
        metrics["accuracy_passed"] = bool(
            metrics["rms_relative"] <= .01 and metrics["peak_error_k"] <= .05
            and metrics["mean_peak_error_k"] <= .02
            and metrics["interface_power_error_over_scale"] <= .05)
        metrics["energy_passed"] = max(fa["max_balance_j"], ra["max_balance_j"]) <= 1e-8
        metrics["accepted"] = bool(supported and metrics["accuracy_passed"]
                                   and metrics["energy_passed"])
        columns = [times, signal[:, 0], signal[:, 1]]
        for index in range(4):
            columns.extend([fa["observed"][:, index], ra["observed"][:, index]])
        for index in range(2):
            columns.extend([fa["energy"][:, index], ra["energy"][:, index]])
        columns.extend([fa["observed"][:, 4], ra["observed"][:, 4],
                        fa["cumulative"][:, :2].sum(axis=1),
                        ra["cumulative"][:, :2].sum(axis=1)])
        for index in (2, 3):
            columns.extend([fa["cumulative"][:, index], ra["cumulative"][:, index]])
        columns.extend([fa["balances"][:, 0], ra["balances"][:, 0]])
        np.savetxt(folder / "timeseries.csv", np.column_stack(columns), delimiter=",",
                   comments="", header=",".join(COLUMNS))
        node_error = np.column_stack([np.arange(len(public["points"])), public["points"],
                                       np.max(abs(full_rom-full_truth), axis=0),
                                       np.sqrt(np.mean((full_rom-full_truth)**2, axis=0))])
        np.savetxt(folder / "node-errors.csv", node_error, delimiter=",", comments="",
                   header="node_id,x_m,y_m,peak_error_k,rms_error_k")
        np.savez_compressed(folder / "fields.npz", times=times, points=public["points"],
                            triangles=public["triangles"], fom_temperature_c=full_truth+25,
                            rom_temperature_c=full_rom+25, reduced_states=reduced, inputs=signal)
        (folder / "result.json").write_text(json.dumps(metrics, indent=2))
        results.append(metrics)
        print("p7-rom-case: "+json.dumps(metrics), flush=True)
    timing = {}
    for name, m, k, f, output, count, basis in (
        ("rom-update-six-outputs", rom["mass"], rom["stiffness"], rom["forcing"],
         rom["observations"], 5000, None),
        ("fom-update-six-outputs", mf, kf, forcing, public["observations"][:, free], 300, None),
        ("rom-update-full-field", rom["mass"], rom["stiffness"], rom["forcing"],
         rom["observations"], 500, rom["basis"])):
        sample = measure(kernel(m, k, f, .0025), output, count, m.shape[0], basis=basis)
        np.savetxt(OUT / (name+".csv"), sample[:, None], delimiter=",", comments="",
                   header="elapsed_ns")
        timing[name] = dict(samples=count, warmup=100, dt_s=.0025,
                            p50_ns=float(np.percentile(sample, 50)),
                            p95_ns=float(np.percentile(sample, 95)),
                            p99_ns=float(np.percentile(sample, 99)), max_ns=int(max(sample)))
    checks = dict(
        supported_cases=all(c["accepted"] for c in results if c["supported"]),
        time_refinement=all(c["time_refinement_rms_relative"] <= .002
                            and c["time_refinement_peak_k"] <= .002 for c in results
                            if "time_refinement_peak_k" in c),
        domain_guard=not results[-1]["accepted"] and not results[-1]["supported"],
        host_budget=timing["rom-update-six-outputs"]["p95_ns"] <= 2_500_000,
        frozen_training=frozen["training_sha256"] == hashes(source),
        frozen_model=frozen["model_sha256"] == hashes(model, exclude=("freeze.json",)))
    report = dict(passed=bool(all(checks.values())), checks=checks, model=metadata, cases=results,
                  timing=timing, columns=COLUMNS, evidence_level="model_simulated",
                  source_kind="synthetic", scope="fixed contact slab POD, partial P7-D only",
                  commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                  versions={p:importlib.metadata.version(p) for p in
                            ("pymor", "gmsh", "scikit-fem", "scipy", "numpy")},
                  host=dict(platform=platform.platform(),
                            cpu_info=Path("/proc/cpuinfo").read_text(),
                            peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
    (OUT / "validation.json").write_text(json.dumps(report, indent=2))
    print("p7-rom-summary: "+json.dumps({k:v for k, v in report.items()
                                      if k not in {"cases", "host"}}), flush=True)
    assert report["passed"], checks


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("generate", "fit", "validate"))
    {"generate":generate, "fit":fit, "validate":validate}[parser.parse_args().phase]()
