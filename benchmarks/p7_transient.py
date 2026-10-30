"""Consistent-mass contact FE, CN time stepping and independent reference gates."""
import hashlib
import importlib.metadata
import json
import platform
import resource
import subprocess
import time
from pathlib import Path

import meshio
import numpy as np
from p7_contact import solve_contact
from p7_contact_reference import BASE, LENGTH, THICKNESS
from p7_layered import mesh_case
from p7_transient_reference import (
    fe_modal,
    finite_volume,
    interpolate_reference,
    pulse,
    pulse_integral,
)
from scipy.sparse import block_diag, save_npz
from scipy.sparse.linalg import factorized
from skfem import BilinearForm, ElementTriP1, FacetBasis, LinearForm

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-transient"
TIMES = np.array([2., 4., 8., 12., 16.])
CONFIG = dict(BASE, left_c=25., rc=.1)
COLUMNS = [
    "time_s", "source_fraction", "left_mean_c", "right_mean_c", "interface_left_c",
    "interface_right_c", "source_step_w", "left_out_step_w", "right_out_step_w",
    "interface_right_step_w", "left_stored_j", "right_stored_j", "stored_j",
    "input_j", "left_out_j", "right_out_j", "interface_right_j",
    "global_balance_j", "left_balance_j", "right_balance_j", "free_residual",
    "continuous_input_j", "fault_balance_j",
]


def assemble(n, capacities, folder):
    _, mesh, tags, facets, quality = mesh_case(n, folder)
    data = solve_contact(mesh, tags, facets, CONFIG)
    blocks, weights, region_capacity, points, triangles = [], [], [], [], []
    offset = 0
    sources = []
    for side, (submesh, basis) in enumerate(zip(data["meshes"], data["bases"], strict=True)):
        cv = capacities[side]

        @BilinearForm
        def storage(u, v, w):
            return THICKNESS*cv*u*v  # noqa: B023

        blocks.append(storage.assemble(basis))
        p = submesh.p[:, submesh.t].transpose(2, 1, 0)
        area = abs((p[:, 1, 0]-p[:, 0, 0])*(p[:, 2, 1]-p[:, 0, 1])
                   -(p[:, 1, 1]-p[:, 0, 1])*(p[:, 2, 0]-p[:, 0, 0]))/2
        node_weight = np.zeros(submesh.nvertices)
        np.add.at(node_weight, submesh.t.T.ravel(),
                  np.repeat(area*THICKNESS*cv/3, 3))
        weights.extend(node_weight)
        region_capacity.append(float(area.sum()*THICKNESS*cv))
        sources.append(float(area.sum()*THICKNESS*CONFIG["s"+str(side+1)]))
        points.extend(submesh.p.T)
        triangles.extend(submesh.t.T+offset)
        offset += submesh.nvertices
    mass = block_diag(blocks, format="csr")
    stiffness = data["matrix"]
    weights = np.array(weights)
    capacity_error = float(max(abs(np.asarray(mass.sum(axis=0)).ravel()-weights)))
    assert capacity_error <= 1e-12
    assert abs(sum(region_capacity)-(.04*capacities[0]+.06*capacities[1])*.001) <= 1e-12
    symmetry = max(float(abs(matrix-matrix.T).max()) for matrix in (mass, stiffness))
    assert symmetry <= 1e-12
    contact = np.zeros(len(weights))
    il, ir = np.zeros(len(weights)), np.zeros(len(weights))
    for _, left, right, length, _ in data["segments"]:
        contact[left] += THICKNESS/CONFIG["rc"]*length/2
        contact[right] -= THICKNESS/CONFIG["rc"]*length/2
        il[left] += length/.1/2
        ir[right] += length/.1/2
    right_mesh = data["meshes"][1]
    right_basis = FacetBasis(right_mesh, ElementTriP1(),
                            facets=right_mesh.facets_satisfying(
                                lambda x: abs(x[0]-LENGTH) < 1e-12), intorder=6)

    @LinearForm
    def convection(v, w):
        return THICKNESS*CONFIG["h"]*v

    right_op = np.r_[np.zeros(data["offset"]), convection.assemble(right_basis)]
    fixed = np.flatnonzero(abs(data["meshes"][0].p[0]) < 1e-12)
    free = np.setdiff1d(np.arange(len(weights)), fixed)
    data.update(mass=mass, weights=weights, capacities=region_capacity, sources=sources,
                points=np.array(points), triangles=np.array(triangles), contact=contact,
                il=il, ir=ir, right_op=right_op, fixed=fixed, free=free,
                capacity_error=capacity_error, symmetry=symmetry, quality=quality)
    return data


def execute(n, dt, capacity_scale=1.):
    started = time.perf_counter()
    name = f"n{n}-dt{dt:g}" if capacity_scale == 1 else "double-capacity"
    folder = OUT / name
    period = 8*capacity_scale
    capacities = np.array([1000., 2000.])*capacity_scale
    data = assemble(n, capacities, folder)
    mass, stiffness, free, fixed = (data[k] for k in ("mass", "matrix", "free", "fixed"))
    mf, kf = mass[free][:, free], stiffness[free][:, free]
    count = round(2*period/dt)
    times = np.arange(count+1)*dt
    solver = factorized((mf+dt/2*kf).tocsc())
    advance = mf-dt/2*kf
    states = np.zeros((count+1, len(data["weights"])))
    rows = np.zeros((count+1, len(COLUMNS)))
    cumulative = np.zeros(4)
    bad_left = 0.
    offset = data["offset"]
    w1, w2 = data["weights"][:offset], data["weights"][offset:]
    rows[0, 2:6] = 25.
    for step in range(1, count+1):
        old = states[step-1]
        factor = float((pulse(times[step-1], period)+pulse(times[step], period))/2)
        states[step, free] = solver(advance@old[free]+dt*data["load"][free]*factor)
        current = states[step]
        derivative, middle = (current-old)/dt, (current+old)/2
        load = data["load"]*factor
        residual = mass@derivative+stiffness@middle-load
        denominator = max(float(np.max(abs(load))), .16/len(load))
        free_residual = float(max(abs(residual[free]))/denominator)
        left = float(-residual[fixed].sum())
        right = float(data["right_op"]@middle)
        contact = float(data["contact"]@middle)
        source = sum(data["sources"])*factor
        cumulative += dt*np.array([source, left, right, contact])
        # Deliberate fault: using steady reaction omits the fixed-row M*du/dt term.
        bad_left += -dt*float((stiffness@middle-load)[fixed].sum())
        e1, e2 = float(w1@current[:offset]), float(w2@current[offset:])
        ein, eleft, eright, ei = cumulative
        balance = [e1+e2-ein+eleft+eright,
                   e1-data["sources"][0]/sum(data["sources"])*ein+eleft+ei,
                   e2-data["sources"][1]/sum(data["sources"])*ein+eright-ei]
        rows[step] = [
            times[step], float(pulse(times[step], period)),
            25+e1/data["capacities"][0], 25+e2/data["capacities"][1],
            25+float(data["il"]@current), 25+float(data["ir"]@current),
            source, left, right, contact, e1, e2, e1+e2, *cumulative, *balance,
            free_residual, sum(data["sources"])*float(pulse_integral(times[step], period)),
            e1+e2-ein+bad_left+eright,
        ]
    max_balance = float(np.max(abs(rows[:, 17:20])))
    max_fault = float(np.max(abs(rows[:, 22])))
    metrics = dict(id=name, n=n, dt_s=dt, period_s=period, capacity_scale=capacity_scale,
                   config=CONFIG, volumetric_capacity_j_m3_k=capacities.tolist(),
                   nodes=len(data["weights"]), triangles=len(data["triangles"]),
                   rows=len(rows), columns=COLUMNS, capacities_j_k=data["capacities"],
                   max_balance_j=max_balance, max_free_residual=float(max(rows[:, 20])),
                   fault_max_balance_j=max_fault, fault_rejected=bool(max_fault > 1e-9),
                   continuous_source_error_j=float(max(abs(rows[:, 13]-rows[:, 21]))),
                   final_input_j=float(rows[-1, 13]), final_stored_j=float(rows[-1, 12]),
                   pulse_end_stored_j=float(rows[round(period/dt), 12]),
                   cooling_out_j=float((rows[-1, 14:16]-rows[round(period/dt), 14:16]).sum()),
                   capacity_error_j_k=data["capacity_error"], symmetry_error=data["symmetry"],
                   mismatch_rejected=data["mismatch_rejected"], min_quality=data["quality"],
                   mesh_sha256=hashlib.sha256((folder / "plate.msh").read_bytes()).hexdigest(),
                   elapsed_s=time.perf_counter()-started)
    metrics["passed"] = bool(
        max_balance <= 1e-9 and metrics["max_free_residual"] <= 1e-9
        and metrics["fault_rejected"] and metrics["mismatch_rejected"]
        and abs(metrics["final_input_j"]-.64*capacity_scale) <= 1e-12
        and metrics["final_stored_j"] < metrics["pulse_end_stored_j"]
        and metrics["cooling_out_j"] > 0
        and (dt > .05 or metrics["continuous_source_error_j"] <= 1e-4))
    np.savetxt(folder / "timeseries.csv", rows, delimiter=",", comments="", header=",".join(COLUMNS))
    node_csv = np.column_stack([
        np.repeat(times, len(data["weights"])), np.tile(np.arange(len(data["weights"])), len(times)),
        np.tile(data["points"], (len(times), 1)), (states+25).ravel()])
    np.savetxt(folder / "nodes.csv", node_csv, delimiter=",", comments="",
               header="time_s,node_id,x_m,y_m,temperature_c")
    np.savez_compressed(folder / "field.npz", points=data["points"], triangles=data["triangles"],
                        times=times, temperature_c=states+25, relative_c=states,
                        weights=data["weights"], rows=rows, free=free, fixed=fixed,
                        load_w=data["load"])
    save_npz(folder / "mass.npz", mass)
    save_npz(folder / "stiffness.npz", stiffness)
    for t in (0., period/2, period, 2*period):
        meshio.write_points_cells(folder / f"t{t:g}.vtu",
                                  np.column_stack([data["points"], np.zeros(len(data["weights"]))]),
                                  [("triangle", data["triangles"])],
                                  point_data={"temperature_c":states[round(t/dt)]+25})
    if n == 8 and capacity_scale == 1:
        exact = fe_modal(mf, kf, data["load"][free], times)
        error = states[:, free]-exact
        numerator = np.sum(error*(mf@error.T).T)
        denominator = np.sum(exact*(mf@exact.T).T)
        metrics["time_rms_relative"] = float(np.sqrt(numerator/denominator))
        metrics["time_peak_error_k"] = float(np.max(abs(error)))
        np.savez_compressed(folder / "modal-reference.npz", times=times, relative_c=exact,
                            free=free)
    (folder / "result.json").write_text(json.dumps(metrics, indent=2))
    print("p7-transient-case: "+json.dumps(metrics), flush=True)
    return metrics, data, states, rows


def spatial_error(data, states, reference):
    squared, norm = 0., 0.
    offset = data["offset"]
    for side, basis in enumerate(data["bases"]):
        nodes = states[:, :offset] if side == 0 else states[:, offset:]
        x = basis.global_coordinates()[0]
        expected = interpolate_reference(reference, x.ravel(), 10 if side == 0 else 20)
        expected = expected.reshape(len(TIMES), *x.shape)
        actual = np.array([basis.interpolate(u) for u in nodes])
        squared += np.sum((actual-expected)**2*basis.dx)
        norm += np.sum(expected**2*basis.dx)
    return float(np.sqrt(squared/norm))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    assert subprocess.check_output(["gmsh", "-version"], stderr=subprocess.STDOUT,
                                   text=True).strip() == "4.13.1"
    references = [finite_volume(CONFIG, [1000., 2000.], n, TIMES) for n in (512, 1024)]
    numerator, denominator = 0., 0.
    for region, a, b in ((10, 0., .04), (20, .04, .1)):
        x = np.linspace(a, b, 2049)
        coarse, fine = [interpolate_reference(r, x, region) for r in references]
        numerator += np.trapz((coarse-fine)**2, x, axis=1).sum()
        denominator += np.trapz(fine**2, x, axis=1).sum()
    reference_difference = float(np.sqrt(numerator/denominator))
    reference_ok = reference_difference <= 1e-4
    for ref in references:
        np.savez_compressed(OUT / f"fv-reference-{ref['n']}.npz", **ref)
    assert reference_ok, reference_difference
    cases, time_results, spatial_results = [], [], []
    baseline = None
    for n in (8, 16, 32):
        saved = {}
        for dt in (.2, .1, .05):
            metrics, data, states, rows = execute(n, dt)
            cases.append(metrics)
            if n == 8:
                time_results.append(metrics)
            saved[dt] = states[np.round(TIMES/dt).astype(int)]
            if n == 16 and dt == .05:
                baseline = (states, rows)
        extrapolated = (4*saved[.05]-saved[.1])/3
        spatial_results.append(dict(
            n=n, richardson_rms_relative=spatial_error(data, extrapolated, references[-1]),
            cn_dt005_rms_relative=spatial_error(data, saved[.05], references[-1])))
    temporal_orders = [float(np.log2(a["time_rms_relative"]/b["time_rms_relative"]))
                       for a, b in zip(time_results[:-1], time_results[1:], strict=True)]
    spatial_orders = [float(np.log2(a["richardson_rms_relative"]/b["richardson_rms_relative"]))
                      for a, b in zip(spatial_results[:-1], spatial_results[1:], strict=True)]
    scaled, _, double_states, double_rows = execute(16, .1, capacity_scale=2.)
    scaling_temperature = float(np.max(abs(double_states-baseline[0])))
    scaling_energy = float(np.max(abs(double_rows[:, 10:17]-2*baseline[1][:, 10:17])))
    checks = dict(
        references=reference_ok, all_cases=all(c["passed"] for c in cases+[scaled]),
        time_convergence=min(temporal_orders) >= 1.7
        and time_results[-1]["time_rms_relative"] <= .002
        and time_results[-1]["time_peak_error_k"] <= .02,
        spatial_convergence=min(spatial_orders) >= 1.5
        and spatial_results[-1]["richardson_rms_relative"] <= .005,
        capacity_scaling=scaling_temperature <= 1e-9 and scaling_energy <= 1e-9,
        mesh_repeat=all(len({c["mesh_sha256"] for c in cases if c["n"] == n}) == 1
                        for n in (8, 16, 32)))
    report = dict(
        passed=bool(all(checks.values())), checks={k:bool(v) for k, v in checks.items()},
        cases=cases, scaled=scaled, time_orders=temporal_orders, space_orders=spatial_orders,
        spatial=spatial_results, fv_refinement_relative=reference_difference,
        scaling_temperature_error_k=scaling_temperature, scaling_energy_error_j=scaling_energy,
        evidence_level="model_simulated", source_kind="synthetic",
        reference_types=["same_FE_exact_modal_time", "independent_1D_finite_volume"],
        scope="idealized transient contact slab, not engineering P7-C or ROM",
        config=CONFIG, sample_times_s=TIMES.tolist(), columns=COLUMNS,
        commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        versions={p:importlib.metadata.version(p) for p in
                  ("gmsh", "scikit-fem", "meshio", "scipy", "numpy")},
        host=dict(platform=platform.platform(), cpu_info=Path("/proc/cpuinfo").read_text(),
                  self_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  children_peak_rss_kib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss))
    (OUT / "validation.json").write_text(json.dumps(report, indent=2))
    print("p7-transient-summary: "+json.dumps({k:v for k, v in report.items()
                                            if k not in {"cases", "scaled", "host"}}), flush=True)
    assert report["passed"], checks


if __name__ == "__main__":
    main()
