"""Independent evaluation of RT0 fluxes against unchanged P1 and analytic references."""
import hashlib
import json
import platform
import resource
import subprocess
import time
from pathlib import Path

import meshio
import numpy as np
from p7_flux_reconstruction import THICKNESS, project_flux
from p7_layered import mesh_case
from p7_layered_reference import A, flux_density

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/p7-layered"
OUT = ROOT / "outputs/p7-conservative"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(prior):
    case,n = prior["config"],prior["n"]
    started = time.perf_counter()
    source = SOURCE / case["id"] / f"n{n}"
    folder = OUT / case["id"] / f"n{n}"
    before = sha(source / "field.npz")
    data = np.load(source / "field.npz")
    original = data["temperature_c"].copy()
    raw,mesh,tags,facets,_ = mesh_case(n,folder)
    assert sha(folder / "plate.msh") == sha(source / "plate.msh")
    assert np.array_equal(data["points"],mesh.p.T)
    result = project_flux(mesh,tags,facets,original,case)
    assert np.array_equal(original,data["temperature_c"])
    assert before == sha(source / "field.npz")
    rt,field = result["rt"],result["field"]
    coordinates = rt.global_coordinates()
    exact = flux_density(coordinates[0],case)
    conductivity = np.where(tags == 10,case["k1"],case["k2"])
    old = -conductivity[None,:,None]*result["primal_gradient"]
    rt_error = (field[0]-exact)**2+field[1]**2
    old_error = (old[0]-exact)**2+old[1]**2
    norm = float(np.sqrt(np.sum(exact**2*rt.dx)))
    rt_l2 = float(np.sqrt(np.sum(rt_error*rt.dx))/norm)
    old_l2 = float(np.sqrt(np.sum(old_error*rt.dx))/norm)
    interface = facets[5]
    length = result["facet_lengths_m"][interface]
    density = (result["facet_integrals"][interface]/length
               *result["normals"][0,interface])
    truth = float(flux_density(A,case))
    pair = mesh.f2t[:,interface]
    left_cells = np.where(tags[pair[0]] == 10,pair[0],pair[1])
    right_cells = np.where(tags[pair[0]] == 20,pair[0],pair[1])
    old_left = -case["k1"]*result["primal_gradient"][0,left_cells,0]
    old_right = -case["k2"]*result["primal_gradient"][0,right_cells,0]

    def rms(value):
        return float(np.sqrt(np.sum((value-truth)**2*length)/sum(length))/abs(truth))

    interface_rms = rms(density)
    old_rms = max(rms(old_left),rms(old_right))
    mean = float(np.sum(density*length)/sum(length))
    integral_error = abs(mean-truth)/abs(truth)
    interface_csv = np.column_stack([result["facet_midpoints"][1,interface],length,
                                    old_left,old_right,density,np.full(len(length),truth)])
    np.savetxt(folder / "interface.csv",interface_csv,delimiter=",",comments="",
               header="y_m,length_m,p1_left_qx_w_m2,p1_right_qx_w_m2,rt_qx_w_m2,exact_qx_w_m2")
    area = result["cell_area_m2"]
    means = np.sum(field*rt.dx[None,:,:],axis=2)/area[None,:]
    center = mesh.p[:,mesh.t].mean(axis=1)
    cell_temperature = original[mesh.t].mean(axis=0)
    cell_source_w = THICKNESS*area*result["sources"]
    balance = result["cell_balance_w"]
    scale = prior["power_scale_w"]
    source_scale = np.where(abs(cell_source_w) > 0,abs(cell_source_w),scale/mesh.nelements)
    divergence = field.div[:,0]
    cells = np.column_stack([np.arange(mesh.nelements),center.T,means.T,cell_temperature,
                             result["sources"],divergence,cell_source_w,balance,
                             abs(balance)/source_scale])
    np.savetxt(folder / "cells.csv",cells,delimiter=",",comments="",
               header="cell,x_m,y_m,qx_w_m2,qy_w_m2,p1_temperature_c,source_w_m3,"
                      "divergence_w_m3,source_w,balance_w,scaled_cell_balance")
    facets_csv = np.column_stack([np.arange(mesh.nfacets),mesh.facets.T,
                                  result["facet_midpoints"].T,result["facet_lengths_m"],
                                  result["normals"].T,result["facet_integrals"],
                                  result["facet_integrals"]/result["facet_lengths_m"],
                                  flux_density(result["facet_midpoints"][0],case)
                                  *result["normals"][0]])
    np.savetxt(folder / "facets.csv",facets_csv,delimiter=",",comments="",
               header="facet,node0,node1,x_m,y_m,length_m,nx,ny,rt_integral_w_m,"
                      "rt_normal_w_m2,exact_normal_w_m2")
    meshio.write_points_cells(folder / "flux.vtu",raw.points,[("triangle",mesh.t.T)],
                              point_data={"p1_temperature_c":original},
                              cell_data={"rt_q_w_m2":[np.column_stack([means.T,
                                                                      np.zeros(mesh.nelements)])],
                                         "cell_balance_w":[balance],"material_tag":[tags]})
    np.savez_compressed(folder / "field.npz",points=mesh.p.T,triangles=mesh.t.T,cells=cells,
                        rt_coefficients=result["coefficients"],facet_dofs=rt.facet_dofs[0])
    boundary = result["boundary_power_w"]
    interface_power = THICKNESS*float(np.sum(density*length))
    source_power = float(cell_source_w.sum())
    global_balance = abs(sum(boundary.values())-source_power)/scale
    boundary_change = max(abs(boundary[4]-prior["left_out_w"]),
                          abs(boundary[2]-prior["right_out_w"]))/scale
    cell_balance = float(max(abs(balance)))/scale
    fault_detected = result["fault_max_balance_w"]/scale > 1e-6
    checks = dict(cell_balance=cell_balance <= 1e-9,
                  internal_normal_jump=result["normal_jump_w_per_m2"] <= 1e-8,
                  trace_matches_dofs=result["trace_integral_error_w_per_m"] <= 1e-9,
                  normals_match_geometry=result["normal_error"] <= 1e-12,
                  global_balance=global_balance <= 1e-9,
                  p1_boundary_power_preserved=boundary_change <= 1e-9,
                  flipped_facet_rejected=fault_detected)
    summary = dict(id=case["id"],config=case,n=n,nodes=int(mesh.nvertices),
                   triangles=int(mesh.nelements),facets=int(mesh.nfacets),
                   passed=all(checks.values()),checks=checks,rt_flux_l2_relative=rt_l2,
                   p1_flux_l2_relative=old_l2,interface_rms_relative=interface_rms,
                   p1_interface_rms_relative=old_rms,
                   rms_improvement=1-interface_rms/old_rms if old_rms > 0 else 0.,
                   interface_mean_relative_error=integral_error,
                   rt_interface_right_w=interface_power,
                   exact_interface_right_w=prior["expected"]["interface_right_w"],
                   left_out_w=boundary[4],right_out_w=boundary[2],source_w=source_power,
                   cell_balance_over_scale=cell_balance,
                   max_scaled_cell_balance=float(max(abs(balance)/source_scale)),
                   global_balance_over_scale=global_balance,
                   normal_jump_w_m2=result["normal_jump_w_per_m2"],
                   trace_integral_error_w_m=result["trace_integral_error_w_per_m"],
                   boundary_power_change_over_scale=boundary_change,
                   fault_max_balance_w=result["fault_max_balance_w"],
                   fault_facet=result["fault_facet"],
                   original_temperature_sha256=before,temperature_unchanged=True,
                   mesh_sha256=sha(folder / "plate.msh"),elapsed_s=time.perf_counter()-started)
    (folder / "result.json").write_text(json.dumps(summary,indent=2))
    print("p7-conservative-case: "+json.dumps(summary),flush=True)
    return summary


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    prior = json.loads((SOURCE / "validation.json").read_text())
    assert prior["passed"]
    cases = [evaluate(c) for c in prior["cases"]]
    patch = evaluate(prior["patch"])
    convergence = {}
    for name in prior["convergence"]:
        group = [c for c in cases if c["id"] == name]
        rates = [float(np.log2(a["rt_flux_l2_relative"]/b["rt_flux_l2_relative"]))
                 for a,b in zip(group[:-1],group[1:],strict=True)]
        fine = group[-1]
        convergence[name] = dict(orders=rates,passed=bool(
            min(rates) >= .8 and fine["rt_flux_l2_relative"] <= .05
            and fine["interface_mean_relative_error"] <= .01
            and fine["interface_rms_relative"] <= .1 and fine["rms_improvement"] >= .75))
    checks = dict(all_local_and_boundary=all(c["passed"] for c in cases),
                  all_flux_accuracy=all(c["passed"] for c in convergence.values()),
                  zero_source=patch["passed"] and patch["rt_flux_l2_relative"] <= 1e-9,
                  hot_ambient_signed=all(c["right_out_w"] < 0 for c in cases
                                         if c["id"] == "hot-ambient"))
    report = dict(passed=all(checks.values()),checks=checks,cases=cases,patch=patch,
                  convergence=convergence,evidence_level="model_simulated",source_kind="analytic",
                  scope="RT0 flux postprocessing of unchanged layered P1 temperatures",
                  prior_temperature_commit=prior["commit"],versions=prior["versions"],
                  host=dict(platform=platform.platform(),cpu_info=Path("/proc/cpuinfo").read_text(),
                            self_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                            children_peak_rss_kib=resource.getrusage(
                                resource.RUSAGE_CHILDREN).ru_maxrss),
                  commit=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip())
    (OUT / "validation.json").write_text(json.dumps(report,indent=2))
    print("p7-conservative-summary: "+json.dumps(
        {k:v for k,v in report.items() if k not in {"cases","patch","host"}}),flush=True)
    assert report["passed"], checks


if __name__ == "__main__":
    main()
