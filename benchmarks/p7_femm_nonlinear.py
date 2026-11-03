"""Actual nonlinear FEMM constitutive probe, frozen dq maps and independent holdouts."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

import femm
import numpy as np
import p7_femm_motor as core
from p7_femm_nonlinear_reference import BH, interpolate, material_node
from p7_femm_probe import real
from p7_femm_reference import abc_from_dq, dq_from_abc

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-femm-nonlinear"
AXIS = [-40., -20., 0., 20., 40.]
SCALE = .026
TS = 1.5*SCALE*40
EXE_SHA = "5e83cf0899cabae2017868ddcce338e3ba4ac25d1bf8e511eac77eda2bc92a21"


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8", newline="\n")


def csv(path, rows):
    keys = list(dict.fromkeys(k for row in rows for k, v in row.items()
                             if isinstance(v, (int, float))))
    np.savetxt(path, [[r.get(k, np.nan) for k in keys] for r in rows],
               delimiter=",", comments="", header=",".join(keys))


def bh_material(name):
    femm.mi_addmaterial(name, 1, 1, 0, 0, 0)
    for b, h in BH:
        femm.mi_addbhpoint(name, float(b), float(h))


def uniform(h, target_b):
    """Independent exact constant field; H reference is at an explicit BH node."""
    folder = OUT / "material" / f"h{h:g}-b{target_b:g}"
    folder.mkdir(parents=True, exist_ok=True)
    femm.newdocument(0)
    femm.mi_probdef(0, "millimeters", "planar", 1e-10, 40, 30)
    femm.mi_smartmesh(0)
    bh_material("synthetic")
    corners = [(-5, -5), (5, -5), (5, 5), (-5, 5)]
    for x, y in corners:
        femm.mi_addnode(x, y)
    for a, b in zip(corners, corners[1:]+corners[:1], strict=True):
        femm.mi_addsegment(*a, *b)
    for y, name in ((-5, "bottom"), (5, "top")):
        femm.mi_addboundprop(name, target_b*y*.001, 0, 0, 0, 0, 0, 0, 0, 0)
        femm.mi_selectsegment(0, y)
        femm.mi_setsegmentprop(name, 0, 1, 0, 0)
        femm.mi_clearselected()
    femm.mi_addblocklabel(0, 0)
    femm.mi_selectlabel(0, 0)
    femm.mi_setblockprop("synthetic", 0, h, "", 0, 1, 0)
    femm.mi_clearselected()
    femm.mi_saveas(str((folder / "uniform.fem").resolve()))
    femm.mi_analyze(1)
    femm.mi_loadsolution()
    femm.mo_smooth("off")
    points = []
    for x in (-3, 0, 3):
        for y in (-3, 0, 3):
            v = femm.mo_getpointvalues(x, y)
            points.append([x*.001, y*.001, real(v[1]), real(v[2]),
                           real(v[5]), real(v[6])])
    a = np.array(points)
    b_error = float(np.max(np.linalg.norm(a[:, 2:4]-[target_b, 0], axis=1))/abs(target_b))
    href = material_node(target_b)
    h_error = float(np.max(np.linalg.norm(a[:, 4:6]-[href, 0], axis=1))/abs(href))
    result = dict(h_mm=h, target_b_t=target_b, target_h_am=href,
                  b_relative=b_error, h_relative=h_error,
                  positive_direction_error=float(np.max(np.linalg.norm(
                      a[:, 2:4]-[abs(target_b), 0], axis=1))/abs(target_b)),
                  passed=b_error <= .005 and h_error <= .01)
    np.savetxt(folder / "points.csv", a, delimiter=",", comments="",
               header="x_m,y_m,bx_t,by_t,hx_am,hy_am")
    write(folder / "validation.json", result)
    femm.mo_close()
    femm.mi_close()
    print("p7-nonlinear-material: "+json.dumps(result), flush=True)
    return result


def motor(grid, nonlinear=True):
    core.motor(*grid)
    if nonlinear:
        femm.mi_modifymaterial("stator", 1, 1)
        femm.mi_modifymaterial("stator", 2, 1)
        for b, h in BH:
            femm.mi_addbhpoint("stator", float(b), float(h))


def point(folder, d, q, h, angle=0., mst=False):
    folder.mkdir(parents=True, exist_ok=True)
    theta = np.deg2rad(angle)
    currents = abc_from_dq(d, q, theta)
    femm.mi_selectlabel(0, 0)
    femm.mi_setblockprop("pm", 0, h, "", angle, 1, 0)
    femm.mi_clearselected()
    for phase, current in zip(core.PHASES, currents, strict=True):
        femm.mi_modifycircprop(phase, 1, float(current))
    femm.mi_saveas(str((folder / "motor.fem").resolve()))
    femm.mi_analyze(1)
    femm.mi_loadsolution()
    circuit = np.array([[real(v) for v in femm.mo_getcircuitproperties(p)]
                        for p in core.PHASES])
    assert np.max(abs(circuit[:, 0]-currents)) <= 1e-10
    lam = circuit[:, 2]
    dq = dq_from_abc(lam, theta)
    femm.mo_groupselectblock(1)
    torque = real(femm.mo_blockintegral(22))
    femm.mo_clearblock()
    gap, _ = core.gap_samples(36)
    femm.mo_smooth("on")
    stator = []
    for phi in np.arange(12)*2*np.pi/12:
        x, y = core.xy(34, phi)
        v = femm.mo_getpointvalues(x, y)
        stator.append([float(phi), real(v[1]), real(v[2]), real(v[5]), real(v[6])])
    row = dict(id_a=float(d), iq_a=float(q), angle_deg=float(angle),
               current_a=float(circuit[0, 0]), current_b=float(circuit[1, 0]),
               current_c=float(circuit[2, 0]), lambda_a_wb=float(lam[0]),
               lambda_b_wb=float(lam[1]), lambda_c_wb=float(lam[2]),
               lambda_d_wb=float(dq[0]), lambda_q_wb=float(dq[1]),
               torque_nm=torque, dq_torque_nm=float(1.5*(dq[0]*q-dq[1]*d)),
               nodes=int(femm.mo_numnodes()), elements=int(femm.mo_numelements()),
               gap=gap.tolist(), stator=stator)
    if mst:
        for mode in ("off", "on"):
            _, t360 = core.gap_samples(360, field_mode=mode)
            fine_gap, t720 = core.gap_samples(720, field_mode=mode)
            row["mst360_"+mode] = t360
            row["mst720_"+mode] = t720
            np.savetxt(folder / ("gap720-"+mode+".csv"), fine_gap, delimiter=",",
                       comments="", header="phi_rad,bx_t,by_t,br_t,bt_t")
    write(folder / "result.json", row)
    femm.mo_close()
    print("p7-nonlinear-point: "+json.dumps({k:v for k, v in row.items()
                                          if k not in {"gap", "stator"}}), flush=True)
    return row


def flux(row):
    return np.array([row["lambda_d_wb"], row["lambda_q_wb"]])


def grid_case(index, grid):
    folder = OUT / f"grid{index}"
    folder.mkdir(parents=True, exist_ok=True)
    motor(grid)
    training = []
    for i, d in enumerate(AXIS):
        for j, q in enumerate(AXIS):
            training.append(point(folder / f"train-{i}-{j}", d, q, grid[0],
                                  mst=index == 1 and d == 0 and abs(q) == 40))
    values = np.array([flux(r) for r in training]).reshape(5, 5, 2)
    frozen = dict(axis_a=AXIS, flux_wb=values.tolist(), training_points=25,
                  commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                  evidence_level="model_simulated", source_kind="synthetic",
                  interpolation="bounded bilinear; no extrapolation", bh_table_si=BH.tolist())
    map_path = folder / "flux-map.json"
    write(map_path, frozen)
    digest = hashlib.sha256(map_path.read_bytes()).hexdigest()
    csv(folder / "training.csv", training)
    # Training artifact is immutable before any holdout result exists.
    holdouts = []
    for k, (d, q) in enumerate(((-10, -10), (-10, 30), (30, -10), (30, 30))):
        row = point(folder / f"holdout-{k}", d, q, grid[0])
        prediction = interpolate(AXIS, values, d, q)
        row.update(predicted_d_wb=float(prediction[0]), predicted_q_wb=float(prediction[1]),
                   prediction_error=float(np.linalg.norm(flux(row)-prediction)/SCALE))
        holdouts.append(row)
    assert hashlib.sha256(map_path.read_bytes()).hexdigest() == digest
    csv(folder / "holdouts.csv", holdouts)
    increments, matrices = [], []
    for step in (1., .5):
        rows = [point(folder / f"increment-{step:g}-{k}", d, q, grid[0])
                for k, (d, q) in enumerate(((step, 0), (-step, 0), (0, step), (0, -step)))]
        increments.extend(rows)
        matrix = np.column_stack([(flux(rows[0])-flux(rows[1]))/(2*step),
                                  (flux(rows[2])-flux(rows[3]))/(2*step)])
        matrices.append(matrix)
    csv(folder / "increments.csv", increments)
    asymmetry = max(float(np.linalg.norm(m-m.T)/np.linalg.norm(m)) for m in matrices)
    min_eig = min(float(np.min(np.linalg.eigvalsh((m+m.T)/2))) for m in matrices)
    increment_refines = float(np.linalg.norm(matrices[0]-matrices[1])/np.linalg.norm(matrices[1]))
    all_points = training+holdouts+increments
    torque_error = max(abs(r["torque_nm"]-r["dq_torque_nm"])/TS for r in all_points)
    checks = dict(holdout=max(r["prediction_error"] for r in holdouts) <= .02,
                  reciprocity=asymmetry <= .02, incremental_spd=min_eig > 0,
                  increment_refinement=increment_refines <= .02, dq_torque=torque_error <= .05)
    mst_rows = [r for r in training if "mst720_on" in r]
    if mst_rows:
        checks["mst"] = all(abs(r["mst720_on"]-r["torque_nm"])/TS <= .05
                            and abs(r["mst720_on"]-r["mst360_on"])/TS <= .03 for r in mst_rows)
    angles = []
    paired = []
    if index == 1:
        for angle in (30., 60., 90.):
            angles.append(point(folder / f"angle-{angle:g}", 0, 40, grid[0], angle=angle))
        origin = next(r for r in training if r["id_a"] == 0 and r["iq_a"] == 40)
        checks["angle_equivalence"] = all(np.linalg.norm(flux(r)-flux(origin))/SCALE <= .02
                                         and abs(r["torque_nm"]-origin["torque_nm"])/TS <= .05
                                         for r in angles)
        csv(folder / "angles.csv", angles)
        femm.mi_close()
        motor(grid, nonlinear=False)
        for k, (d, q) in enumerate(((0, 0), (-40, -40), (-40, 40), (40, -40), (40, 40))):
            paired.append(point(folder / f"linear-{k}", d, q, grid[0]))
        csv(folder / "linear.csv", paired)
        differences = [float(np.linalg.norm(flux(r)-flux(next(
            t for t in training if t["id_a"] == r["id_a"] and t["iq_a"] == r["iq_a"])))/SCALE)
                       for r in paired]
        checks["observed_nonlinearity"] = max(differences) > .001
    else:
        differences = []
    femm.mi_close()
    checks = {k:bool(v) for k, v in checks.items()}
    result = dict(grid=index, mesh=dict(h_mm=grid[0], gap_h_mm=grid[1], arc_deg=grid[2]),
                  passed=all(checks.values()), checks=checks, map_sha256=digest,
                  training=training, holdouts=holdouts, increments=increments,
                  incremental_matrices_h=[m.tolist() for m in matrices],
                  reciprocity_relative=asymmetry, min_incremental_eigenvalue_h=min_eig,
                  incremental_refinement_relative=increment_refines,
                  torque_error_relative=torque_error, angles=angles, linear=paired,
                  linear_difference_relative=differences)
    write(folder / "validation.json", result)
    print("p7-nonlinear-grid: "+json.dumps({k:v for k, v in result.items()
          if k not in {"training", "holdouts", "increments", "angles", "linear"}}), flush=True)
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    core.OUT = OUT
    assert hashlib.sha256(Path(os.environ["FEMM_EXE"]).read_bytes()).hexdigest() == EXE_SHA
    np.savetxt(OUT / "bh.csv", BH, delimiter=",", comments="", header="b_t,h_am")
    femm.openfemm(1)
    try:
        materials = [uniform(h, b) for h in (2., 1., .5) for b in (1., 1.5, 2.)]
        reverse = uniform(.5, -1.5)
        write(OUT / "material-validation.json", dict(
            passed=all(r["passed"] for r in materials+[reverse]),
            cases=materials, reverse=reverse,
            positive_reference_rejected=reverse["positive_direction_error"] > 1))
        assert all(r["passed"] for r in materials+[reverse])
        assert reverse["positive_direction_error"] > 1
        grids = [grid_case(i, grid) for i, grid in enumerate(core.GRIDS[1:])]
    finally:
        femm.closefemm()
    mesh_flux = max(float(np.linalg.norm(flux(a)-flux(b))/SCALE)
                    for a, b in zip(grids[0]["training"], grids[1]["training"], strict=True))
    mesh_torque = max(abs(a["torque_nm"]-b["torque_nm"])/TS
                      for a, b in zip(grids[0]["training"], grids[1]["training"], strict=True))
    checks = dict(material=True, grids=all(g["passed"] for g in grids),
                  mesh_flux=mesh_flux <= .03, mesh_torque=mesh_torque <= .05)
    result = dict(passed=bool(all(checks.values())), checks=checks, materials=materials,
                  reverse=reverse, grids=grids, mesh_flux_relative=mesh_flux,
                  mesh_torque_relative=mesh_torque, bh_table_si=BH.tolist(),
                  flux_scale_wb=SCALE, torque_scale_nm=TS,
                  source_kind="synthetic", evidence_level="model_simulated",
                  commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                  executable_sha256=EXE_SHA,
                  limitations="slotless static synthetic BH; no losses or dynamic nonlinear FOC")
    write(OUT / "validation.json", result)
    print("p7-nonlinear-summary: "+json.dumps({k:v for k, v in result.items()
          if k not in {"grids", "materials", "bh_table_si"}}), flush=True)
    assert result["passed"], checks


if __name__ == "__main__":
    main()
