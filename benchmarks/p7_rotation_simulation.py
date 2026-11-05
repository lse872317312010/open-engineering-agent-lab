"""Prescribed-speed full-matrix local-model extension with held stationary voltage."""
import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import p7_rotation_reference as rotation
from p7_local_flux_model import LocalFluxModel
from scipy.linalg import expm

from oeal.current_control import CurrentPIParameters, CurrentPIState, current_control_step
from oeal.foc import average_svpwm
from oeal.transforms import inverse_park, park

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-rotation-report"
SHA = "dc8c5ca77d55c7fe876d7c18da1ad897896c9e0289b5d940417984fec1a6068e"
TS, R, OFFSET = 50e-6, .3, -3.069879826333843e-5


def simulate(model, rpm, vdc, dt):
    matrix, psi = model.inductance, model.psi
    omega = 4*rpm*2*math.pi/60
    inverse = np.linalg.inv(matrix)
    generator = np.zeros((5, 5))
    generator[:2, :2] = -inverse@(R*np.eye(2)+omega*rotation.J@matrix)
    generator[:2, 2:4] = inverse
    generator[:2, 4] = -inverse@(omega*rotation.J@psi)
    generator[2:4, 2:4] = -omega*rotation.J
    propagator = expm(generator*TS)
    parameters = CurrentPIParameters(matrix[0, 0]*1000, R*1000, matrix[1, 1]*1000,
                                     R*1000, vdc/math.sqrt(3), 1., 1000.)
    pi = CurrentPIState()
    state, exact = np.zeros(5), np.zeros(2)
    rows = []
    max_exact = max_balance = max_domain = 0.
    limited = 0
    rejection = None
    commands, time = 0, 0.

    def row(at, reference, stationary, saturated, duties):
        angle = OFFSET+omega*at
        voltage = park(*stationary, angle)
        flux = model.flux(state[:2])
        torque = float(6*(flux[0]*state[1]-flux[1]*state[0]))
        magnetic = float(.75*state[:2]@matrix@state[:2])
        balance = float(state[2]-state[3]-state[4]-magnetic)
        return [at, *state[:2], reference, *voltage, *flux, torque,
                state[2], state[3], state[4], magnetic, balance, int(saturated), *duties, angle]

    for tick in range(1200):
        start = tick*TS
        reference = 0. if tick < 20 else .5 if tick < 600 else -.5
        coupling = omega*rotation.J@model.flux(state[:2])
        command = current_control_step(
            parameters, pi, reference_d_a=0., reference_q_a=reference,
            measured_d_a=float(state[0]), measured_q_a=float(state[1]), period_s=TS,
            feedforward_d_v=float(coupling[0]), feedforward_q_v=float(coupling[1]))
        pi = command.next_state
        stationary = inverse_park(command.vd_v, command.vq_v, OFFSET+omega*start)
        alpha, beta, duties = average_svpwm(*stationary, vdc)
        stationary = np.array([alpha, beta])
        limited += int(command.voltage_limited)
        commands += 1
        rows.append(row(start, reference, stationary, command.voltage_limited, duties))
        try:
            for substep in range(round(TS/dt)):
                at = start+substep*dt
                state = rotation.advance(at, state, stationary, omega, OFFSET, R, matrix, psi, dt)
                time = at+dt
                model.flux(state[:2])
                max_domain = max(max_domain, float(np.sum(abs(state[:2]))))
                balance = state[2]-state[3]-state[4]-.75*state[:2]@matrix@state[:2]
                max_balance = max(max_balance, abs(float(balance)))
        except rotation.DomainViolation as exc:
            rejection = dict(time_s=exc.time_s, current_a=exc.current, reason=str(exc),
                             last_accepted_time_s=time)
            break
        voltage = np.array(park(*stationary, OFFSET+omega*start))
        exact = (propagator@np.array([*exact, *voltage, 1.]))[:2]
        max_exact = max(max_exact, float(np.max(abs(state[:2]-exact))))
    rows.append(row(time, reference, stationary, command.voltage_limited, duties))
    samples = np.asarray(rows)
    completed = rejection is None
    steady = samples[np.r_[np.arange(400, 600), np.arange(1000, 1200)]] if completed else None
    metrics = dict(completed=completed, commands=commands, samples=len(rows),
                   rpm=rpm, omega_e_rad_s=omega, vdc_v=vdc, microstep_s=dt,
                   exact_error_a=max_exact, max_balance_j=max_balance,
                   max_l1_current_a=max_domain, limited_commands=limited, rejection=rejection,
                   steady_q_error_a=(float(np.max(abs(steady[:, 2]-steady[:, 3])))
                                     if completed else None),
                   steady_d_a=float(np.max(abs(steady[:, 1]))) if completed else None,
                   max_voltage_v=float(np.max(np.linalg.norm(samples[:, 4:6], axis=1))),
                   shaft_energy_j=float(state[4]), source_energy_j=float(state[2]))
    return samples, metrics


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    path = ROOT / "outputs/frozen-flux/model.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == SHA
    upstream = "f8cfb936deb271ece2908bb8ab4781ba2270ce5b"
    subprocess.run(["git", "fetch", "origin", upstream, "--depth=1"], check=True)
    subprocess.run(["git", "diff", "--exit-code", upstream, "HEAD", "--",
                    "benchmarks/p7_local_flux_model.py", "src/oeal/current_control.py",
                    "src/oeal/foc.py", "src/oeal/transforms.py"], check=True)
    frozen = json.loads(path.read_text())
    model = LocalFluxModel(frozen["psi_wb"], frozen["inductance_h"])
    (OUT / "model.json").write_bytes(path.read_bytes())
    scenarios = {}
    series = {}
    for name, rpm, vdc, dt in (("forward", 300., 48., 5e-6), ("reverse", -300., 48., 5e-6),
                                ("fine", 300., 48., 2.5e-6), ("undervoltage", 300., 6., 5e-6)):
        series[name], scenarios[name] = simulate(model, rpm, vdc, dt)
    normal = [scenarios[name] for name in ("forward", "reverse", "fine")]
    refinement = float(np.max(abs(series["forward"][:, 1:3]-series["fine"][:, 1:3])))
    low = scenarios["undervoltage"]
    checks = dict(completed=all(s["completed"] and s["commands"] == 1200 for s in normal),
                  tracking=all(s["steady_q_error_a"] <= .005 and s["steady_d_a"] <= .005
                               for s in normal),
                  exact=max(s["exact_error_a"] for s in normal) <= 1e-7,
                  refinement=refinement <= 1e-7,
                  energy=max(s["max_balance_j"] for s in scenarios.values()) <= 1e-8,
                  domain=max(s["max_l1_current_a"] for s in scenarios.values()) <= 2,
                  voltage=all(s["max_voltage_v"] <= s["vdc_v"]/math.sqrt(3)+1e-12
                              for s in scenarios.values()),
                  rejection=not low["completed"] and low["rejection"]["time_s"] < .06,
                  frozen=hashlib.sha256(path.read_bytes()).hexdigest() == SHA)
    columns = ("time_s,id_a,iq_a,reference_a,vd_v,vq_v,lambda_d_wb,lambda_q_wb,torque_nm,"
               "source_j,copper_j,shaft_j,magnetic_j,balance_j,limited,duty_a,duty_b,duty_c,"
               "electrical_angle_rad").split(",")
    for name, values in series.items():
        with (OUT / (name+".csv")).open("w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            writer.writerow(columns)
            writer.writerows(values.tolist())
    data = dict(passed=all(checks.values()), checks=checks, scenarios=scenarios,
                refinement_error_a=refinement, model_sha256=SHA, resistance_ohm=R,
                commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
    (OUT / "validation.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("rotation-summary: "+json.dumps(data), flush=True)
    assert data["passed"], checks


if __name__ == "__main__":
    main()
