"""Actual FEMM slotless two-pole motor: field/circuit/torque extraction and mapped FOC."""
import hashlib
import json
import os
import platform
import subprocess
import time
from pathlib import Path

import femm
import numpy as np
import psutil
from p7_femm_probe import real
from p7_femm_reference import MU0, abc_from_dq, dq_from_abc

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-femm"
DEPTH_M = .04
GRIDS = [(2., .5, 4.), (1., .25, 2.), (.5, .125, 1.)]
PHASES = ("A", "B", "C")


def xy(radius, angle):
    return radius*np.cos(angle), radius*np.sin(angle)


def motor(h, gap_h, arc):
    femm.newdocument(0)
    femm.mi_probdef(0, "millimeters", "planar", 1e-10, 40, 30)
    femm.mi_smartmesh(0)
    femm.mi_addmaterial("air", 1, 1, 0, 0, 0)
    femm.mi_addmaterial("pm", 1.05, 1.05, 1.2/(MU0*1.05), 0, 0)
    femm.mi_addmaterial("copper", 1, 1, 0, 0, 58)
    femm.mi_addmaterial("stator", 1000, 1000, 0, 0, 0)
    femm.mi_addboundprop("A0", 0, 0, 0, 0, 0, 0, 0, 0, 0)
    for phase in PHASES:
        femm.mi_addcircprop(phase, 0, 1)
    for radius in (20., 22., 28., 40.):
        for k in range(6):
            femm.mi_addnode(*xy(radius, k*np.pi/3))
        for k in range(6):
            femm.mi_addarc(*xy(radius, k*np.pi/3),
                           *xy(radius, ((k+1) % 6)*np.pi/3), 60, arc)
        if radius == 40:
            for k in range(6):
                femm.mi_selectarcsegment(*xy(radius, (k+.5)*np.pi/3))
            femm.mi_setarcsegmentprop(arc, "A0", 0, 0)
            femm.mi_clearselected()
    for k in range(6):
        femm.mi_addsegment(*xy(22, k*np.pi/3), *xy(28, k*np.pi/3))
    for x, material, mesh_size, group in (
        (0., "pm", h, 1), (21., "air", gap_h, 4), (34., "stator", h, 2)):
        femm.mi_addblocklabel(x, 0)
        femm.mi_selectlabel(x, 0)
        femm.mi_setblockprop(material, 0, mesh_size, "", 0, group, 0)
        femm.mi_clearselected()
    for k, (phase, turns) in enumerate((("B", -20), ("A", 20), ("C", -20),
                                        ("B", 20), ("A", -20), ("C", 20))):
        location = xy(25, (k+.5)*np.pi/3)
        femm.mi_addblocklabel(*location)
        femm.mi_selectlabel(*location)
        femm.mi_setblockprop("copper", 0, h, phase, 0, 3, turns)
        femm.mi_clearselected()


def gap_samples(count):
    phi = np.arange(count)*2*np.pi/count
    b = np.array([femm.mo_getb(*xy(21, t)) for t in phi], dtype=float)
    br = b[:, 0]*np.cos(phi)+b[:, 1]*np.sin(phi)
    bt = -b[:, 0]*np.sin(phi)+b[:, 1]*np.cos(phi)
    torque = float(DEPTH_M*.021**2/MU0*2*np.pi*np.mean(br*bt))
    return np.column_stack([phi, b, br, bt]), torque


def solve_point(folder, angle_deg, currents, h, mst=False):
    folder.mkdir(parents=True, exist_ok=True)
    femm.mi_selectlabel(0, 0)
    femm.mi_setblockprop("pm", 0, h, "", angle_deg, 1, 0)
    femm.mi_clearselected()
    for phase, value in zip(PHASES, currents, strict=True):
        femm.mi_modifycircprop(phase, 1, float(value))
    femm.mi_saveas(str((folder / "motor.fem").resolve()))
    femm.mi_analyze(1)
    femm.mi_loadsolution()
    femm.mo_smooth("off")
    circuit = np.array([[real(v) for v in femm.mo_getcircuitproperties(p)] for p in PHASES])
    assert np.max(abs(circuit[:, 0]-currents)) <= 1e-12
    linkage = circuit[:, 2]
    dq = dq_from_abc(linkage, np.deg2rad(angle_deg))
    femm.mo_groupselectblock(1)
    torque = real(femm.mo_blockintegral(22))
    femm.mo_clearblock()
    gap, _ = gap_samples(36)
    row = dict(angle_deg=float(angle_deg), current_a=float(circuit[0, 0]),
               current_b=float(circuit[1, 0]), current_c=float(circuit[2, 0]),
               lambda_a_wb=float(linkage[0]), lambda_b_wb=float(linkage[1]),
               lambda_c_wb=float(linkage[2]), lambda_d_wb=float(dq[0]), lambda_q_wb=float(dq[1]),
               torque_weighted_nm=torque, nodes=int(femm.mo_numnodes()),
               elements=int(femm.mo_numelements()))
    if mst:
        _, raw360 = gap_samples(360)
        raw_gap, raw720 = gap_samples(720)
        np.savetxt(folder / "gap-raw-720.csv", raw_gap, delimiter=",", comments="",
                   header="phi_rad,bx_t,by_t,br_t,bt_t")
        femm.mo_smooth("on")
        _, t360 = gap_samples(360)
        fine_gap, t720 = gap_samples(720)
        femm.mo_smooth("off")
        row.update(torque_mst360_nm=t360, torque_mst720_nm=t720,
                   torque_raw_mst360_nm=raw360, torque_raw_mst720_nm=raw720)
        np.savetxt(folder / "gap-720.csv", fine_gap, delimiter=",", comments="",
                   header="phi_rad,bx_t,by_t,br_t,bt_t")
    np.savetxt(folder / "gap.csv", gap, delimiter=",", comments="",
               header="phi_rad,bx_t,by_t,br_t,bt_t")
    (folder / "result.json").write_text(json.dumps(row, indent=2))
    femm.mo_close()
    return row, gap.tolist()


def save_rows(path, rows):
    keys = list(rows[0])
    np.savetxt(path, [[r[k] for k in keys] for r in rows], delimiter=",", comments="",
               header=",".join(keys))


def phase_flux(row):
    return np.array([row["lambda_"+p+"_wb"] for p in ("a", "b", "c")])


def characterize(rows):
    theta = np.deg2rad([r["angle_deg"] for r in rows])
    lam = np.array([phase_flux(r) for r in rows])
    reference = np.cos(theta[:, None]-np.array([0., 2*np.pi/3, -2*np.pi/3]))
    psi = float(np.sum(lam*reference)/np.sum(reference**2))
    fit = np.column_stack([np.cos(theta), np.sin(theta)])
    coefficients = np.linalg.lstsq(fit, lam, rcond=None)[0]
    amplitudes = np.linalg.norm(coefficients, axis=0)
    expected_phase = np.array([0., 2*np.pi/3, -2*np.pi/3])
    phase = np.arctan2(coefficients[1], coefficients[0])
    phase_error = np.angle(np.exp(1j*(phase-expected_phase)))
    return dict(psi_wb=psi, fit_relative=float(np.linalg.norm(lam-psi*reference)
                                               /np.linalg.norm(lam)),
                phase_amplitudes_wb=amplitudes.tolist(),
                phase_error_deg=np.rad2deg(phase_error).tolist(),
                phase_amplitude_spread=float(np.ptp(amplitudes)/psi),
                common_mode_relative=float(np.max(abs(lam.sum(axis=1)))/psi))


def grid_case(index, h, gap_h, arc):
    started = time.perf_counter()
    folder = OUT / f"grid{index}"
    folder.mkdir(parents=True, exist_ok=True)
    motor(h, gap_h, arc)
    scans, snapshots = {}, []
    for count in (24, 48):
        rows = []
        for k in range(count):
            angle = k*360/count
            row, gap = solve_point(folder / f"open{count}" / f"a{k:02d}", angle,
                                   np.zeros(3), h)
            rows.append(row)
            if count == 24:
                snapshots.append(dict(mode="open", **row, gap=gap))
        scans[count] = rows
        save_rows(folder / f"open-{count}.csv", rows)
        print("p7-femm-scan: "+json.dumps(
            dict(grid=index, angles=count, extraction=characterize(rows))), flush=True)
    open_zero = phase_flux(scans[24][0])
    load_rows, loaded = [], {}
    for name, d, q in (("dplus", .5, 0.), ("dminus", -.5, 0.),
                        ("qplus", 0., .5), ("qminus", 0., -.5)):
        currents = abc_from_dq(d, q, 0.)
        row, gap = solve_point(folder / name, 0., currents, h,
                               mst=name in {"dplus", "qplus", "qminus"})
        loaded[name] = row
        snapshots.append(dict(mode=name, **row, gap=gap))
        load_rows.append(row)
    # CSV columns include all torque methods even when a point only needs flux.
    load_keys = list(loaded["qplus"])
    for row in load_rows:
        for key in load_keys:
            row.setdefault(key, float("nan"))
    save_rows(folder / "loaded.csv", [{k:r[k] for k in load_keys} for r in load_rows])
    ld = (loaded["dplus"]["lambda_d_wb"]-loaded["dminus"]["lambda_d_wb"])
    lq = (loaded["qplus"]["lambda_q_wb"]-loaded["qminus"]["lambda_q_wb"])
    matrix = np.zeros((3, 3))
    for column in range(3):
        currents = np.eye(3)[column]
        row, _ = solve_point(folder / f"phase-{column}", 0., currents, h)
        matrix[:, column] = phase_flux(row)-open_zero
    np.savetxt(folder / "phase-inductance-h.csv", matrix, delimiter=",")
    delta = .5
    pm_minus, _ = solve_point(folder / "virtual-minus", -delta, np.zeros(3), h)
    pm_plus, _ = solve_point(folder / "virtual-plus", delta, np.zeros(3), h)
    derivative = (phase_flux(pm_plus)-phase_flux(pm_minus))/(2*np.deg2rad(delta))
    extraction = characterize(scans[24])
    psi = extraction["psi_wb"]
    torque_scale = 1.5*psi*.5
    torque_checks = {}
    for name, iq in (("qplus", .5), ("qminus", -.5)):
        row = loaded[name]
        virtual = float(abc_from_dq(0., iq, 0.) @ derivative)
        row["torque_virtual_nm"] = virtual
        expected = 1.5*psi*iq
        torque_checks[name] = dict(
            weighted_nm=row["torque_weighted_nm"], expected_nm=expected, virtual_nm=virtual,
            mst360_nm=row["torque_mst360_nm"], mst720_nm=row["torque_mst720_nm"],
            raw_mst360_nm=row["torque_raw_mst360_nm"],
            raw_mst720_nm=row["torque_raw_mst720_nm"],
            raw_mst_relative=abs(row["torque_weighted_nm"]-row["torque_raw_mst720_nm"])
            /torque_scale,
            reduced_relative=abs(row["torque_weighted_nm"]-expected)/torque_scale,
            virtual_relative=abs(row["torque_weighted_nm"]-virtual)/torque_scale,
            mst_relative=abs(row["torque_weighted_nm"]-row["torque_mst720_nm"])/torque_scale,
            mst_refinement=abs(row["torque_mst360_nm"]-row["torque_mst720_nm"])/torque_scale)
    phase_asymmetry = float(np.linalg.norm(matrix-matrix.T)/np.linalg.norm(matrix))
    eigenvalues = np.linalg.eigvalsh((matrix+matrix.T)/2)
    angle_error = abs(characterize(scans[48])["psi_wb"]/psi-1)
    mapping_error = max(float(max(abs(dq_from_abc(abc_from_dq(d, q, angle), angle)
                                      -[d, q])))
                        for d, q in ((.5, 0.), (0., .5), (0., -.5))
                        for angle in (0., 1.2, 4.7))
    checks = dict(
        pm_direction=psi > 0 and scans[24][0]["lambda_d_wb"] > 0
        and abs(scans[24][0]["lambda_q_wb"])/psi <= .02,
        sinusoidal=extraction["fit_relative"] <= .02,
        balanced=extraction["common_mode_relative"] <= .02
        and extraction["phase_amplitude_spread"] <= .02,
        angle_refinement=angle_error <= .005, inductance=ld > 0 and lq > 0,
        reciprocity=phase_asymmetry <= 1e-6 and min(eigenvalues) > 0,
        peak_mapping=mapping_error <= 1e-12,
        torque=all(t["reduced_relative"] <= .05 and t["virtual_relative"] <= .05
                   and t["mst_relative"] <= .05 and t["mst_refinement"] <= .03
                   for t in torque_checks.values()),
        d_axis_torque=abs(loaded["dplus"]["torque_weighted_nm"])/torque_scale <= .02)
    checks = {key:bool(value) for key, value in checks.items()}
    result = dict(passed=bool(all(checks.values())), checks=checks, grid=index,
                  h_mm=h, gap_h_mm=gap_h, arc_deg=arc,
                  extraction=extraction, ld_h=float(ld), lq_h=float(lq),
                  angle_refinement_relative=angle_error, phase_asymmetry=phase_asymmetry,
                  phase_eigenvalues_h=eigenvalues.tolist(), peak_mapping_error_a=mapping_error,
                  torque=torque_checks, mst_field_mode="FEMM native recovered B",
                  d_axis_torque_nm=loaded["dplus"]["torque_weighted_nm"],
                  snapshots=snapshots, elapsed_s=time.perf_counter()-started)
    (folder / "validation.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    print("p7-femm-grid: "+json.dumps(
        {k:v for k, v in result.items() if k != "snapshots"}), flush=True)
    femm.mi_close()
    return result


def foc(parameters):
    from oeal.backends.motulator import CONTROL_COLUMNS, run_drive

    results = []
    for reference in (.5, -.5):
        name = "positive" if reference > 0 else "negative"
        config = dict(duration_s=.04, period_s=50e-6, step_time_s=.003, bus_v=48.,
                      pwm=False, delay=False, device_drop_v=0., iq_ref_a=reference,
                      current_limit_a=2., bandwidth_per_s=2000., thermal_feedback=False,
                      motor_parameters=parameters)
        _, controller = run_drive(config)
        a = np.array(controller.rows)
        columns = {name:i for i, name in enumerate(CONTROL_COLUMNS)}
        tail = a[a[:, 0] >= .03]
        current_error = float(np.max(abs(tail[:, columns["iq_a"]]-reference)))
        d_error = float(np.max(abs(tail[:, columns["id_a"]])))
        torque = 1.5*(parameters["flux_linkage_wb"]*a[:, columns["iq_a"]]
                     +(parameters["d_inductance_h"]-parameters["q_inductance_h"])
                     *a[:, columns["id_a"]]*a[:, columns["iq_a"]])
        torque_error = float(max(abs(torque-a[:, columns["torque_nm"]])))
        physical = controller.drive.oeal_physical_parameters
        assert physical == parameters
        assert controller.nominal.n_p == 1
        folder = OUT / "foc"
        folder.mkdir(exist_ok=True)
        np.savetxt(folder / (name+".csv"), a, delimiter=",", comments="",
                   header=",".join(CONTROL_COLUMNS))
        record = dict(id=name, reference_a=reference, rows=len(a), tail_iq_error_a=current_error,
                      tail_id_error_a=d_error, torque_formula_error_nm=torque_error,
                      passed=current_error <= .02 and d_error <= .02 and torque_error <= 1e-10)
        results.append(record)
        print("p7-femm-foc: "+json.dumps(record), flush=True)
    return results


def main():
    probe = json.loads((OUT / "probe-validation.json").read_text())
    assert probe["passed"]
    femm.openfemm(1)
    try:
        grids = [grid_case(i, *values) for i, values in enumerate(GRIDS)]
    finally:
        femm.closefemm()
    fine = grids[-1]
    parameters = dict(stator_resistance_ohm=.3, d_inductance_h=fine["ld_h"],
                      q_inductance_h=fine["lq_h"],
                      flux_linkage_wb=fine["extraction"]["psi_wb"], pole_pairs=1,
                      inertia_kg_m2=.002, viscous_friction_nms=1e-5)
    changes = {key:abs(grids[-2][key]/fine[key]-1) for key in ("ld_h", "lq_h")}
    changes["psi_wb"] = abs(grids[-2]["extraction"]["psi_wb"]
                           /fine["extraction"]["psi_wb"]-1)
    tq = fine["torque"]["qplus"]
    actual = tq["weighted_nm"]
    baseline = tq["expected_nm"]
    faults = dict(rms_peak=abs(actual-baseline/np.sqrt(2))/abs(baseline),
                  missing_three_halves=abs(actual-baseline/1.5)/abs(baseline),
                  phase_exchange=abs(actual+baseline)/abs(baseline),
                  wrong_pole_pairs=abs(actual-2*baseline)/abs(baseline))
    checks = dict(
        cylinder=probe["passed"], all_grids=all(g["passed"] for g in grids),
        mesh_refinement=max(changes.values()) <= .03,
        rejected_conventions=min(faults.values()) > .05)
    checks = {key:bool(value) for key, value in checks.items()}
    (OUT / "field-validation.json").write_text(json.dumps(
        dict(passed=bool(all(checks.values())), checks=checks, grids=grids,
             parameter_changes=changes, faults=faults), indent=2, allow_nan=False))
    assert all(checks.values()), checks
    payload = dict(parameters=parameters, source_kind="synthetic",
                   evidence_level="model_simulated", source="actual FEMM static slotless motor",
                   commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                   units="SI; peak amplitude-invariant dq; p=1",
                   fe_parameters=["d_inductance_h", "q_inductance_h", "flux_linkage_wb"],
                   assigned_parameters=["stator_resistance_ohm", "inertia_kg_m2",
                                        "viscous_friction_nms", "pole_pairs"],
                   limitations="linear slotless 2D finite boundary; no end effects or losses")
    frozen_text = json.dumps(payload, indent=2)
    path = OUT / "parameters.json"
    path.write_text(frozen_text, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    mapped = foc(parameters)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    checks["foc"] = all(c["passed"] for c in mapped)
    result = dict(passed=bool(all(checks.values())), checks=checks, grids=grids, foc=mapped,
                  parameter_changes=changes, faults=faults, parameters=payload,
                  parameter_sha256=digest, commit=payload["commit"],
                  host=dict(platform=platform.platform(), cpu=platform.processor(),
                            logical_cpus=os.cpu_count(), peak_working_set_bytes=getattr(
                                psutil.Process().memory_info(), "peak_wset", None)),
                  source_kind="synthetic", evidence_level="model_simulated",
                  scope="actual FEMM slotless static extraction to reduced motulator FOC")
    (OUT / "validation.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    print("p7-femm-summary: "+json.dumps(
        {k:v for k, v in result.items() if k not in {"grids", "host"}}), flush=True)
    assert result["passed"], checks


if __name__ == "__main__":
    main()
