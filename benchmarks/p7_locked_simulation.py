"""Use existing PI/SVPWM with frozen full-L locked-rotor plant and exact replay."""
import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path

import numpy as np
from p7_local_flux_model import LocalFluxModel
from p7_locked_reference import advance
from scipy.linalg import expm

from oeal.current_control import CurrentPIParameters, CurrentPIState, current_control_step
from oeal.foc import average_svpwm
from oeal.transforms import inverse_park, park

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-locked-report"
MODEL_SHA = "dc8c5ca77d55c7fe876d7c18da1ad897896c9e0289b5d940417984fec1a6068e"
DT = 50e-6
R = .3
ANGLE = -3.069879826333843e-5


def simulate(model, vdc, microstep):
    matrix = model.inductance
    inverse = np.linalg.inv(matrix)
    p = CurrentPIParameters(matrix[0, 0]*1000, R*1000, matrix[1, 1]*1000,
                            R*1000, vdc/math.sqrt(3), 1., 1000.)
    pi = CurrentPIState()
    x = np.zeros(4)
    exact = np.zeros(2)
    propagator = expm(-R*inverse*DT)
    history = []
    max_exact, max_balance, max_domain = 0., 0., 0.
    limited = 0
    for tick in range(800):
        reference = 0. if tick < 20 else .5 if tick < 400 else -.5
        command = current_control_step(
            p, pi, reference_d_a=0., reference_q_a=reference,
            measured_d_a=float(x[0]), measured_q_a=float(x[1]), period_s=DT)
        pi = command.next_state
        alpha, beta = inverse_park(command.vd_v, command.vq_v, ANGLE)
        alpha, beta, duties = average_svpwm(alpha, beta, vdc)
        voltage = np.array(park(alpha, beta, ANGLE))
        limited += int(command.voltage_limited)
        flux = model.flux(x[:2])
        magnetic = float(.75*x[:2]@matrix@x[:2])
        balance = float(x[2]-x[3]-magnetic)
        torque = float(6*(flux[0]*x[1]-flux[1]*x[0]))
        history.append([tick*DT, *x[:2], reference, *voltage, *flux, torque,
                        x[2], x[3], magnetic, balance, int(command.voltage_limited), *duties])
        for _ in range(round(DT/microstep)):
            x = advance(x, voltage, R, inverse, microstep)
            model.flux(x[:2])
            max_domain = max(max_domain, float(np.sum(abs(x[:2]))))
            max_balance = max(max_balance, abs(float(x[2]-x[3]-.75*x[:2]@matrix@x[:2])))
        exact = propagator@exact+(np.eye(2)-propagator)@voltage/R
        max_exact = max(max_exact, float(np.max(abs(x[:2]-exact))))
    final = history[-1].copy()
    final[:3] = [800*DT, *x[:2]]
    final[6:8] = model.flux(x[:2]).tolist()
    final[8] = float(6*(final[6]*x[1]-final[7]*x[0]))
    final[9:13] = [x[2], x[3], float(.75*x[:2]@matrix@x[:2]),
                    float(x[2]-x[3]-.75*x[:2]@matrix@x[:2])]
    history.append(final)
    samples = np.asarray(history)
    steady = samples[np.r_[np.arange(300, 400), np.arange(700, 800)]]
    tracking = float(np.max(abs(steady[:, 2]-steady[:, 3])))
    d_error = float(np.max(abs(steady[:, 1])))
    return samples, dict(exact_error_a=max_exact, max_balance_j=max_balance,
                         max_l1_current_a=max_domain, steady_q_error_a=tracking,
                         steady_d_a=d_error, limited_commands=limited, commands=800,
                         max_voltage_v=float(np.max(np.linalg.norm(samples[:, 4:6], axis=1))),
                         vdc_v=vdc, microstep_s=microstep)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = ROOT / "outputs/frozen-flux/model.json"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == MODEL_SHA
    upstream = "f8cfb936deb271ece2908bb8ab4781ba2270ce5b"
    subprocess.run(["git", "fetch", "origin", upstream, "--depth=1"], check=True)
    subprocess.run(["git", "diff", "--exit-code", upstream, "HEAD", "--",
                    "benchmarks/p7_local_flux_model.py", "src/oeal/current_control.py",
                    "src/oeal/foc.py", "src/oeal/transforms.py"], check=True)
    frozen = json.loads(source.read_text())
    verified = ROOT / "outputs/frozen-flux/verified-source.json"
    assert hashlib.sha256(verified.read_bytes()).hexdigest() == frozen["source_sha256"]
    assert abs(json.loads(verified.read_text())["rows"][0]["electrical_rad"]-ANGLE) <= 1e-15
    model = LocalFluxModel(frozen["psi_wb"], frozen["inductance_h"])
    (OUT / "model.json").write_bytes(source.read_bytes())
    nominal, n = simulate(model, 48., 5e-6)
    fine, f = simulate(model, 48., 2.5e-6)
    low, l = simulate(model, .18, 5e-6)
    refinement = float(np.max(abs(nominal[:, 1:3]-fine[:, 1:3])))
    checks = dict(tracking=n["steady_q_error_a"] <= .005 and n["steady_d_a"] <= .005,
                  exact=max(x["exact_error_a"] for x in (n, f, l)) <= 1e-7,
                  energy=max(x["max_balance_j"] for x in (n, f, l)) <= 1e-9,
                  refinement=refinement <= 1e-7,
                  domain=max(x["max_l1_current_a"] for x in (n, f, l)) <= 2,
                  voltage=all(x["max_voltage_v"] <= x["vdc_v"]/math.sqrt(3)+1e-12
                              for x in (n, f, l)),
                  undervoltage=l["limited_commands"] > 0 and l["steady_q_error_a"] > .05,
                  frozen=hashlib.sha256(source.read_bytes()).hexdigest() == MODEL_SHA)
    columns = ("time_s,id_a,iq_a,iq_reference_a,vd_v,vq_v,lambda_d_wb,lambda_q_wb,"
               "reaction_torque_nm,source_j,copper_j,magnetic_j,balance_j,limited,"
               "duty_a,duty_b,duty_c").split(",")
    for name, values in (("nominal", nominal), ("fine", fine), ("undervoltage", low)):
        with (OUT / (name+".csv")).open("w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            writer.writerow(columns)
            writer.writerows(values.tolist())
    report = dict(passed=all(checks.values()), checks=checks, nominal=n, fine=f, undervoltage=l,
                  refinement_error_a=refinement, model_sha256=MODEL_SHA,
                  assigned_resistance_ohm=R, electrical_angle_rad=ANGLE,
                  commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
    (OUT / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("locked-summary: "+json.dumps(report), flush=True)
    assert report["passed"], checks


if __name__ == "__main__":
    main()
