"""Real Gmsh CLI meshes and scikit-fem P1 steady thermal solutions."""
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
from p7_fea_reference import (
    AMBIENT_C,
    CONDUCTIVITY_W_PER_M_K,
    LENGTH_M,
    THICKNESS_M,
    exact_norms,
    exact_total_power_w,
    gradient,
    rise,
    source_w_per_m3,
)
from skfem import (
    Basis,
    BilinearForm,
    ElementTriP1,
    FacetBasis,
    Functional,
    LinearForm,
    MeshTri,
    condense,
    solve,
)
from skfem.helpers import dot, grad

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-fea-baseline"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def geometry(n):
    return f"""
L = {LENGTH_M};
Point(1) = {{0,0,0}}; Point(2) = {{L,0,0}};
Point(3) = {{L,L,0}}; Point(4) = {{0,L,0}};
Line(1) = {{1,2}}; Line(2) = {{2,3}}; Line(3) = {{3,4}}; Line(4) = {{4,1}};
Curve Loop(1) = {{1,2,3,4}}; Plane Surface(1) = {{1}};
Transfinite Curve {{1,2,3,4}} = {n+1};
Transfinite Surface {{1}} = {{1,2,3,4}};
Physical Curve("bottom",1) = {{1}}; Physical Curve("right",2) = {{2}};
Physical Curve("top",3) = {{3}}; Physical Curve("left",4) = {{4}};
Physical Surface("plate",10) = {{1}};
Mesh.ElementOrder = 1; Mesh.MshFileVersion = 2.2;
Mesh.RandomFactor = 0; General.NumThreads = 1;
"""


def run_mesh(n, folder):
    geo = folder / "plate.geo"
    geo.write_text(geometry(n))
    paths = [folder / "plate.msh", folder / "repeat.msh"]
    for i, path in enumerate(paths):
        command = ["gmsh", str(geo), "-2", "-format", "msh2", "-o", str(path), "-nt", "1"]
        run = subprocess.run(command, text=True, capture_output=True, timeout=120, check=True)
        (folder / f"gmsh-{i}.log").write_text(run.stdout+run.stderr)
    assert sha(paths[0]) == sha(paths[1]), "same-input mesh bytes must reproduce"
    return meshio.read(paths[0])


def execute(n):
    folder = OUT / f"n{n}"
    folder.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    raw = run_mesh(n, folder)
    triangles = raw.cells_dict["triangle"]
    lines = raw.cells_dict["line"]
    line_tags = raw.cell_data_dict["gmsh:physical"]["line"]
    assert set(line_tags) == {1,2,3,4}
    assert np.all(raw.cell_data_dict["gmsh:physical"]["triangle"] == 10)
    points = raw.points[:, :2]
    assert len(points) == (n+1)**2 and len(triangles) == 2*n*n
    assert np.allclose(points.min(axis=0), 0., atol=1e-12)
    assert np.allclose(points.max(axis=0), LENGTH_M, atol=1e-12)
    vertices = points[triangles]
    cross = ((vertices[:,1,0]-vertices[:,0,0])*(vertices[:,2,1]-vertices[:,0,1])
             -(vertices[:,1,1]-vertices[:,0,1])*(vertices[:,2,0]-vertices[:,0,0]))
    area = abs(cross)/2
    side_squared = sum(np.sum((vertices[:,i]-vertices[:,(i+1) % 3])**2, axis=1)
                       for i in range(3))
    quality = 4*np.sqrt(3)*area/side_squared
    assert min(quality) >= .8 and abs(area.sum()-LENGTH_M**2) < 1e-12
    lengths = {}
    # Boundary identity includes geometry, not merely presence of numeric tags.
    for tag, axis, coordinate in ((1,1,0.),(2,0,LENGTH_M),(3,1,LENGTH_M),(4,0,0.)):
        segments = lines[line_tags == tag]
        assert len(segments) == n
        assert np.max(abs(points[segments, axis]-coordinate)) < 1e-12
        lengths[str(tag)] = float(np.linalg.norm(
            points[segments[:,1]]-points[segments[:,0]], axis=1).sum())
        assert abs(lengths[str(tag)]-LENGTH_M) < 1e-12
    mesh = MeshTri(points.T, triangles.T)
    boundary = np.unique(lines)
    assert np.array_equal(boundary, np.sort(mesh.boundary_nodes()))
    basis = Basis(mesh, ElementTriP1(), intorder=6)
    k, thickness = CONDUCTIVITY_W_PER_M_K, THICKNESS_M

    @BilinearForm
    def conduction(u, v, w):
        return k*thickness*dot(grad(u), grad(v))

    @LinearForm
    def thermal_source(v, w):
        return thickness*source_w_per_m3(w.x[0], w.x[1])*v

    matrix, load = conduction.assemble(basis), thermal_source.assemble(basis)
    before_solve = time.perf_counter()
    temperature_rise = solve(*condense(matrix, load, D=boundary))
    solve_s = time.perf_counter()-before_solve
    field = basis.interpolate(temperature_rise)

    @Functional
    def l2_error(w):
        return (w.uh-rise(w.x[0], w.x[1]))**2

    @Functional
    def h1_error(w):
        difference = w.uh.grad-gradient(w.x[0], w.x[1])
        return np.sum(difference**2, axis=0)

    norm_l2, norm_h1 = exact_norms()
    l2 = float(np.sqrt(l2_error.assemble(basis, uh=field))/norm_l2)
    h1 = float(np.sqrt(h1_error.assemble(basis, uh=field))/norm_h1)
    residual = matrix @ temperature_rise-load
    free = np.setdiff1d(np.arange(len(points)), boundary)
    normalized_residual = float(max(abs(residual[free]))/max(abs(load)))
    source = float(load.sum())
    reaction = float(-residual[boundary].sum())
    facets = FacetBasis(mesh, ElementTriP1(), facets=mesh.boundary_facets(), intorder=6)
    boundary_field = facets.interpolate(temperature_rise)
    direct_flux = float(np.sum(-k*thickness*np.sum(
        boundary_field.grad*facets.normals, axis=0)*facets.dx))
    power = exact_total_power_w()
    values = temperature_rise+AMBIENT_C
    exact = rise(points[:,0], points[:,1])+AMBIENT_C
    np.savetxt(folder / "nodes.csv", np.column_stack([points,values,exact,values-exact]),
               delimiter=",", header="x_m,y_m,temperature_c,exact_c,error_k", comments="")
    np.savetxt(folder / "free-residual.csv", np.column_stack([free,residual[free]]),
               delimiter=",", header="node,residual_w", comments="")
    meshio.write_points_cells(folder / "field.vtu", raw.points, [("triangle", triangles)],
                              point_data={"temperature_c":values, "exact_c":exact,
                                          "error_k":values-exact})
    np.savez_compressed(folder / "field.npz", points=points, triangles=triangles,
                        temperature_c=values, exact_c=exact)
    passed = bool(normalized_residual <= 1e-9 and abs(source/power-1) <= 1e-6
                  and abs(source-reaction)/power <= 1e-9)
    result = dict(n=n, nodes=len(points), triangles=len(triangles), passed=passed,
                  area_m2=float(area.sum()), min_quality=float(min(quality)),
                  boundary_lengths_m=lengths, mesh_reproduced=True,
                  mesh_sha256=sha(folder / "plate.msh"), l2_relative=l2, h1_relative=h1,
                  source_w=source, reaction_w=reaction, direct_boundary_flux_w=direct_flux,
                  direct_flux_relative_error=abs(direct_flux/power-1),
                  normalized_free_residual=normalized_residual,
                  reaction_balance_relative=abs(source-reaction)/power,
                  elapsed_s=time.perf_counter()-start, sparse_solve_s=solve_s)
    (folder / "result.json").write_text(json.dumps(result, indent=2))
    print("p7-fea-case: "+json.dumps(result), flush=True)
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = [execute(n) for n in (8,16,32)]
    l2_rates = [float(np.log2(a["l2_relative"]/b["l2_relative"]))
                for a,b in zip(results[:-1], results[1:], strict=True)]
    h1_rates = [float(np.log2(a["h1_relative"]/b["h1_relative"]))
                for a,b in zip(results[:-1], results[1:], strict=True)]
    checks = dict(all_mesh_and_balance=all(c["passed"] for c in results),
                  l2_order=min(l2_rates) >= 1.7, h1_order=min(h1_rates) >= .8,
                  fine_l2=results[-1]["l2_relative"] <= .005,
                  fine_h1=results[-1]["h1_relative"] <= .1,
                  direct_flux=results[-1]["direct_flux_relative_error"] <= .06)
    versions = {p:importlib.metadata.version(p)
                for p in ("gmsh","scikit-fem","meshio","scipy","numpy")}
    assert versions["gmsh"] == "4.13.1" and versions["scikit-fem"] == "11.0.0"
    report = dict(passed=all(checks.values()), checks=checks, cases=results,
                  l2_orders=l2_rates, h1_orders=h1_rates,
                  evidence_level="model_simulated", source_kind="analytic",
                  scope="manufactured 2D steady thermal FE; partial P7-A",
                  versions=versions, gmsh_cli_version=subprocess.check_output(
                      ["gmsh","-version"], text=True, stderr=subprocess.STDOUT).strip(),
                  commit=subprocess.check_output(["git","rev-parse","HEAD"], text=True).strip(),
                  host=dict(platform=platform.platform(), cpu=platform.processor(),
                            cpu_info=Path("/proc/cpuinfo").read_text(),
                            self_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                            children_peak_rss_kib=resource.getrusage(
                                resource.RUSAGE_CHILDREN).ru_maxrss))
    (OUT / "validation.json").write_text(json.dumps(report, indent=2))
    print("p7-fea-summary: "+json.dumps(report), flush=True)
    assert report["passed"], checks


if __name__ == "__main__":
    main()
