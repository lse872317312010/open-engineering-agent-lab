"""First real FEMM COM and bounded permanent-magnet-cylinder probe on Windows."""
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
from pathlib import Path

import femm
import numpy as np
from p7_femm_reference import MU0, magnet_field

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-femm"


def circle(radius, arc_deg, boundary=""):
    femm.mi_addnode(radius, 0)
    femm.mi_addnode(-radius, 0)
    femm.mi_addarc(radius, 0, -radius, 0, 180, arc_deg)
    femm.mi_addarc(-radius, 0, radius, 0, 180, arc_deg)
    if boundary:
        femm.mi_selectarcsegment(0, radius)
        femm.mi_selectarcsegment(0, -radius)
        femm.mi_setarcsegmentprop(arc_deg, boundary, 0, 0)
        femm.mi_clearselected()


def real(value):
    return float(complex(value).real)


def cylinder(h_mm, arc_deg, mag_deg=0.):
    suffix = "-reverse" if mag_deg else ""
    folder = OUT / f"cylinder-h{h_mm:g}{suffix}"
    folder.mkdir(parents=True, exist_ok=True)
    femm.newdocument(0)
    femm.mi_probdef(0, "millimeters", "planar", 1e-10, 40, 30)
    femm.mi_smartmesh(0)
    femm.mi_addmaterial("air", 1, 1, 0, 0, 0)
    femm.mi_addmaterial("pm", 1, 1, 1.2/MU0, 0, 0)
    femm.mi_addboundprop("A0", 0, 0, 0, 0, 0, 0, 0, 0, 0)
    circle(20, arc_deg)
    circle(40, arc_deg, "A0")
    for x, material, direction in ((0, "pm", mag_deg), (30, "air", 0)):
        femm.mi_addblocklabel(x, 0)
        femm.mi_selectlabel(x, 0)
        femm.mi_setblockprop(material, 0, h_mm, "", direction, 1 if x == 0 else 0, 0)
        femm.mi_clearselected()
    femm.mi_saveas(str((folder / "cylinder.fem").resolve()))
    femm.mi_analyze(1)
    femm.mi_loadsolution()
    femm.mo_smooth("on")
    samples = []
    for radius in (.01, .03):
        for angle in np.arange(16)*2*np.pi/16:
            x, y = radius*np.cos(angle), radius*np.sin(angle)
            values = femm.mo_getpointvalues(x*1000, y*1000)
            target = magnet_field(x, y)
            samples.append([x, y, real(values[0]), real(values[1]), real(values[2]),
                            *[real(v) for v in target]])
    a = np.array(samples)
    a_error = float(np.linalg.norm(a[:, 2]-a[:, 5])/np.linalg.norm(a[:, 5]))
    b_error = float(np.linalg.norm(a[:, 3:5]-a[:, 6:8])/np.linalg.norm(a[:, 6:8]))
    result = dict(h_mm=h_mm, arc_deg=arc_deg, az_relative_rms=a_error, b_relative_rms=b_error,
                  nodes=int(femm.mo_numnodes()), elements=int(femm.mo_numelements()))
    np.savetxt(folder / "points.csv", a, delimiter=",", comments="",
               header="x_m,y_m,az_wb_per_m,bx_t,by_t,exact_az_wb_per_m,exact_bx_t,exact_by_t")
    (folder / "result.json").write_text(json.dumps(result, indent=2))
    femm.mo_close()
    femm.mi_close()
    print("p7-femm-cylinder: "+json.dumps(result), flush=True)
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    femm.openfemm(1)
    try:
        lua_probe = real(femm.callfemm("1+1"))
        assert lua_probe == 2
        rows = [cylinder(h, arc) for h, arc in ((2., 4.), (1., 2.), (.5, 1.))]
        direction_fault = cylinder(.5, 1., mag_deg=180.)
    finally:
        femm.closefemm()
    checks = dict(
        direction_rejected=direction_fault["b_relative_rms"] > 1,
        fine_field=rows[-1]["b_relative_rms"] <= .02,
        fine_az=rows[-1]["az_relative_rms"] <= .02,
        field_refines=all(b["b_relative_rms"] < a["b_relative_rms"]
                          for a, b in zip(rows[:-1], rows[1:], strict=True)),
        az_refines=all(b["az_relative_rms"] < a["az_relative_rms"]
                       for a, b in zip(rows[:-1], rows[1:], strict=True)))
    exepath = Path(os.environ["FEMM_EXE"])
    report = dict(passed=bool(all(checks.values())), checks=checks, cases=rows,
                  direction_fault=direction_fault, lua_expression_probe=lua_probe,
                  pyfemm=importlib.metadata.version("pyfemm"),
                  executable_sha256=hashlib.sha256(exepath.read_bytes()).hexdigest(),
                  host=platform.platform(), source_kind="synthetic",
                  evidence_level="model_simulated", reference_kind="analytic",
                  field_mode="FEMM native recovered B",
                  commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
    (OUT / "probe-validation.json").write_text(json.dumps(report, indent=2))
    print("p7-femm-probe: "+json.dumps(report), flush=True)
    assert report["passed"], checks


if __name__ == "__main__":
    main()
