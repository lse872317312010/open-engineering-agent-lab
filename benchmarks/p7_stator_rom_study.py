"""Train/freeze then independently validate a same-stator convection-parametric ROM."""
import argparse
import csv
import json
import platform
import time
from pathlib import Path

import meshio
import numpy as np
from p7_stator_thermal import OUT as UPSTREAM
from p7_stator_thermal import THICKNESS, assemble, validate_exposed_boundary
from p7_winding_heat import OUT as HEAT
from p7_winding_heat import ROOT, digest
from scipy.linalg import svd
from scipy.sparse import diags, load_npz
from scipy.sparse.linalg import factorized
from skfem import BilinearForm, ElementTriP1, FacetBasis, MeshTri

from oeal.stator_rom import StatorThermalROM

OUT = ROOT / "outputs/p7-stator-rom"
TOTAL = 1200


def powers(name, dt, p0):
    values = np.zeros(round(TOTAL/dt))
    phases = {"train": ((0, 600, 1.),),
              "validation": ((0, 200, .5), (200, 500, 1.), (700, 900, 1.5)),
              "holdout": ((0, 150, 1.25), (150, 450, .25), (650, 800, 1.75))}[name]
    for start, end, value in phases:
        values[round(start/dt):round(end/dt)] = value*p0
    return values


def load_fom():
    manifest = json.loads((UPSTREAM / "manifest.json").read_text(encoding="utf-8"))
    names = ("summary.json", "mesh-2/stator.msh", "mesh-2/stiffness.npz",
             "mesh-2/volume-inputs.npz", "mesh-2/operators.npz")
    for name in names:
        if digest(UPSTREAM / name) != manifest[name]:
            raise ValueError("upstream thermal evidence integrity failure")
    if not json.loads((UPSTREAM / "summary.json").read_text())["passed"]:
        raise ValueError("upstream thermal validation failed")
    raw = meshio.read(UPSTREAM / "mesh-2/stator.msh")
    triangles = raw.cells_dict["triangle"]
    used = np.unique(triangles)
    remap = np.full(len(raw.points), -1)
    remap[used] = np.arange(len(used))
    mesh = MeshTri(raw.points[used, :2].T, remap[triangles].T)
    lookup = {tuple(sorted(p)): i for i, p in enumerate(mesh.facets.T)}
    outer = np.array([lookup[tuple(sorted(p))] for p in remap[raw.cells_dict["line"]]])
    validate_exposed_boundary(mesh, outer)
    tags = raw.cell_data_dict["gmsh:physical"]["triangle"]
    _, mass, stiffness, inputs, _, _ = assemble(mesh, tags, outer)
    old = load_npz(UPSTREAM / "mesh-2/stiffness.npz")
    error = float(abs(stiffness-old).max())
    with np.load(UPSTREAM / "mesh-2/operators.npz", allow_pickle=False) as data:
        if error > 1e-12 or not np.array_equal(mass, data["mass"]):
            raise ValueError("default operator changed")
    boundary_basis = FacetBasis(mesh, ElementTriP1(), facets=outer, intorder=4)

    @BilinearForm
    def robin_unit(u, v, w):
        return THICKNESS*u*v

    convection = robin_unit.assemble(boundary_basis)
    bulk = stiffness-20*convection
    volume = np.asarray(inputs.sum(axis=0)).ravel()
    wind = np.asarray(inputs[:, 1:].sum(axis=1)).ravel()/sum(volume[1:])
    core = np.asarray(inputs[:, 0].toarray()).ravel()/volume[0]
    flux = np.asarray(convection.sum(axis=0)).ravel()
    observations = np.vstack((wind, core, mass, flux))
    with (HEAT / "windows.csv").open(encoding="utf-8", newline="") as fp:
        copper = sum(float(r["copper_j"]) for r in csv.DictReader(fp)
                     if r["case"] == "forward-base")
    source_summary = json.loads((HEAT / "summary.json").read_text())
    if (not source_summary["passed"] or digest(HEAT / "windows.csv")
            != source_summary["output_sha256"]["windows.csv"]):
        raise ValueError("mean-power source integrity failure")
    return dict(mass=mass, bulk=bulk, convection=convection, forcing=wind,
                observations=observations, p0=copper/.05, operator_difference=error,
                mesh=mesh, upstream_sha256=digest(UPSTREAM / "summary.json"))


def full_replay(fom, h, name, dt, *, basis=None, model=None):
    power = powers(name, dt, fom["p0"])
    mass = fom["mass"]
    inverse = factorized((diags(mass)+dt*(fom["bulk"]+h*fom["convection"])).tocsc())
    state = np.zeros(len(mass))
    obs = fom["observations"].copy()
    obs[3] *= h
    output = np.zeros((len(power)+1, 5))
    output[0, :2] = 25
    output[0, 4] = 25
    snapshots = [state.copy()]
    source_j = out_j = max_balance = max_rom_balance = max_field = 0.
    rom_error = []
    rom_source = rom_out = 0.
    for tick, p in enumerate(power, 1):
        state = inverse(mass*state+dt*fom["forcing"]*p)
        values = obs@state
        values[:2] += 25
        output[tick] = np.r_[values, 25+max(state)]
        source_j += dt*p
        out_j += dt*values[3]
        max_balance = max(max_balance, abs(source_j-out_j-values[2]))
        if tick % round(24/dt) == 0:
            snapshots.append(state.copy())
        if model is not None:
            reduced = model.step_average(float(p))
            field = basis@model.state
            max_field = max(max_field, float(max(abs(field-state))))
            rom_error.append(reduced[:2]-values[:2])
            rom_source += dt*p
            rom_out += dt*reduced[3]
            max_rom_balance = max(max_rom_balance, abs(rom_source-rom_out-reduced[2]))
    return dict(outputs=output, snapshots=np.array(snapshots),
                max_balance_j=float(max_balance), rom_balance_j=float(max_rom_balance),
                max_field_error_k=float(max_field),
                rmse_k=float(max(np.sqrt(np.mean(np.array(rom_error)**2, axis=0))))
                if rom_error else None)


def orthogonal_basis(weighted, mass, forcing):
    u, singular, _ = svd(weighted, full_matrices=False, check_finite=False)
    candidates = [np.sqrt(mass), forcing/np.sqrt(mass)]+list(u[:, :20].T)
    vectors = []
    for candidate in candidates:
        value = candidate/np.linalg.norm(candidate)
        for _ in range(2):
            for previous in vectors:
                value = value-previous*(previous@value)
        norm = np.linalg.norm(value)
        if norm > 1e-10:
            vectors.append(value/norm)
    return np.array(vectors).T/np.sqrt(mass)[:, None], singular


def train():
    OUT.mkdir(parents=True, exist_ok=True)
    fom = load_fom()
    training = [full_replay(fom, h, "train", 1.) for h in (5., 20., 80.)]
    fields = np.vstack([case["snapshots"] for case in training])
    basis, singular = orthogonal_basis(fields.T*np.sqrt(fom["mass"])[:, None],
                                       fom["mass"], fom["forcing"])
    def project(matrix):
        return basis.T@(matrix@basis)
    mass = basis.T@(fom["mass"][:, None]*basis)
    bulk, convection = (project(fom[key]) for key in ("bulk", "convection"))
    bundle = dict(format_version=1, mass=(mass+mass.T)/2, bulk=(bulk+bulk.T)/2,
                  convection=(convection+convection.T)/2, forcing=basis.T@fom["forcing"],
                  observations=fom["observations"]@basis, h_bounds=[5., 80.],
                  power_bounds_w=[0., 2*fom["p0"]], ambient_c=25.)
    np.savez(OUT / "inference.npz", **bundle)
    np.savez_compressed(OUT / "offline-basis.npz", basis=basis, singular_values=singular)
    sensitivity = np.stack([c["outputs"] for c in training])
    np.savez_compressed(OUT / "training.npz", h=[5., 20., 80.],
                        snapshots=fields, outputs=sensitivity, dt_s=1.)
    monotone = all(np.all(np.diff(sensitivity[:, tick, 0]) <= 1e-10) for tick in (600, 1200))
    metadata = dict(passed=bool(monotone and max(c["max_balance_j"] for c in training) <= 1e-8),
                    training_h=[5., 20., 80.], sensitivity_monotone=bool(monotone),
                    dimensions=basis.shape[1], full_nodes=len(fom["mass"]),
                    p0_w=fom["p0"], source_kind="preset mean-copper replay",
                    duration_s=TOTAL, training_dt_s=1., snapshot_period_s=24.,
                    producer_sha256=digest(Path(__file__)),
                    inference_api_sha256=digest(ROOT / "src/oeal/stator_rom.py"),
                    upstream_sha256=fom["upstream_sha256"],
                    default_operator_difference=fom["operator_difference"],
                    training_balance_j=[c["max_balance_j"] for c in training],
                    frozen_sha256={n: digest(OUT / n) for n in
                                   ("inference.npz", "offline-basis.npz", "training.npz")})
    (OUT / "frozen.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2), flush=True)
    if not metadata["passed"]:
        raise SystemExit(1)


def validate():
    frozen = json.loads((OUT / "frozen.json").read_text())
    for name, expected in frozen["frozen_sha256"].items():
        if digest(OUT / name) != expected:
            raise ValueError("frozen training artifact modified")
    if not frozen["passed"]:
        raise ValueError("training sensitivity or energy gate failed")
    if digest(ROOT / "src/oeal/stator_rom.py") != frozen["inference_api_sha256"]:
        raise ValueError("inference implementation changed since freezing")
    fom = load_fom()
    if fom["upstream_sha256"] != frozen["upstream_sha256"]:
        raise ValueError("upstream FOM changed since training")
    with np.load(OUT / "offline-basis.npz", allow_pickle=False) as data:
        basis = data["basis"]
    cases = []
    for name, h in (("validation", 12.), ("holdout", 40.)):
        model = StatorThermalROM.from_npz(OUT / "inference.npz", h_w_m2_k=h, dt_s=1.)
        case = full_replay(fom, h, name, 1., basis=basis, model=model)
        fine = full_replay(fom, h, name, .5)
        time_error = float(np.max(abs(case["outputs"][:, [0, 1, 4]]
                                     -fine["outputs"][::2, [0, 1, 4]])))
        fast = StatorThermalROM.from_npz(OUT / "inference.npz", h_w_m2_k=h, dt_s=.0025)
        input_power = powers(name, .0025, fom["p0"])
        outputs = np.zeros((len(input_power)+1, 4))
        outputs[0, :2] = 25
        balances = np.zeros(len(input_power)+1)
        source_j = out_j = 0.
        for tick, power in enumerate(input_power, 1):
            outputs[tick] = fast.step_average(float(power))
            source_j += .0025*power
            out_j += .0025*outputs[tick, 3]
            balances[tick] = source_j-out_j-outputs[tick, 2]
        fast_error = float(np.max(abs(outputs[::200, :2]-fine["outputs"][:, :2])))
        np.savez_compressed(OUT / (name+".npz"), dt_s=.0025, outputs=outputs,
                            power_w=input_power, balance_j=balances,
                            fom_dt_1=case["outputs"], fom_dt_half=fine["outputs"],
                            fom_field_snapshots=case["snapshots"],
                            fine_field_snapshots=fine["snapshots"], snapshot_period_s=24.)
        checks = dict(reduction=case["max_field_error_k"] <= 1e-4 and case["rmse_k"] <= 2e-5,
                      energy=max(case["max_balance_j"], case["rom_balance_j"],
                                 fine["max_balance_j"], float(max(abs(balances)))) <= 1e-8,
                      temporal=time_error <= 1e-4, fast_replay=fast_error <= 1e-4)
        cases.append(dict(name=name, h=h, passed=all(checks.values()), checks=checks,
                          max_field_error_k=case["max_field_error_k"], rmse_k=case["rmse_k"],
                          fom_time_difference_k=time_error, fast_difference_k=fast_error,
                          max_fast_balance_j=float(max(abs(balances)))))
    timer = StatorThermalROM.from_npz(OUT / "inference.npz", h_w_m2_k=12., dt_s=.0025)
    rejections = {}
    for h in (2., 100.):
        try:
            StatorThermalROM.from_npz(OUT / "inference.npz", h_w_m2_k=h, dt_s=.0025)
        except ValueError:
            rejections[f"h={h:g}"] = True
        else:
            rejections[f"h={h:g}"] = False
    for name, power in (("negative", -fom["p0"]), ("over-power", 2.1*fom["p0"]),
                        ("nonfinite", float("inf"))):
        before = timer.state
        try:
            timer.step_average(power)
        except ValueError:
            rejections[name] = bool(np.array_equal(before, timer.state))
        else:
            rejections[name] = False
    for _ in range(1000):
        timer.step_average(fom["p0"])
    durations = []
    for _ in range(5000):
        start = time.perf_counter_ns()
        timer.step_average(fom["p0"])
        durations.append(time.perf_counter_ns()-start)
    np.savetxt(OUT / "step-times-ns.csv", durations, fmt="%d", header="duration_ns", comments="")
    for name, expected in frozen["frozen_sha256"].items():
        if digest(OUT / name) != expected:
            raise ValueError("training artifact changed during validation")
    summary = dict(passed=all(c["passed"] for c in cases) and all(rejections.values())
                   and np.percentile(durations, 95) <= 2.5e6,
                   cases=cases, dimensions=frozen["dimensions"],
                   p95_ns=float(np.percentile(durations, 95)),
                   p50_ns=float(np.percentile(durations, 50)), max_ns=int(max(durations)),
                   platform=platform.platform(), processor=platform.processor(),
                   numpy_version=np.__version__, domain_rejections=rejections,
                   frozen_unchanged=True,
                   frozen_sha256=digest(OUT / "frozen.json"), evidence_kind="model_simulated",
                   producer_sha256=digest(Path(__file__)))
    summary["passed"] = bool(summary["passed"])
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    manifest = {p.relative_to(OUT).as_posix(): digest(p) for p in OUT.rglob("*")
                if p.is_file() and p.name != "manifest.json"}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("train", "validate"))
    args = parser.parse_args()
    (train if args.stage == "train" else validate)()
