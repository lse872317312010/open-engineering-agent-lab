"""One-coarse-field diagnostic: API source, smoothing and native batched quadrature."""
import inspect
import json
from pathlib import Path

import femm
import numpy as np
from p7_femm_motor import DEPTH_M, gap_samples, motor, solve_point
from p7_femm_reference import abc_from_dq, maxwell_torque

OUT = Path(__file__).resolve().parents[1] / "outputs/p7-femm/stress-probe"


def batch(count, radius):
    # ActiveX accepts expressions; dofile executes a trusted numeric Lua chunk.
    phi = np.arange(count)*2*np.pi/count
    xs, ys = radius*1000*np.cos(phi), radius*1000*np.sin(phi)
    script = 'xs={'+','.join(femm.num(v) for v in xs)+'};'
    script += 'ys={'+','.join(femm.num(v) for v in ys)+'};'
    script += ('s="" for k=1,'+str(count)+' do '
               'local a,bx,by=mo_getpointvalues(xs[k],ys[k]) '
               's=s..format("%.17g,%.17g,",bx,by) end return s')
    script_path = OUT / "batch-query.lua"
    script_path.write_text(script, encoding="ascii", newline="\n")
    command = "dofile("+femm.quote(script_path.as_posix())+")"
    response = femm.HandleToFEMM.call2femm(command)
    if response.startswith("error"):
        raise RuntimeError(response)
    values = np.fromstring(response.strip().rstrip(","), sep=",").reshape(count, 2)
    assert np.all(np.isfinite(values))
    return values, maxwell_torque(phi, values[:, 0], values[:, 1], radius, DEPTH_M)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("mo_getb", "mo_getpointvalues", "mo_smooth", "callfemm"):
        print("femm-api-source: "+name+"\n"+inspect.getsource(getattr(femm, name)), flush=True)
    femm.openfemm(1)
    try:
        motor(2., .5, 4.)
        row, _ = solve_point(OUT / "qplus", 0., abc_from_dq(0., .5, 0.), 2.)
        femm.opendocument(str((OUT / "qplus/motor.ans").resolve()))
        result = dict(weighted_nm=row["torque_weighted_nm"], modes={})
        for mode in ("off", "on", "on-reload"):
            femm.mo_smooth("off" if mode == "off" else "on")
            if mode == "on-reload":
                femm.mo_reload()
            direct, torque = gap_samples(360, field_mode="off" if mode == "off" else "on")
            actual, batch_torque = batch(360, .021)
            error = float(np.max(abs(actual-direct[:, 1:3])))
            result["modes"][mode] = dict(single_nm=torque, batch_nm=batch_torque,
                                        batch_error_t=error)
            print("femm-batch: "+json.dumps(result["modes"][mode]), flush=True)
            assert error <= 1e-12
        femm.mo_smooth("on")
        result["radial"] = []
        for count in (720, 1440, 2880, 5760):
            nodes, weights = np.polynomial.legendre.leggauss(32)
            torques = [batch(count, .021+.0008*z)[1] for z in nodes]
            value = float(np.dot(weights, torques)/2)
            record = dict(angular=count, radial=32, torque_nm=value,
                          weighted_relative=abs(value-row["torque_weighted_nm"])
                          /abs(row["torque_weighted_nm"]))
            result["radial"].append(record)
            print("femm-radial-diagnostic: "+json.dumps(record), flush=True)
        result["radial_orders"] = []
        for radial_count in (6, 12, 32, 64):
            femm.mo_smooth("on")
            nodes, weights = np.polynomial.legendre.leggauss(radial_count)
            torques = [batch(2880, .021+.0008*z)[1] for z in nodes]
            value = float(np.dot(weights, torques)/2)
            record = dict(angular=2880, radial=radial_count, torque_nm=value,
                          weighted_relative=abs(value-row["torque_weighted_nm"])
                          /abs(row["torque_weighted_nm"]))
            result["radial_orders"].append(record)
            print("femm-radial-order-diagnostic: "+json.dumps(record), flush=True)
        (OUT / "diagnostic.json").write_text(json.dumps(result, indent=2))
        femm.mo_close()
        femm.mi_close()
    finally:
        femm.closefemm()


if __name__ == "__main__":
    main()
