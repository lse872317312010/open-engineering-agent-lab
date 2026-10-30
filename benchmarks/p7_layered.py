"""Tagged two-material P1 heat conduction with Robin and insulated boundaries."""
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
from p7_layered_reference import (
    CASES,
    HEIGHT,
    PATCH,
    THICKNESS,
    A,
    L,
    gradient_x,
    norms,
    powers,
    temperature,
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
OUT = ROOT / "outputs/p7-layered"


def geometry(n):
    # Separate surfaces share curve7, not duplicated coincident nodes.
    return f"""
a={A}; L={L}; H={HEIGHT};
Point(1)={{0,0,0}}; Point(2)={{a,0,0}}; Point(3)={{L,0,0}};
Point(4)={{L,H,0}}; Point(5)={{a,H,0}}; Point(6)={{0,H,0}};
Line(1)={{1,2}}; Line(2)={{2,3}}; Line(3)={{3,4}};
Line(4)={{4,5}}; Line(5)={{5,6}}; Line(6)={{6,1}}; Line(7)={{2,5}};
Curve Loop(1)={{1,7,5,6}}; Plane Surface(1)={{1}};
Curve Loop(2)={{2,3,4,-7}}; Plane Surface(2)={{2}};
Transfinite Curve {{1,2,3,4,5,6,7}}={n+1};
Transfinite Surface {{1}}={{1,2,5,6}}; Transfinite Surface {{2}}={{2,3,4,5}};
Physical Curve("bottom",1)={{1,2}}; Physical Curve("right",2)={{3}};
Physical Curve("top",3)={{4,5}}; Physical Curve("left",4)={{6}};
Physical Curve("interface",5)={{7}};
Physical Surface("material-left",10)={{1}}; Physical Surface("material-right",20)={{2}};
Mesh.ElementOrder=1; Mesh.MshFileVersion=2.2; Mesh.RandomFactor=0; General.NumThreads=1;
"""


def material_identity(points, triangles, tags):
    centroid = points[triangles,0].mean(axis=1)
    if (set(tags) != {10,20} or np.any(tags[centroid < A] != 10)
            or np.any(tags[centroid > A] != 20)):
        raise ValueError("material physical tags do not match the frozen geometry")


def mesh_case(n, folder):
    folder.mkdir(parents=True, exist_ok=True)
    geo = folder / "plate.geo"
    geo.write_text(geometry(n))
    path = folder / "plate.msh"
    run = subprocess.run(["gmsh",str(geo),"-2","-format","msh2","-o",str(path),"-nt","1"],
                         capture_output=True,text=True,check=True,timeout=120)
    (folder / "gmsh.log").write_text(run.stdout+run.stderr)
    raw = meshio.read(path)
    points, triangles = raw.points[:,:2],raw.cells_dict["triangle"]
    tags = raw.cell_data_dict["gmsh:physical"]["triangle"]
    material_identity(points,triangles,tags)
    try:
        material_identity(points,triangles,30-tags)
        raise AssertionError("swapped material tags were accepted")
    except ValueError:
        pass
    assert len(points) == (2*n+1)*(n+1) and len(triangles) == 4*n*n
    mesh = MeshTri(points.T,triangles.T)
    assert np.array_equal(np.sort(mesh.t.T,axis=1),np.sort(triangles,axis=1))
    p = points[triangles]
    area = abs((p[:,1,0]-p[:,0,0])*(p[:,2,1]-p[:,0,1])
               -(p[:,1,1]-p[:,0,1])*(p[:,2,0]-p[:,0,0]))/2
    edge_squared = sum(np.sum((p[:,i]-p[:,(i+1) % 3])**2,axis=1) for i in range(3))
    quality = 4*np.sqrt(3)*area/edge_squared
    assert min(quality) >= .5
    assert abs(area[tags == 10].sum()-A*HEIGHT) < 1e-12
    assert abs(area[tags == 20].sum()-(L-A)*HEIGHT) < 1e-12
    lookup = {tuple(sorted(pair)):i for i,pair in enumerate(mesh.facets.T)}
    lines = raw.cells_dict["line"]
    line_tags = raw.cell_data_dict["gmsh:physical"]["line"]
    assert set(line_tags) == {1,2,3,4,5}
    facets = {}
    for tag,axis,value,length in ((1,1,0.,L),(2,0,L,HEIGHT),(3,1,HEIGHT,L),
                                  (4,0,0.,HEIGHT),(5,0,A,HEIGHT)):
        segment = lines[line_tags == tag]
        assert np.max(abs(points[segment,axis]-value)) < 1e-12
        measured = np.linalg.norm(points[segment[:,1]]-points[segment[:,0]],axis=1).sum()
        assert abs(measured-length) < 1e-12
        facets[tag] = np.array([lookup[tuple(sorted(pair))] for pair in segment])
    boundary = np.unique(np.concatenate([facets[t] for t in (1,2,3,4)]))
    assert np.array_equal(np.sort(boundary),np.sort(mesh.boundary_facets()))
    adjacent = mesh.f2t[:,facets[5]]
    assert np.all(adjacent >= 0)
    assert np.all(np.sort(tags[adjacent],axis=0) == np.array([[10],[20]]))
    return raw,mesh,tags,facets,float(min(quality))


def execute(case,n):
    folder = OUT / case["id"] / f"n{n}"
    started = time.perf_counter()
    raw,mesh,tags,facets,quality = mesh_case(n,folder)
    basis = Basis(mesh,ElementTriP1(),intorder=6)
    conductivity = np.where(tags == 10,case["k1"],case["k2"])
    source = np.where(tags == 10,case["s1"],case["s2"])
    right = FacetBasis(mesh,ElementTriP1(),facets=facets[2],intorder=6)

    @BilinearForm
    def conduction(u,v,w):
        return THICKNESS*conductivity[:,None]*dot(grad(u),grad(v))

    @BilinearForm
    def convection(u,v,w):
        return THICKNESS*case["h"]*u*v

    @LinearForm
    def forcing(v,w):
        return THICKNESS*source[:,None]*v

    matrix = conduction.assemble(basis)+convection.assemble(right)
    load = forcing.assemble(basis)
    left_nodes = np.unique(mesh.facets[:,facets[4]])
    initial = np.zeros(basis.N)
    initial[left_nodes] = case["left_c"]-case["ambient_c"]
    u = solve(*condense(matrix,load,x=initial,D=left_nodes))
    field = basis.interpolate(u)

    @Functional
    def l2(w):
        return (w.uh+case["ambient_c"]-temperature(w.x[0],case))**2

    @Functional
    def h1(w):
        return (w.uh.grad[0]-gradient_x(w.x[0],case))**2+w.uh.grad[1]**2

    norm = norms(case)
    l2_error = float(np.sqrt(l2.assemble(basis,uh=field))/norm[0])
    h1_error = float(np.sqrt(h1.assemble(basis,uh=field))/norm[1])
    residual = matrix @ u-load
    free = np.setdiff1d(np.arange(basis.N),left_nodes)
    load_scale = float(max(abs(load)))
    residual_scale = load_scale if load_scale > 0 else max(float(max(abs(matrix @ u))),1.)
    free_residual = float(max(abs(residual[free])))/residual_scale
    robin = float(THICKNESS*case["h"]*np.sum(right.interpolate(u)*right.dx))
    reaction = float(-residual[left_nodes].sum())
    source_power = float(load.sum())
    expected = powers(case)
    scale = max(abs(expected["source_w"]),abs(expected["left_out_w"]),
                abs(expected["right_out_w"]),1e-9)
    direct = {}
    for tag in (2,4):
        fb = FacetBasis(mesh,ElementTriP1(),facets=facets[tag],intorder=6)
        cells = mesh.f2t[0,facets[tag]]
        direct[tag] = float(-THICKNESS*np.sum(conductivity[cells,None]
                           *np.sum(fb.interpolate(u).grad*fb.normals,axis=0)*fb.dx))
    interface_rows = []
    for facet in facets[5]:
        pair = mesh.f2t[:,facet]
        left_cell = pair[np.flatnonzero(tags[pair] == 10)[0]]
        right_cell = pair[np.flatnonzero(tags[pair] == 20)[0]]
        vertices = mesh.facets[:,facet]
        length = np.linalg.norm(mesh.p[:,vertices[1]]-mesh.p[:,vertices[0]])
        gl = field.grad[0,left_cell,0]
        gr = field.grad[0,right_cell,0]
        interface_rows.append([float(mesh.p[1,vertices].mean()),float(length),
                               float(-case["k1"]*gl),float(-case["k2"]*gr)])
    interface = np.asarray(interface_rows)
    qleft,qright = (THICKNESS*np.sum(interface[:,i]*interface[:,1]) for i in (2,3))
    np.savetxt(folder / "interface.csv",interface,delimiter=",",comments="",
               header="y_mid_m,length_m,left_flux_right_w_per_m2,right_flux_right_w_per_m2")
    actual = u+case["ambient_c"]
    exact = temperature(mesh.p[0],case)
    np.savetxt(folder / "nodes.csv",np.column_stack([mesh.p.T,actual,exact,actual-exact]),
               delimiter=",",comments="",header="x_m,y_m,temperature_c,exact_c,error_k")
    cells = [("triangle",raw.cells_dict["triangle"])]
    meshio.write_points_cells(folder / "field.vtu",raw.points,cells,
                              point_data={"temperature_c":actual,"exact_c":exact,
                                          "error_k":actual-exact},
                              cell_data={"material_tag":[tags]})
    np.savez_compressed(folder / "field.npz",points=mesh.p.T,triangles=mesh.t.T,
                        temperature_c=actual,exact_c=exact,material_tag=tags)
    balance = abs(reaction+robin-source_power)/scale
    errors = dict(left=abs(direct[4]-expected["left_out_w"])/scale,
                  right=abs(direct[2]-expected["right_out_w"])/scale,
                  interface_left=abs(qleft-expected["interface_right_w"])/scale,
                  interface_right=abs(qright-expected["interface_right_w"])/scale,
                  interface_jump=abs(qleft-qright)/scale)
    result = dict(id=case["id"],config=case,n=n,nodes=int(mesh.nvertices),
                  triangles=int(mesh.nelements),
                  l2_relative=l2_error,h1_relative=h1_error,free_residual=free_residual,
                  source_w=source_power,left_out_w=reaction,right_out_w=robin,
                  direct_left_out_w=direct[4],direct_right_out_w=direct[2],
                  interface_left_right_w=float(qleft),interface_right_right_w=float(qright),
                  expected=expected,power_scale_w=scale,flux_errors=errors,
                  balance_relative=balance,min_quality=quality,swapped_material_tags_rejected=True,
                  source_error_relative=abs(source_power-expected["source_w"])/scale,
                  peak_node_error_k=float(max(abs(actual-exact))),
                  mesh_sha256=hashlib.sha256((folder / "plate.msh").read_bytes()).hexdigest(),
                  elapsed_s=time.perf_counter()-started,
                  passed=bool(balance <= 1e-9 and free_residual <= 1e-9
                              and abs(source_power-expected["source_w"])/scale <= 1e-9))
    (folder / "result.json").write_text(json.dumps(result,indent=2))
    print("p7-layered-case: "+json.dumps(result),flush=True)
    return result


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    version = subprocess.check_output(["gmsh","-version"],text=True,
                                      stderr=subprocess.STDOUT).strip()
    assert version == "4.13.1"
    cases = [execute(case,n) for case in CASES for n in (8,16,32)]
    patch = execute(PATCH,8)
    convergence = {}
    for case in CASES:
        group = [r for r in cases if r["id"] == case["id"]]
        rates = {key:[float(np.log2(a[key]/b[key])) for a,b in
                      zip(group[:-1],group[1:],strict=True)]
                 for key in ("l2_relative","h1_relative")}
        fine = group[-1]
        passed = bool(min(rates["l2_relative"]) >= 1.7 and min(rates["h1_relative"]) >= .8
                      and fine["l2_relative"] <= .005 and fine["h1_relative"] <= .1
                      and max(fine["flux_errors"].values()) <= .05)
        convergence[case["id"]] = dict(passed=passed,orders=rates)
    checks = dict(all_balance=all(c["passed"] for c in cases),
                  convergence=all(c["passed"] for c in convergence.values()),
                  zero_source_patch=patch["passed"] and patch["peak_node_error_k"] <= 1e-9,
                  ambient_supplies_heat=all(c["right_out_w"] < 0 for c in cases
                                           if c["id"] == "hot-ambient"))
    report = dict(passed=all(checks.values()),checks=checks,cases=cases,patch=patch,
                  convergence=convergence,evidence_level="model_simulated",source_kind="analytic",
                  scope="two-region ideal-contact steady slab; partial P7-A",
                  versions={p:importlib.metadata.version(p)
                            for p in ("gmsh","scikit-fem","meshio","scipy","numpy")},
                  host=dict(platform=platform.platform(),cpu_info=Path("/proc/cpuinfo").read_text(),
                            self_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                            children_peak_rss_kib=resource.getrusage(
                                resource.RUSAGE_CHILDREN).ru_maxrss),
                  commit=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip())
    (OUT / "validation.json").write_text(json.dumps(report,indent=2))
    print("p7-layered-summary: "+json.dumps(
        {k:v for k,v in report.items() if k not in {"cases","patch","host"}}),flush=True)
    assert report["passed"], checks


if __name__ == "__main__":
    main()
