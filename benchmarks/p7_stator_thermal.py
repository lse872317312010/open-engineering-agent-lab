"""Same-geometry stator heat diffusion with synthetic materials and audited copper input."""
import csv
import importlib.metadata
import json

import meshio
import numpy as np
from p7_stator_partition import build_mesh
from p7_winding_heat import OUT as SOURCE_DIR
from p7_winding_heat import ROOT, SOURCE, digest
from scipy.sparse import coo_matrix, diags, save_npz
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import factorized
from skfem import Basis, BilinearForm, ElementTriP1, FacetBasis, Functional, condense, solve
from skfem.helpers import dot, grad

OUT = ROOT / "outputs/p7-stator-thermal"
THICKNESS, AMBIENT, H = .05, 25., 20.
CASES = ("forward-base", "forward-fine", "reverse-base", "reverse-fine")


def assemble(mesh, tags, outer):
    basis = Basis(mesh, ElementTriP1(), intorder=4)
    convection_basis = FacetBasis(mesh, ElementTriP1(), facets=outer, intorder=4)
    k = np.where(tags == 1, 25., 1.5)
    capacity = np.where(tags == 1, 3.5e6, 2.5e6)

    @BilinearForm
    def conduction(u, v, w):
        return THICKNESS*k[:, None]*dot(grad(u), grad(v))

    @BilinearForm
    def storage(u, v, w):
        return THICKNESS*capacity[:, None]*u*v

    @BilinearForm
    def convection(u, v, w):
        return THICKNESS*H*u*v

    mass = np.asarray(storage.assemble(basis).sum(axis=1)).ravel()
    robin = convection.assemble(convection_basis)
    stiffness = conduction.assemble(basis)+robin
    area = basis.dx.sum(axis=1)
    inputs = coo_matrix((np.repeat(area*THICKNESS/3, 3),
                         (mesh.t.T.ravel(), np.repeat(tags-1, 3))),
                        shape=(mesh.nvertices, 25)).tocsr()
    out = np.asarray(robin.sum(axis=0)).ravel()
    return basis, mass, stiffness, inputs, out, area


def validate_exposed_boundary(mesh, outer):
    exposed = np.setdiff1d(mesh.boundary_facets(), outer)
    radii = np.linalg.norm(mesh.p[:, np.unique(mesh.facets[:, exposed])], axis=0)
    if not np.allclose(radii, .02785, rtol=0, atol=1e-8):
        raise ValueError("exposed slot interface: perfect contact not established")


def validate_mesh(mesh, tags, outer, area, reference, level):
    from oeal.heat_sources import polygon_area_m2

    if set(tags) != set(range(1, 26)) or np.any(area <= 0):
        raise ValueError("positive elements and all 25 material labels required")
    if len(np.unique(np.round(mesh.p.T, 12), axis=0)) != mesh.nvertices:
        raise ValueError("duplicate interface nodes")
    edges = mesh.facets
    graph = coo_matrix((np.ones(edges.shape[1]), (edges[0], edges[1])),
                       shape=(mesh.nvertices, mesh.nvertices))
    if connected_components(graph, directed=False)[0] != 1:
        raise ValueError("stator thermal domain is disconnected")
    neighbours = mesh.f2t[:, mesh.f2t[1] >= 0]
    interfaces = tags[neighbours]
    for tag in range(2, 26):
        if not np.any(np.all(np.sort(interfaces, axis=0) == np.array([[1], [tag]]), axis=0)):
            raise ValueError("winding lacks conforming iron interface")
    if not np.all(np.isin(outer, mesh.boundary_facets())):
        raise ValueError("convection applied to internal facet")
    if not np.allclose(np.linalg.norm(mesh.p[:, np.unique(mesh.facets[:, outer])], axis=0),
                       .05, rtol=0, atol=1e-11):
        raise ValueError("wrong exterior convection boundary")
    validate_exposed_boundary(mesh, outer)
    core_error = abs(area[tags == 1].sum()/reference["reference"]["stator_core_m2"]-1)
    original = [polygon_area_m2(s["points"]) for s in reference["surfaces"][1:25]]
    native = reference["native_areas_m2"][1:]
    coil_errors = [abs(area[tags == tag].sum()/value-1)
                   for tag, value in enumerate(native, 2)]
    clipping = np.max(abs(np.array(native)/original-1))
    if (core_error > (.003, .001, .0003)[level] or max(coil_errors) > 1e-4
            or clipping > .001):
        raise ValueError("material area budget failed")
    return dict(nodes=int(mesh.nvertices), elements=int(mesh.nelements),
                core_area_relative_error=float(core_error),
                winding_area_relative_error=float(max(coil_errors)), connected=True,
                full_contact=True, original_winding_area_m2=original,
                clipped_winding_area_m2=native, clipping_relative_error=float(clipping))


def manufactured(basis):
    @BilinearForm
    def laplace(u, v, w):
        return dot(grad(u), grad(v))

    matrix = laplace.assemble(basis)
    boundary = basis.mesh.boundary_nodes()
    exact = np.sum(basis.doflocs**2, axis=0)
    @BilinearForm
    def unit_mass(u, v, w):
        return u*v

    nodal_area = np.asarray(unit_mass.assemble(basis).sum(axis=1)).ravel()
    solution = solve(*condense(matrix, -4*nodal_area, x=exact.copy(), D=boundary))

    @Functional
    def error(w):
        return (w.u-w.x[0]**2-w.x[1]**2)**2

    @Functional
    def norm(w):
        return (w.x[0]**2+w.x[1]**2)**2

    relative = np.sqrt(error.assemble(basis, u=basis.interpolate(solution))/norm.assemble(basis))
    affine = 1+basis.doflocs[0]-2*basis.doflocs[1]
    linear = solve(*condense(matrix, np.zeros(basis.N), x=affine.copy(), D=boundary))
    linear_error = float(np.max(abs(linear-affine)))
    if linear_error > 1e-10:
        raise ValueError("independent linear manufactured solution failed")
    return dict(relative_l2=float(relative), affine_max_error=linear_error)


def read_sources():
    summary = json.loads((SOURCE_DIR / "summary.json").read_text(encoding="utf-8"))
    if not summary["passed"] or summary["thermal_solve"]:
        raise ValueError("expected validated source-interface evidence")
    for name, expected in summary["output_sha256"].items():
        if digest(SOURCE_DIR / name) != expected:
            raise ValueError("copper source CSV integrity failure")
    with (SOURCE_DIR / "regions.csv").open(encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))
    geometry = json.loads(SOURCE.read_text(encoding="utf-8"))["geometry"]
    labels = [s["label"] for s in geometry["surfaces"][1:25]]
    result = {}
    for case in CASES:
        values = np.zeros((20, 25))
        source_energy = 0.
        for i in range(20):
            window = [r for r in rows if r["case"] == case and int(r["window"]) == i]
            if len(window) != 24 or {r["region"] for r in window} != set(labels):
                raise ValueError("missing or duplicate thermal source region")
            lookup = {r["region"]: r for r in window}
            values[i, 1:] = [float(lookup[n]["source_w_m3"]) for n in labels]
            source_energy += sum(float(r["energy_j"]) for r in window)
        if not np.isfinite(values).all() or np.any(values < 0):
            raise ValueError("physical heat source must be finite and nonnegative")
        volumes = np.r_[0., [float(next(r for r in rows if r["case"] == case
                                       and r["region"] == n)["volume_m3"]) for n in labels]]
        result[case] = values, source_energy, volumes
    return result


def run_case(mesh, mass, stiffness, inputs, boundary_out, forcing, energy, dt, folder):
    folder.mkdir(parents=True, exist_ok=True)
    solve_step = factorized((diags(mass)+dt*stiffness).tocsc())
    state = np.zeros(mesh.nvertices)
    volume = np.asarray(inputs.sum(axis=0)).ravel()
    rows, snapshots, snapshot_times = [], [state.copy()], [0.]
    source_j = out_j = max_balance = 0.
    for tick in range(1, round(1.05/dt)+1):
        # Integer clock: original 20 means, then exactly 1 s of zero-input cooling.
        source_index = (tick-1)//round(.0025/dt)
        density = forcing[source_index] if source_index < 20 else np.zeros(25)
        load = inputs@density
        state = solve_step(mass*state+dt*load)
        source_j += dt*float(sum(load))
        out_j += dt*float(boundary_out@state)
        stored = float(mass@state)
        balance = source_j-out_j-stored
        max_balance = max(max_balance, abs(balance))
        weighted = np.asarray(inputs.T@state).ravel()
        means = weighted/volume
        rows.append(dict(time_s=tick*dt, source_j=source_j, ambient_out_j=out_j,
                         stored_j=stored, balance_j=balance,
                         core_c=AMBIENT+means[0],
                         winding_c=AMBIENT+sum(weighted[1:])/sum(volume[1:]),
                         peak_c=AMBIENT+float(max(state)), min_c=AMBIENT+float(min(state))))
        if tick % round(.0025/dt) == 0 and source_index < 20 or tick % round(.1/dt) == 0:
            snapshots.append(state.copy())
            snapshot_times.append(tick*dt)
    snapshots.append(state.copy())
    snapshot_times.append(1.05)
    checks = dict(energy=max_balance <= 1e-9, input=abs(source_j-energy) <= 1e-10,
                  temperature=min(r["min_c"] for r in rows) >= AMBIENT-1e-6,
                  cooling=rows[-1]["stored_j"] <= rows[round(.05/dt)-1]["stored_j"])
    with (folder / "ledger.csv").open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    np.savez_compressed(folder / "field-snapshots.npz", time_s=snapshot_times,
                        rise_k=np.array(snapshots), points=mesh.p, triangles=mesh.t)
    meshio.write_points_cells(folder / "final.vtu", np.pad(mesh.p.T, ((0, 0), (0, 1))),
                              [("triangle", mesh.t.T)], point_data={"temperature_c": state+AMBIENT})
    return dict(passed=all(checks.values()), checks={k: bool(v) for k, v in checks.items()},
                dt_s=dt, max_balance_j=max_balance, source_difference_j=source_j-energy,
                pulse=rows[round(.05/dt)-1], final=rows[-1])


def main():
    sources = read_sources()
    results = []
    for level, size in enumerate((.004, .002, .001)):
        folder = OUT / f"mesh-{level}"
        mesh, tags, outer, reference = build_mesh(size, folder)
        basis, mass, stiffness, inputs, out, area = assemble(mesh, tags, outer)
        metadata = validate_mesh(mesh, tags, outer, area, reference, level)
        metadata["manufactured"] = manufactured(basis)
        metadata["size_m"] = size
        (folder / "mesh-summary.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        save_npz(folder / "stiffness.npz", stiffness)
        save_npz(folder / "volume-inputs.npz", inputs)
        np.savez(folder / "operators.npz", mass=mass, boundary_out=out, tags=tags)
        cases = {}
        for name, (density, energy, source_volumes) in sources.items():
            mesh_volumes = np.asarray(inputs.sum(axis=0)).ravel()
            projection = source_volumes/mesh_volumes
            if max(abs(projection[1:]-1)) > .001:
                raise ValueError("source projection exceeds geometric approximation budget")
            forcing = density*projection
            pair = [run_case(mesh, mass, stiffness, inputs, out, forcing, energy, dt,
                             folder / name / label)
                    for dt, label in ((.0025, "base"), (.00125, "half"))]
            difference = float(max(abs(pair[0][at][key]-pair[1][at][key])
                                   for at in ("pulse", "final")
                                   for key in ("core_c", "winding_c", "peak_c")))
            cases[name] = dict(runs=pair, time_difference_k=difference,
                               max_density_projection=float(max(abs(projection[1:]-1))),
                               unprojected_input_difference_j=float(
                                   .0025*np.sum(density@mesh_volumes)-energy),
                               passed=all(r["passed"] for r in pair) and difference <= 1e-6)
            (folder / name / "case-summary.json").write_text(
                json.dumps(cases[name], indent=2), encoding="utf-8")
        results.append(dict(mesh=metadata, cases=cases))
    mesh_difference = max(abs(results[1]["cases"][name]["runs"][0][at][key]
                              -results[2]["cases"][name]["runs"][0][at][key])
                          for name in CASES for at in ("pulse", "final")
                          for key in ("core_c", "winding_c", "peak_c"))
    errors = [r["mesh"]["manufactured"]["relative_l2"] for r in results]
    mesh_difference = float(mesh_difference)
    checks = dict(cases=all(c["passed"] for r in results for c in r["cases"].values()),
                  manufactured=errors[-1] <= .002 and errors[-1] < errors[0],
                  spatial=mesh_difference <= 1e-6)
    summary = dict(passed=all(checks.values()), checks=checks, results=results,
                   mesh_difference_k=mesh_difference, evidence_kind="model_simulated",
                   material_kind="synthetic", coupled_temperature_feedback=False,
                   source_sha256=digest(SOURCE_DIR / "summary.json"),
                   producer_sha256={p.name: digest(p) for p in (
                       ROOT / "benchmarks/p7_stator_thermal.py",
                       ROOT / "benchmarks/p7_stator_partition.py")},
                   versions={p: importlib.metadata.version(p)
                             for p in ("numpy", "scipy", "gmsh", "scikit-fem", "meshio")})
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    manifest = {p.relative_to(OUT).as_posix(): digest(p) for p in OUT.rglob("*")
                if p.is_file() and p.name != "manifest.json" and "probe" not in p.parts}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
