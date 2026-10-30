"""Split P1 steady conduction with finite areal contact resistance."""
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
from p7_contact_reference import (
    CASES,
    HEIGHT,
    LENGTH,
    PATCH,
    THICKNESS,
    powers,
    temperature,
)
from p7_layered import mesh_case
from scipy.sparse import block_diag, coo_matrix, save_npz
from skfem import (
    Basis,
    BilinearForm,
    ElementTriP1,
    FacetBasis,
    LinearForm,
    MeshTri,
    condense,
    solve,
)
from skfem.helpers import dot, grad

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-contact"


def paired_nodes(left_ids, right_ids, left_points, right_points):
    if (not np.array_equal(left_ids, right_ids)
            or not np.allclose(left_points, right_points, atol=1e-13, rtol=0)):
        raise ValueError("interface original node IDs / coordinates do not match")


def solve_contact(mesh, tags, facets, c):
    """No exact fields enter assembly."""
    if c["rc"] <= 0:
        raise ValueError("finite contact resistance must be positive")
    blocks, loads, meshes, bases, ids, inverses = [], [], [], [], [], []
    for tag, k, source in ((10, c["k1"], c["s1"]), (20, c["k2"], c["s2"])):
        triangles = mesh.t[:, tags == tag]
        original = np.unique(triangles)
        inverse = np.full(mesh.nvertices, -1, dtype=int)
        inverse[original] = np.arange(len(original))
        submesh = MeshTri(mesh.p[:, original], inverse[triangles])
        basis = Basis(submesh, ElementTriP1(), intorder=6)

        @BilinearForm
        def conduction(u, v, w):
            return THICKNESS*k*dot(grad(u), grad(v))  # noqa: B023

        @LinearForm
        def forcing(v, w):
            return THICKNESS*source*v  # noqa: B023

        matrix = conduction.assemble(basis)
        if tag == 20:
            right_facets = submesh.facets_satisfying(lambda x: abs(x[0]-LENGTH) < 1e-12)
            right = FacetBasis(submesh, ElementTriP1(), facets=right_facets, intorder=6)

            @BilinearForm
            def robin(u, v, w):
                return THICKNESS*c["h"]*u*v

            matrix += robin.assemble(right)
        blocks.append(matrix)
        loads.append(forcing.assemble(basis))
        meshes.append(submesh)
        bases.append(basis)
        ids.append(original)
        inverses.append(inverse)
    offset = len(ids[0])
    interface_ids = np.unique(mesh.facets[:, facets[5]])
    il, ir = inverses[0][interface_ids], inverses[1][interface_ids]
    paired_nodes(ids[0][il], ids[1][ir], meshes[0].p[:, il], meshes[1].p[:, ir])
    rejected = False
    try:
        paired_nodes(ids[0][il], ids[1][ir[::-1]],
                     meshes[0].p[:, il], meshes[1].p[:, ir[::-1]])
    except ValueError:
        rejected = True
    assert rejected
    rows, cols, values, segments = [], [], [], []
    for facet in facets[5]:
        original = mesh.facets[:, facet]
        left, right_nodes = inverses[0][original], inverses[1][original]+offset
        length = float(np.linalg.norm(mesh.p[:, original[1]]-mesh.p[:, original[0]]))
        mass = length/6*np.array([[2., 1.], [1., 2.]])
        for row_nodes, row_sign in ((left, 1), (right_nodes, -1)):
            for col_nodes, col_sign in ((left, 1), (right_nodes, -1)):
                for i in range(2):
                    for j in range(2):
                        rows.append(int(row_nodes[i]))
                        cols.append(int(col_nodes[j]))
                        values.append(THICKNESS/c["rc"]*row_sign*col_sign*mass[i, j])
        segments.append((original, left, right_nodes, length, mass))
    matrix = block_diag(blocks, format="csr")
    matrix += coo_matrix((values, (rows, cols)), shape=matrix.shape).tocsr()
    load = np.concatenate(loads)
    fixed = np.flatnonzero(abs(meshes[0].p[0]) < 1e-12)
    initial = np.zeros(len(load))
    initial[fixed] = c["left_c"]-c["ambient_c"]
    u = solve(*condense(matrix, load, x=initial, D=fixed))
    residual = matrix@u-load
    free = np.setdiff1d(np.arange(len(u)), fixed)
    scale = max(float(np.max(abs(load))), float(np.max(abs(matrix@u))), 1e-12)
    right_power = float(THICKNESS*c["h"]*np.sum(right.interpolate(u[offset:])*right.dx))
    return dict(u=u, matrix=matrix, load=load, meshes=meshes, bases=bases, ids=ids,
                segments=segments, offset=offset, mismatch_rejected=rejected,
                left_out_w=float(-residual[fixed].sum()), right_out_w=right_power,
                free_residual=float(np.max(abs(residual[free]))/scale))


def execute(c, n):
    started = time.perf_counter()
    folder = OUT / c["id"] / f"n{n}"
    _, mesh, tags, facets, quality = mesh_case(n, folder)
    result = solve_contact(mesh, tags, facets, c)
    u = result["u"]
    actual = u+c["ambient_c"]
    expected = powers(c)
    scale = max(abs(expected[k]) for k in ("source_w", "left_out_w", "right_out_w"))
    offset = result["offset"]
    errors, norms, exact_nodes, sources, node_rows, points, triangles = [], [], [], [], [], [], []
    for side, tag in enumerate((10, 20)):
        submesh, basis = result["meshes"][side], result["bases"][side]
        start, stop = (0, offset) if side == 0 else (offset, len(u))
        field = basis.interpolate(u[start:stop])
        exact_quad = temperature(basis.global_coordinates()[0], c, tag)
        errors.append(float(np.sum((field+c["ambient_c"]-exact_quad)**2*basis.dx)))
        norms.append(float(np.sum((exact_quad-c["ambient_c"])**2*basis.dx)))
        exact = temperature(submesh.p[0], c, tag)
        exact_nodes.extend(exact)
        for i in range(submesh.nvertices):
            node_rows.append([int(result["ids"][side][i]), tag, *submesh.p[:, i],
                              actual[start+i], exact[i], actual[start+i]-exact[i]])
        p = submesh.p[:, submesh.t].transpose(2, 1, 0)
        area = abs((p[:, 1, 0]-p[:, 0, 0])*(p[:, 2, 1]-p[:, 0, 1])
                   -(p[:, 1, 1]-p[:, 0, 1])*(p[:, 2, 0]-p[:, 0, 0]))/2
        sources.append(float(area.sum()*THICKNESS*c["s"+str(side+1)]))
        points.extend(submesh.p.T.tolist())
        triangles.extend((submesh.t.T+start).tolist())
    qi = expected["interface_right_w"]/(HEIGHT*THICKNESS)
    interface_rows = []
    flux_error, jump_error, interface_power, jump_mean = 0., 0., 0., 0.
    for original, left, right, length, mass in result["segments"]:
        jump = u[left]-u[right]
        flux = jump/c["rc"]
        error_q, error_jump = flux-qi, jump-expected["jump_k"]
        flux_error += error_q@mass@error_q
        jump_error += error_jump@mass@error_jump
        interface_power += THICKNESS*length*float(flux.mean())
        jump_mean += length*float(jump.mean())/HEIGHT
        for i in range(2):
            interface_rows.append([int(original[i]), mesh.p[1, original[i]], actual[left[i]],
                                   actual[right[i]], jump[i], flux[i], qi])
    left, right = result["left_out_w"], result["right_out_w"]
    balances = [left+right-sum(sources), left+interface_power-sources[0],
                right-interface_power-sources[1]]
    power_errors = [abs(left-expected["left_out_w"]), abs(right-expected["right_out_w"]),
                    abs(interface_power-expected["interface_right_w"])]
    metrics = dict(id=c["id"], config=c, n=n, nodes=len(u), triangles=int(mesh.nelements),
                   min_quality=quality, l2_relative=float(np.sqrt(sum(errors)/sum(norms))),
                   peak_node_error_k=float(max(abs(actual-np.asarray(exact_nodes)))),
                   interface_rms_relative=float(np.sqrt(flux_error/HEIGHT)/abs(qi)),
                   jump_rms_relative=float(np.sqrt(jump_error/HEIGHT)/abs(expected["jump_k"])),
                   jump_mean_k=float(jump_mean), interface_right_w=float(interface_power),
                   source_w=sum(sources), region_sources_w=sources,
                   left_out_w=left, right_out_w=right, expected=expected,
                   power_scale_w=scale, power_error_relative=float(max(power_errors)/scale),
                   balances_w=[float(b) for b in balances],
                   balance_relative=float(max(abs(np.array(balances)))/scale),
                   free_residual=result["free_residual"],
                   mismatch_rejected=result["mismatch_rejected"],
                   mesh_sha256=hashlib.sha256((folder / "plate.msh").read_bytes()).hexdigest(),
                   elapsed_s=time.perf_counter()-started)
    metrics["passed"] = bool(metrics["balance_relative"] <= 1e-9
                             and metrics["free_residual"] <= 1e-9
                             and metrics["power_error_relative"] <= 1e-9
                             and metrics["mismatch_rejected"])
    np.savetxt(folder / "nodes.csv", node_rows, delimiter=",", comments="",
               header="original_id,material_tag,x_m,y_m,temperature_c,exact_c,error_k")
    np.savetxt(folder / "interface.csv", interface_rows, delimiter=",", comments="",
               header="original_id,y_m,left_c,right_c,jump_k,flux_right_w_m2,exact_flux_right_w_m2")
    np.savez_compressed(folder / "field.npz", points=points, triangles=triangles,
                        temperature_c=actual, exact_c=exact_nodes, solution_relative_c=u,
                        load_w=result["load"], interface_rows=interface_rows,
                        original_left_ids=result["ids"][0], original_right_ids=result["ids"][1])
    save_npz(folder / "matrix.npz", result["matrix"])
    meshio.write_points_cells(folder / "field.vtu",
                              np.column_stack([points, np.zeros(len(points))]),
                              [("triangle", np.array(triangles))],
                              point_data={"temperature_c":actual, "exact_c":np.array(exact_nodes)})
    (folder / "result.json").write_text(json.dumps(metrics, indent=2))
    print("p7-contact-case: "+json.dumps(metrics), flush=True)
    return metrics


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    assert subprocess.check_output(["gmsh", "-version"], stderr=subprocess.STDOUT,
                                   text=True).strip() == "4.13.1"
    cases = [execute(c, n) for c in CASES for n in (8, 16, 32)]
    patches = [execute(dict(PATCH, id=f"patch-{rc:g}", rc=rc), 8) for rc in (.01, .1, 1.)]
    convergence = {}
    for c in CASES:
        group = [r for r in cases if r["id"] == c["id"]]
        rates = [float(np.log2(a["l2_relative"]/b["l2_relative"])) for a, b in
                 zip(group[:-1], group[1:], strict=True)]
        f = group[-1]
        convergence[c["id"]] = dict(orders=rates, passed=bool(
            min(rates) >= 1.7 and f["l2_relative"] <= .005 and f["peak_node_error_k"] <= .05
            and f["interface_rms_relative"] <= .01 and f["jump_rms_relative"] <= .01))
    checks = dict(all_balances=all(c["passed"] for c in cases+patches),
                  convergence=all(c["passed"] for c in convergence.values()),
                  patch=all(c["peak_node_error_k"] <= 1e-9 for c in patches),
                  resistance_sensitivity=all(
                      a["interface_right_w"] > b["interface_right_w"] > 0 and
                      a["expected"]["interface_right_w"] > b["expected"]["interface_right_w"]
                      for a, b in zip(patches[:-1], patches[1:], strict=True)),
                  reverse_flow=all(c["right_out_w"] < 0 and c["interface_right_w"] < 0
                                   for c in cases if c["id"] == "hot-ambient"),
                  mesh_repeat=all(len({c["mesh_sha256"] for c in cases if c["n"] == n}) == 1
                                  for n in (8, 16, 32)))
    report = dict(passed=all(checks.values()), checks=checks, cases=cases, patches=patches,
                  convergence=convergence, evidence_level="model_simulated", source_kind="analytic",
                  scope="idealized 2D steady contact benchmark; not engineering P7-C",
                  commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                  versions={p:importlib.metadata.version(p) for p in
                            ("gmsh", "scikit-fem", "meshio", "scipy", "numpy")},
                  host=dict(platform=platform.platform(),
                            cpu_info=Path("/proc/cpuinfo").read_text(),
                            peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                            children_peak_rss_kib=resource.getrusage(
                                resource.RUSAGE_CHILDREN).ru_maxrss))
    (OUT / "validation.json").write_text(json.dumps(report, indent=2))
    print("p7-contact-summary: "+json.dumps({k:v for k, v in report.items()
                                           if k not in {"host", "cases", "patches"}}), flush=True)
    assert report["passed"], checks


if __name__ == "__main__":
    main()
