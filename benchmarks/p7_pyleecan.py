"""Actual unmodified PYLEECAN/SWAT/SciDataTool slotted machine and FEMM integration."""
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from p7_pyleecan_reference import physical_depth, polygon_area, reference

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-pyleecan"
ASSET = ROOT / "benchmarks/assets/pyleecan-spmsm001.json"
SOURCES = {
    "pyleecan": "8654bd49fc005fdb19a38b1e39cd5d06198cdac1",
    "scidatatool": "c6f2497971a24486c64ad27575eb45f12a8458bf",
    "swat-em": "4d3b4d7093ba127b5bfbf4c6f2a038d87ba79d7e",
}
EXE_SHA = "5e83cf0899cabae2017868ddcce338e3ba4ac25d1bf8e511eac77eda2bc92a21"
GRIDS = [1., 1.5, 2.]


def encode(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, complex):
        return dict(real=value.real, imag=value.imag)
    raise TypeError(type(value).__name__)


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, default=encode, indent=2, allow_nan=False),
                    encoding="utf-8", newline="\n")


def activate():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, sha in SOURCES.items():
        folder = ROOT / "outputs/vendor" / name
        actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=folder,
                                         text=True).strip()
        assert actual == sha, (name, actual)
        sys.path.insert(0, str(folder))
        shutil.copyfile(folder / "LICENSE", OUT / (name+"-LICENSE.txt"))
    original = ROOT / "outputs/vendor/pyleecan/pyleecan/Data/Machine/SPMSM_001.json"
    assert ASSET.read_bytes() == original.read_bytes()
    from pyleecan.Functions.load import load

    return load(str(ASSET))


def points(surface, count=64):
    a = np.asarray(surface.discretize(Npoint=count), dtype=complex)
    return np.column_stack([a.real, a.imag])


def geometry():
    machine = activate()
    raw = json.loads(ASSET.read_text())
    target = reference(raw)
    winding = machine.stator.winding.get_connection_mat()
    nz = np.argwhere(winding != 0)
    turns = np.sum(np.abs(winding), axis=(0, 1, 2))
    signed = np.sum(winding, axis=(0, 1, 2))
    checks = dict(winding_count=len(nz) == 24,
                  winding_turns=bool(np.all(np.abs(winding[winding != 0]) == 34)),
                  phase_balance=bool(np.all(signed == 0) and np.all(turns == 272)),
                  slot_area=abs(machine.stator.slot.comp_surface_active()/target["slot_m2"]-1)
                  <= 1e-10,
                  magnet_area=abs(machine.rotor.slot.comp_surface_active()/target["magnet_m2"]-1)
                  <= 1e-10,
                  gap=abs(machine.comp_width_airgap_mec()-target["gap_m"]) <= 1e-12)
    slot = machine.stator.slot.get_surface_active()
    polygon_error = abs(polygon_area(points(slot, 96))/target["slot_m2"]-1)
    checks["polygon"] = polygon_error <= .001
    surfaces = []
    for lam in (machine.stator, machine.rotor):
        for surface in lam.build_geometry(sym=1):
            label = surface.label
            record = dict(label=label, points=points(surface).tolist(),
                          rotor=not lam.is_stator)
            if "Wind" in label:
                match = re.search(r"_R(\d+)-T(\d+)-S(\d+)", label)
                assert match, label
                rad, tan, si = map(int, match.groups())
                vector = winding[rad, tan, si]
                assert np.count_nonzero(vector) == 1
                phase = int(np.flatnonzero(vector)[0])
                record.update(phase=phase, turns=float(vector[phase]), slot=si)
            surfaces.append(record)
    checks["surfaces"] = sum("phase" in s for s in surfaces) == 24
    rows = np.array([[*idx, winding[tuple(idx)]] for idx in nz])
    np.savetxt(OUT / "winding.csv", rows, delimiter=",", comments="",
               header="radial_layer,tangential_layer,slot,phase,turns")
    np.savetxt(OUT / "bh.csv", raw["stator"]["mat_type"]["mag"]["BH_curve"]["value"],
               delimiter=",", comments="", header="h_am,b_t")
    checks = {k:bool(v) for k, v in checks.items()}
    data = dict(passed=all(checks.values()), checks=checks, reference=target,
                winding_shape=list(winding.shape), absolute_turns_per_phase=turns.tolist(),
                signed_turns_per_phase=signed.tolist(), surfaces=surfaces,
                polygon_error=polygon_error, sources=SOURCES,
                asset_sha256=hashlib.sha256(ASSET.read_bytes()).hexdigest(),
                bh_source="upstream M400-50A reference table; measurement provenance not verified",
                bh=raw["stator"]["mat_type"]["mag"]["BH_curve"]["value"])
    write(OUT / "geometry.json", data)
    print("p7-pyleecan-geometry: "+json.dumps(
        {k:v for k, v in data.items() if k not in {"surfaces", "bh"}}, default=encode), flush=True)
    assert data["passed"], checks
    return data


def selected_area(handler, groups):
    handler.mo_clearblock()
    for group in groups:
        handler.mo_groupselectblock(int(group))
    area = float(handler.mo_blockintegral(5))
    handler.mo_clearblock()
    return area


def solve(name, grid, sign=0., angle=0., length=.05):
    from pyleecan.Classes.ImportMatrixVal import ImportMatrixVal
    from pyleecan.Classes.InputCurrent import InputCurrent
    from pyleecan.Classes.MagFEMM import MagFEMM
    from pyleecan.Classes.OPdq import OPdq
    from pyleecan.Classes.Simu1 import Simu1

    machine = activate()
    machine.stator.L1 = length
    machine.rotor.L1 = length
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    currents = np.array([0., sign*math.sqrt(3)*2.5, -sign*math.sqrt(3)*2.5])
    sim = Simu1(name=name, machine=machine, path_result=str(folder))
    sim.input = InputCurrent(Is=ImportMatrixVal(value=currents[None, :]), Ir=None,
                             OP=OPdq(N0=60), Nt_tot=1, Na_tot=96,
                             angle_rotor_initial=math.radians(angle))
    sim.mag = MagFEMM(type_BH_stator=0, type_BH_rotor=0, is_periodicity_a=False,
                      is_periodicity_t=False, is_get_meshsolution=False,
                      Kgeo_fineness=grid, Kmesh_fineness=grid, nb_worker=1,
                      is_close_femm=False, is_set_previous=False, is_sliding_band=True,
                      is_fast_draw=False)
    sim.force = None
    sim.struct = None
    print("p7-pyleecan-start: "+json.dumps(dict(case=name, grid=grid, angle_deg=angle,
                                               length_m=length, currents_a=currents.tolist())),
          flush=True)
    output = sim.run()
    handler = output.mag.internal.handler_list[0]
    try:
        details = output.mag.internal.FEMM_dict
        info = handler.mo_getprobleminfo()
        native_depth = float(info[2])
        assert float(info[1]) == 0 and abs(native_depth-1.) <= 1e-12
        circuit = np.array([handler.mo_getcircuitproperties("Circs"+str(i)) for i in range(3)])
        circuit = np.real(circuit).astype(float)
        assert np.max(abs(circuit[:, 0]-currents)) <= 1e-10
        rotor_groups = details["groups"]["lam_group_list"][machine.rotor.get_label()]
        handler.mo_clearblock()
        for group in rotor_groups:
            handler.mo_groupselectblock(int(group))
        raw_torque = float(np.real(handler.mo_blockintegral(22)))
        handler.mo_clearblock()
        gap_torque_raw = float(np.real(handler.mo_gapintegral("bc_ag2", 0)))
        flux = physical_depth(circuit[:, 2], length, native_depth)
        torque = float(physical_depth(raw_torque, length, native_depth))
        gap_torque = float(physical_depth(gap_torque_raw, length, native_depth))
        library_flux = np.asarray(output.mag.Phi_wind_stator.values, dtype=float).reshape(-1)
        library_torque = float(output.mag.Tem_av)
        assert library_flux.size == 3
        phi_error = float(np.linalg.norm(flux-library_flux)/.05)
        torque_error = abs(torque-library_torque)
        phi = np.arange(96)*2*np.pi/96
        field = np.array([handler.mo_getgapb("bc_ag2", float(a*180/np.pi)) for a in phi],
                         dtype=float)
        areas = dict(winding_m2=selected_area(handler, [details["groups"]["GROUP_SW"]]),
                     magnets_m2=selected_area(handler, details["groups"]["GROUP_RM"]),
                     stator_core_m2=selected_area(handler, [details["groups"]["GROUP_SC"]]),
                     rotor_core_m2=selected_area(handler, [details["groups"]["GROUP_RC"]]))
        target = reference(json.loads(ASSET.read_text()))
        area_error = max(abs(v/target[k]-1) for k, v in areas.items())
        nodes, elements = int(handler.mo_numnodes()), int(handler.mo_numelements())
        fempath = Path(details["path_save"])
        anspath = fempath.with_suffix(".ans")
        assert fempath.is_file() and anspath.is_file()
        native_files = {str(p.relative_to(OUT)).replace("\\", "/"):
                        hashlib.sha256(p.read_bytes()).hexdigest() for p in (fempath, anspath)}
        checks = dict(circuit=True, depth_mapping=phi_error <= 1e-8 and torque_error <= 1e-8,
                      native_area=area_error <= .005, mst=abs(torque-gap_torque) <= .05,
                      finite=bool(np.all(np.isfinite([*flux, torque, gap_torque]))))
        result = dict(case=name, grid=grid, sign=sign, angle_deg=angle,
                      length_m=length, native_depth_m=native_depth, currents_a=currents.tolist(),
                      flux_wb=flux.tolist(), native_flux_wb=circuit[:, 2].tolist(),
                      torque_nm=torque, gap_torque_nm=gap_torque,
                      native_torque_nm=raw_torque, library_flux_wb=library_flux.tolist(),
                      library_torque_nm=library_torque, phi_unit_error=phi_error,
                      torque_unit_error_nm=torque_error, native_areas_m2=areas,
                      max_area_relative=area_error, nodes=nodes, elements=elements,
                      field=field.tolist(), phi_rad=phi.tolist(), native_files=native_files,
                      passed=all(checks.values()), checks=checks,
                      actual_angle_rad=float(np.asarray(output.get_angle_rotor()).reshape(-1)[0]))
        write(folder / "result.json", result)
        write(folder / "femm-dict.json", details)
        np.savetxt(folder / "gap.csv", np.column_stack([phi, field]), delimiter=",", comments="",
                   header="phi_rad,br_t,bt_t")
    finally:
        handler.mo_close()
        handler.mi_close()
        handler.closefemm()
    print("p7-pyleecan-case: "+json.dumps(
        {k:v for k, v in result.items() if k not in {"field", "phi_rad"}},
        default=encode), flush=True)
    return result


def main():
    assert hashlib.sha256(Path(os.environ["FEMM_EXE"]).read_bytes()).hexdigest() == EXE_SHA
    geometry_data = geometry()
    if len(sys.argv) > 1 and sys.argv[1] == "geometry":
        return
    results = []
    for i, grid in enumerate(GRIDS):
        for label, sign in (("open", 0.), ("positive", 1.), ("negative", -1.)):
            results.append(solve(f"grid{i}-{label}", grid, sign))
    for angle in (45., 90.):
        results.append(solve("fine-open-"+str(int(angle)), 2., angle=angle))
    results.append(solve("fine-double-stack", 2., length=.1))
    medium, fine = results[3:6], results[6:9]
    flux_change = max(float(np.linalg.norm(np.array(a["flux_wb"])-b["flux_wb"])/.05)
                      for a, b in zip(medium, fine, strict=True))
    torque_change = max(abs(a["torque_nm"]-b["torque_nm"])
                        for a, b in zip(medium, fine, strict=True))
    base, reverse, repeat, doubled = results[6], results[9], results[10], results[11]
    reversal = float(np.linalg.norm(np.array(base["flux_wb"])+reverse["flux_wb"])/.05)
    periodic = float(np.linalg.norm(np.array(base["flux_wb"])-repeat["flux_wb"])/.05)
    double_phi = float(np.linalg.norm(np.array(doubled["flux_wb"])
                                     -2*np.array(base["flux_wb"]))/.05)
    double_t = abs(doubled["torque_nm"]-2*base["torque_nm"])
    field_delta = float(np.linalg.norm(np.array(doubled["field"])-base["field"])
                        /np.linalg.norm(base["field"]))
    mesh_nodes = [results[3*i]["nodes"] for i in range(3)]
    checks = dict(geometry=geometry_data["passed"], cases=all(r["passed"] for r in results),
                  mesh_nodes=all(a < b for a, b in zip(
                      mesh_nodes[:-1], mesh_nodes[1:], strict=True)),
                  mesh_flux=flux_change <= .03, mesh_torque=torque_change <= .05,
                  open_nonzero=np.linalg.norm(base["flux_wb"]) > 1e-6,
                  half_period=reversal <= .02, full_period=periodic <= .02,
                  axial_scaling=double_phi <= 1e-6 and double_t <= 1e-6 and field_delta <= 1e-6)
    checks = {k:bool(v) for k, v in checks.items()}
    report = dict(passed=all(checks.values()), checks=checks, cases=results,
                  mesh_flux_relative=flux_change, mesh_torque_change_nm=torque_change,
                  reversal_relative=reversal, periodic_relative=periodic,
                  double_flux_relative=double_phi, double_torque_error_nm=double_t,
                  double_field_relative=field_delta, sources=SOURCES,
                  source_kind="open_dataset", evidence_level="model_simulated",
                  commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                  limits="reference 2D; unverified material provenance; no losses/dynamic FOC")
    write(OUT / "validation.json", report)
    print("p7-pyleecan-summary: "+json.dumps(
        {k:v for k, v in report.items() if k != "cases"}, default=encode), flush=True)
    assert report["passed"], checks


def archive():
    OUT.mkdir(parents=True, exist_ok=True)
    data = dict(source_commit=subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True).strip(), platform=platform.platform(),
        cpu=platform.processor(), python=sys.version,
        packages={p:importlib.metadata.version(p) for p in
                  ("numpy", "scipy", "matplotlib", "pyfemm", "pywin32", "PySide6")},
        executable_sha256=hashlib.sha256(Path(os.environ["FEMM_EXE"]).read_bytes()).hexdigest())
    write(OUT / "environment.json", data)
    (OUT / "environment.txt").write_text(
        subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True))
    for path in Path(os.environ["FEMM_EXE"]).parents[1].rglob("*"):
        if path.is_file() and any(s in path.name.lower()
                                  for s in ("license", "licence", "copyright")):
            dst = OUT / "installed-licenses" / path.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dst)
    manifest = {p.relative_to(OUT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                for p in OUT.rglob("*") if p.is_file() and p.name != "manifest.json"}
    write(OUT / "manifest.json", manifest)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "archive":
        archive()
    else:
        main()
