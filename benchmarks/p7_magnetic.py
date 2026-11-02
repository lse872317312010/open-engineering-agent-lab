"""Real tagged magnetostatic Az FE; independent analytic field and circuit-L audit."""
import hashlib
import importlib.metadata
import json
import platform
import resource
import shutil
import subprocess
import time
from pathlib import Path

import meshio
import numpy as np
from p7_layered import geometry, mesh_case
from p7_magnetic_reference import CASES, DEPTH, HEIGHT, LENGTH, SPLIT, exact, inductance, norms
from scipy.sparse import save_npz
from skfem import Basis, BilinearForm, ElementTriP1, Functional, LinearForm, condense, solve
from skfem.helpers import dot, grad

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-magnetic"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assemble(mesh, tags, case):
    basis = Basis(mesh, ElementTriP1(), intorder=6)
    mu = np.where(tags == 10, case["mu_left"], case["mu_right"])
    winding = np.where(tags == 10, 1/(SPLIT*HEIGHT), -1/((LENGTH-SPLIT)*HEIGHT))

    @BilinearForm
    def reluctance(u, v, w):
        return DEPTH/mu[:, None]*dot(grad(u), grad(v))

    @LinearForm
    def unit_winding(v, w):
        return DEPTH*winding[:, None]*v

    return basis, reluctance.assemble(basis), unit_winding.assemble(basis), mu, winding


def execute(case, n, mesh_data):
    started = time.perf_counter()
    folder = OUT / case["id"] / f"n{n}"
    folder.mkdir(parents=True, exist_ok=True)
    raw, mesh, tags, facets, quality = mesh_data
    basis, matrix, unit_load, mu, winding = assemble(mesh, tags, case)
    current = case["current_a"]
    load = current*unit_load
    boundary = np.unique(mesh.facets[:, np.r_[facets[2], facets[4]]])
    az = solve(*condense(matrix, load, D=boundary))
    field = basis.interpolate(az)
    # Curl sign is explicit: Bx = dAz/dy; By = -dAz/dx.
    b = np.column_stack([field.grad[1, :, 0], -field.grad[0, :, 0]])
    h = b/mu[:, None]
    vertices = mesh.p.T[mesh.t.T]
    cross = ((vertices[:, 1, 0]-vertices[:, 0, 0])
             *(vertices[:, 2, 1]-vertices[:, 0, 1])
             -(vertices[:, 1, 1]-vertices[:, 0, 1])
             *(vertices[:, 2, 0]-vertices[:, 0, 0]))
    area = abs(cross)/2
    cell_energy = DEPTH*area*np.sum(b*b, axis=1)/(2*mu)
    energy = float(cell_energy.sum())
    matrix_energy = float(az @ (matrix @ az)/2)
    linkage = float(unit_load @ az)
    measured_l = linkage/current
    expected_l = inductance(case)
    free = np.setdiff1d(np.arange(basis.N), boundary)
    residual = matrix @ az-load

    @Functional
    def a_error(w):
        return (w.uh-exact(w.x[0], case)[0])**2

    @Functional
    def b_error(w):
        target = exact(w.x[0], case)
        return (w.uh.grad[1]-target[1])**2+(-w.uh.grad[0]-target[2])**2

    norm_a, norm_b = norms(case)
    error_a = float(np.sqrt(a_error.assemble(basis, uh=field))/norm_a)
    error_b = float(np.sqrt(b_error.assemble(basis, uh=field))/norm_b)
    regional_current = [float(np.sum(area[tags == tag]*winding[tags == tag])*current)
                        for tag in (10, 20)]
    shifted = float(unit_load @ (az+3*max(abs(az))))
    interface = []
    for facet in facets[5]:
        pair = mesh.f2t[:, facet]
        left = pair[np.flatnonzero(tags[pair] == 10)[0]]
        right = pair[np.flatnonzero(tags[pair] == 20)[0]]
        interface.append([float(mesh.p[1, mesh.facets[:, facet]].mean()),
                          h[left, 1], h[right, 1], current/(2*HEIGHT)])
    interface = np.array(interface)
    hscale = abs(current/(2*HEIGHT))
    interface_gap = float(max(abs(interface[:, 1]-interface[:, 2]))/hscale)
    interface_error = float(np.max(abs(interface[:, 1:3]-interface[:, 3, None]))/hscale)
    np.savetxt(folder / "nodes.csv",
               np.column_stack([mesh.p.T, az, exact(mesh.p[0], case)[0]]),
               delimiter=",", comments="", header="x_m,y_m,az_wb_per_m,analytic_az_wb_per_m")
    np.savetxt(folder / "cells.csv",
               np.column_stack([vertices.mean(axis=1), tags, area, mu,
                                winding*current, b, h, cell_energy]),
               delimiter=",", comments="",
               header="x_m,y_m,material_tag,area_m2,mu_h_per_m,jz_a_per_m2,"
                      "bx_t,by_t,hx_a_per_m,hy_a_per_m,energy_j")
    np.savetxt(folder / "interface.csv", interface, delimiter=",", comments="",
               header="y_m,left_hy_a_per_m,right_hy_a_per_m,analytic_hy_a_per_m")
    meshio.write_points_cells(
        folder / "field.vtu", raw.points, [("triangle", mesh.t.T)],
        point_data={"az_wb_per_m":az, "analytic_az_wb_per_m":exact(mesh.p[0], case)[0]},
        cell_data={"b_t":[np.column_stack([b, np.zeros(len(b))])], "material_tag":[tags],
                   "energy_j":[cell_energy]})
    np.savez_compressed(folder / "field.npz", points=mesh.p.T, triangles=mesh.t.T,
                        az=az, exact_az=exact(mesh.p[0], case)[0], b=b, h=h, mu=mu,
                        winding=winding, current_density=winding*current, tags=tags,
                        energy_j=cell_energy)
    save_npz(folder / "reluctance.npz", matrix)
    np.savez_compressed(folder / "unit-winding.npz", unit_load=unit_load, boundary=boundary)
    parameters = dict(
        format_version=1, quantity="bounded_single_turn_return_pair_inductance",
        inductance_h=measured_l, analytic_inductance_h=expected_l,
        flux_linkage_wb=linkage, field_energy_j=energy, current_a=current,
        current_convention="signed DC branch current; +left/-right; one turn",
        length_m=LENGTH, height_m=HEIGHT, depth_m=DEPTH, split_m=SPLIT,
        mu_left_h_per_m=case["mu_left"], mu_right_h_per_m=case["mu_right"],
        boundary="Az=0 at x=0/L; dAz/dn=0 at y=0/H",
        source_kind="synthetic", evidence_level="model_simulated",
        scope="linear finite rectangular magnetostatics; not a PMSM Ld/Lq")
    (folder / "parameters.json").write_text(json.dumps(parameters, indent=2))
    energy_scale = abs(2*energy)
    result = dict(
        id=case["id"], n=n, current_a=current, nodes=int(basis.N), triangles=len(mesh.t.T),
        min_quality=quality, az_l2_relative=error_a, b_l2_relative=error_b,
        inductance_h=measured_l, analytic_inductance_h=expected_l,
        inductance_relative_error=abs(measured_l/expected_l-1),
        energy_j=energy, linkage_wb=linkage,
        geometry_matrix_energy_relative=abs(energy-matrix_energy)/energy,
        linkage_energy_relative=abs(linkage*current-2*energy)/energy_scale,
        gauge_linkage_relative=abs(shifted-linkage)/abs(linkage),
        regional_current_a=regional_current,
        current_integral_relative=max(abs(regional_current[0]-current),
                                      abs(regional_current[1]+current))/abs(current),
        net_current_relative=abs(sum(regional_current))/abs(current),
        free_residual_relative=float(max(abs(residual[free]))/max(abs(load))),
        interface_h_gap_relative=interface_gap, interface_h_error_relative=interface_error,
        elapsed_s=time.perf_counter()-started)
    result["passed"] = bool(
        result["free_residual_relative"] <= 1e-8 and result["current_integral_relative"] <= 1e-12
        and result["net_current_relative"] <= 1e-12
        and result["geometry_matrix_energy_relative"] <= 1e-10
        and result["linkage_energy_relative"] <= 1e-10 and result["gauge_linkage_relative"] <= 1e-10
        and interface_gap <= .05
        and (n != 32 or interface_error <= .05))
    (folder / "result.json").write_text(json.dumps(result, indent=2))
    print("p7-magnetic-case: "+json.dumps(result), flush=True)
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cli = subprocess.check_output(["gmsh", "-version"], text=True,
                                  stderr=subprocess.STDOUT).strip()
    assert cli == "4.13.1"
    meshes, mesh_hashes = {}, {}
    for n in (8, 16, 32):
        folder, repeat = OUT / "meshes" / f"n{n}", OUT / "meshes" / f"repeat{n}"
        original = OUT / "original-meshes" / f"n{n}"
        mesh_case(n, original)
        expected_hash = {
            8:"034e105f617224bcd40a60a26adf370dde51e9c441e91406cdef86a4776f4700",
            16:"b6fac4d4c7738bf09c133841fb549be2b32f4ee4eaa90fc8053cac10e478a23d",
            32:"76ae8585856dd02e34b255e112c02114f2efc9368ad633c5e9078c4b261cf3b1",
        }[n]
        assert sha(original / "plate.msh") == expected_hash, "old default mesh changed"
        alternate = geometry(n).replace("={1,2,5,6};", "={1,2,5,6} Alternate;")
        alternate = alternate.replace("={2,3,4,5};", "={2,3,4,5} Alternate;")
        meshes[n] = mesh_case(n, folder, geometry_text=alternate)
        mesh_case(n, repeat, geometry_text=alternate)
        assert sha(folder / "plate.msh") == sha(repeat / "plate.msh")
        mesh_hashes[str(n)] = sha(folder / "plate.msh")
    results = [execute(c, n, meshes[n]) for c in CASES for n in (8, 16, 32)]
    convergence = {}
    for case in CASES:
        group = [r for r in results if r["id"] == case["id"]]
        rates = {key:[float(np.log2(a[key]/b[key])) for a, b in
                      zip(group[:-1], group[1:], strict=True)]
                 for key in ("az_l2_relative", "b_l2_relative", "inductance_relative_error")}
        rates["passed"] = bool(
            min(rates["az_l2_relative"]) >= 1.7 and min(rates["b_l2_relative"]) >= .8
            and min(rates["inductance_relative_error"]) >= 1.7
            and group[-1]["az_l2_relative"] <= .005 and group[-1]["b_l2_relative"] <= .05
            and group[-1]["inductance_relative_error"] <= .002)
        convergence[case["id"]] = rates
    linear_errors = []
    for n in (8, 16, 32):
        fields = [np.load(OUT / c / f"n{n}/field.npz") for c in
                  ("contrast", "reverse", "double")]
        for key in ("az", "b"):
            scale = max(abs(fields[0][key]).ravel())
            linear_errors.extend([float(np.max(abs(fields[1][key]+fields[0][key]))/scale),
                                  float(np.max(abs(fields[2][key]-2*fields[0][key]))/scale)])
        rows = [next(r for r in results if r["id"] == c and r["n"] == n)
                for c in ("contrast", "reverse", "double")]
        for key, reverse_factor, double_factor in (
            ("energy_j", 1, 4), ("linkage_wb", -1, 2), ("inductance_h", 1, 1)):
            value = rows[0][key]
            linear_errors.extend([abs(rows[1][key]-reverse_factor*value)/abs(value),
                                  abs(rows[2][key]-double_factor*value)/abs(value)])
    raw, mesh, tags, facets, _ = meshes[32]
    basis, matrix, winding_load, mu, winding = assemble(mesh, tags, CASES[1])
    boundary = np.unique(mesh.facets[:, np.r_[facets[2], facets[4]]])
    zero = solve(*condense(matrix, np.zeros(basis.N), D=boundary))
    zero_error = float(max(abs(zero)))
    np.savez_compressed(OUT / "zero-current.npz", az=zero, b=basis.interpolate(zero).grad)
    f = np.load(OUT / "contrast/n32/field.npz")
    row = next(r for r in results if r["id"] == "contrast" and r["n"] == 32)
    # These corrupted copies are diagnostics; actual assembled equations stay frozen.
    sign_fault = float(np.sqrt(np.sum((f["b"]+f["b"])**2)/np.sum(f["b"]**2)))
    depth_fault = abs(row["inductance_h"]/DEPTH/row["analytic_inductance_h"]-1)

    @LinearForm
    def wrong_return(v, w):
        return DEPTH*abs(winding[:, None])*v

    bad = wrong_return.assemble(basis)
    gauge_fault = float(abs(bad @ (f["az"]+3*max(abs(f["az"])))-bad @ f["az"])
                        /abs(row["linkage_wb"]))
    faults = dict(reversed_b_relative=sign_fault, missing_depth_l_relative=depth_fault,
                  wrong_return_gauge_relative=gauge_fault)
    checks = dict(
        all_cases=all(r["passed"] for r in results),
        mesh_hashes_repeated=True, convergence=all(r["passed"] for r in convergence.values()),
        linear_scaling=max(linear_errors) <= 1e-10, zero_current=zero_error == 0,
        fault_sign=sign_fault > 1, fault_depth=depth_fault > 1, fault_return=gauge_fault > .1)
    versions = {p:importlib.metadata.version(p) for p in
                ("numpy", "scipy", "gmsh", "scikit-fem", "meshio")}
    assert versions["gmsh"] == "4.13.1" and versions["scikit-fem"] == "11.0.0"
    report = dict(
        passed=bool(all(checks.values())), checks=checks, cases=results,
        convergence=convergence, linear_scaling_max_relative=float(max(linear_errors)),
        zero_current_max_az=zero_error, faults=faults, mesh_sha256=mesh_hashes, versions=versions,
        source_kind="synthetic", evidence_level="model_simulated",
        reference_kind="independent analytic Ampere/energy; not another field solver",
        mesh_pattern="alternating diagonals; original default meshes reproduced",
        original_grid=json.loads(
            (ROOT / "benchmarks/p7-magnetic-original-grid.json").read_text()),
        scope="bounded return-current pair magnetostatics; partial P7-A toward P7-B",
        commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        host=dict(platform=platform.platform(), cpu_info=Path("/proc/cpuinfo").read_text(),
                  peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
    (OUT / "validation.json").write_text(json.dumps(report, indent=2))
    shutil.copyfile(ROOT / "docs/p7-magnetic-contract.md", OUT / "contract.md")
    print("p7-magnetic-summary: "+json.dumps(
        {k:v for k, v in report.items()
         if k not in {"cases", "host", "original_grid"}}), flush=True)
    assert report["passed"], checks


if __name__ == "__main__":
    main()
