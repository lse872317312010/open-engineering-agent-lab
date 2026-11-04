"""Loaded-current extension of the frozen native solve; original producer remains intact."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from p7_pyleecan import (
    ANGLE_ORIGIN,
    ASSET,
    OUT,
    activate,
    encode,
    physical_depth,
    reference,
    selected_area,
    write,
)


def solve(name, grid, sign=0., angle=0., length=.05, currents_abc=None):
    machine = activate()
    from pyleecan.Classes.ImportMatrixVal import ImportMatrixVal
    from pyleecan.Classes.InputCurrent import InputCurrent
    from pyleecan.Classes.MagFEMM import MagFEMM
    from pyleecan.Classes.OPdq import OPdq
    from pyleecan.Classes.Simu1 import Simu1

    machine.stator.L1 = length
    machine.rotor.L1 = length
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    currents = np.asarray(currents_abc, dtype=float)
    assert currents.shape == (3,) and np.isfinite(currents).all()
    sim = Simu1(name=name, machine=machine, path_result=str(folder))
    sim.input = InputCurrent(Is=ImportMatrixVal(value=currents[None, :]), Ir=None,
                             OP=OPdq(N0=60), Nt_tot=1, Na_tot=96,
                             angle_rotor_initial=ANGLE_ORIGIN+math.radians(angle))
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
        actual_angle = float(np.asarray(output.get_angle_rotor()).reshape(-1)[0])
        expected_angle = ANGLE_ORIGIN+math.radians(angle)
        frame_error = abs(math.atan2(math.sin(actual_angle-expected_angle),
                                    math.cos(actual_angle-expected_angle)))
        checks = dict(frame=frame_error <= 1e-12, circuit=True,
                      depth_mapping=phi_error <= 1e-8 and torque_error <= 1e-8,
                      native_area=area_error <= .005, mst=abs(torque-gap_torque) <= .05,
                      finite=bool(np.all(np.isfinite([*flux, torque, gap_torque]))))
        result = dict(case=name, grid=grid, sign=sign, angle_deg=angle,
                      length_m=length, native_depth_m=native_depth, currents_a=currents.tolist(),
                      native_currents_a=circuit[:, 0].tolist(),
                      flux_wb=flux.tolist(), native_flux_wb=circuit[:, 2].tolist(),
                      torque_nm=torque, gap_torque_nm=gap_torque,
                      native_torque_nm=raw_torque, library_flux_wb=library_flux.tolist(),
                      library_torque_nm=library_torque, phi_unit_error=phi_error,
                      torque_unit_error_nm=torque_error, native_areas_m2=areas,
                      max_area_relative=area_error, nodes=nodes, elements=elements,
                      field=field.tolist(), phi_rad=phi.tolist(), native_files=native_files,
                      passed=all(checks.values()), checks=checks,
                      actual_angle_rad=actual_angle, expected_angle_rad=expected_angle,
                      angle_origin_rad=ANGLE_ORIGIN, frame_error_rad=frame_error)
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

