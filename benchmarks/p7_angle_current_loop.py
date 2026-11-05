"""20 kHz PI/SVPWM with angle-dependent flux and piecewise-exact replay."""
import csv
import json
import math
from pathlib import Path

import numpy as np
from p7_angle_flux import AngleFlux
from scipy.linalg import expm

from oeal.current_control import CurrentPIParameters, CurrentPIState, current_control_step
from oeal.foc import average_svpwm
from oeal.transforms import inverse_park, park

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-angle-dynamics"
J = np.array([[0., -1.], [1., 0.]])
OFFSET = -3.069879826333843e-5
TS = 50e-6


class DomainViolation(Exception):
    def __init__(self, time, current, message):
        super().__init__(message)
        self.time = time
        self.current = current


def dynamics(model, omega, stationary, at, state, segment):
    voltage = np.array(park(*stationary, OFFSET+4*omega*at))
    try:
        derivative = model.rhs(omega*at, omega, voltage, state[:2], segment)
        power = model.power(omega*at, omega, voltage, state[:2], segment)
    except ValueError as exc:
        raise DomainViolation(at, state[:2].tolist(), str(exc)) from exc
    return np.concatenate((derivative, power))


def reference_step(model, omega, stationary, start, current, segment):
    inv = np.linalg.inv(model.inductance)
    psi, slope = model.coefficients(omega*start, segment)
    matrix = np.zeros((6, 6))
    matrix[:2, :2] = -inv@(model.resistance*np.eye(2)+4*omega*J@model.inductance)
    matrix[:2, 2:4] = inv
    matrix[:2, 4] = -inv@(4*omega*omega*J@slope)
    matrix[:2, 5] = -inv@(omega*slope+4*omega*J@psi)
    matrix[2:4, 2:4] = -4*omega*J
    matrix[4, 5] = 1.
    voltage = park(*stationary, OFFSET+4*omega*start)
    return (expm(matrix*TS)@np.array([*current, *voltage, 0., 1.]))[:2]


def simulate(model, rpm, vdc, dt):
    omega = rpm*2*math.pi/60
    matrix = model.inductance
    parameters = CurrentPIParameters(matrix[0, 0]*1000, model.resistance*1000,
                                     matrix[1, 1]*1000, model.resistance*1000,
                                     vdc/math.sqrt(3), 1., 1000.)
    pi = CurrentPIState()
    state, exact = np.zeros(5), np.zeros(2)
    rows, rejection = [], None
    max_exact = max_balance = max_domain = 0.
    limited = commands = 0
    time = 0.
    last = None

    def record(at, reference, stationary, saturated, duties):
        voltage = park(*stationary, OFFSET+4*omega*at)
        flux = model.flux(omega*at, state[:2])
        power = model.power(omega*at, omega, voltage, state[:2])
        magnetic = model.stored(state[:2])
        return dict(time_s=at, id_a=float(state[0]), iq_a=float(state[1]),
                    reference_a=reference, vd_v=voltage[0], vq_v=voltage[1],
                    lambda_d_wb=float(flux[0]), lambda_q_wb=float(flux[1]),
                    torque_nm=float(power[2]/omega), source_j=float(state[2]),
                    copper_j=float(state[3]), mechanical_j=float(state[4]),
                    stored_j=magnetic,
                    balance_j=float(state[2]-state[3]-state[4]-magnetic),
                    limited=bool(saturated), duty_a=duties[0], duty_b=duties[1],
                    duty_c=duties[2], theta_rad=omega*at)

    for tick in range(500):
        start = tick*TS
        reference = 0. if tick < 20 else .5 if tick < 250 else -.5
        segment = int(((omega*(start+TS/2)) % model.period)/model.step)
        psi, slope = model.coefficients(omega*start, segment)
        flux = psi+matrix@state[:2]
        feedforward = omega*slope+4*omega*J@flux
        command = current_control_step(
            parameters, pi, reference_d_a=0., reference_q_a=reference,
            measured_d_a=float(state[0]), measured_q_a=float(state[1]), period_s=TS,
            feedforward_d_v=float(feedforward[0]), feedforward_q_v=float(feedforward[1]))
        pi = command.next_state
        stationary = inverse_park(command.vd_v, command.vq_v, OFFSET+4*omega*start)
        alpha, beta, duties = average_svpwm(*stationary, vdc)
        stationary = np.array([alpha, beta])
        limited += int(command.voltage_limited)
        commands += 1
        last = (reference, stationary, command.voltage_limited, duties)
        rows.append(record(start, *last))
        try:
            for substep in range(round(TS/dt)):
                at = start+substep*dt
                k1 = dynamics(model, omega, stationary, at, state, segment)
                k2 = dynamics(model, omega, stationary, at+dt/2, state+dt*k1/2, segment)
                k3 = dynamics(model, omega, stationary, at+dt/2, state+dt*k2/2, segment)
                k4 = dynamics(model, omega, stationary, at+dt, state+dt*k3, segment)
                candidate = state+dt*(k1+2*k2+2*k3+k4)/6
                try:
                    model.current(candidate[:2])
                except ValueError as exc:
                    raise DomainViolation(at+dt, candidate[:2].tolist(), str(exc)) from exc
                state = candidate
                time = at+dt
                max_domain = max(max_domain, float(np.sum(abs(state[:2]))))
                balance = state[2]-state[3]-state[4]-model.stored(state[:2])
                max_balance = max(max_balance, abs(float(balance)))
        except DomainViolation as exc:
            rejection = dict(time_s=exc.time, current_a=exc.current, reason=str(exc),
                             last_accepted_time_s=time)
            break
        exact = reference_step(model, omega, stationary, start, exact, segment)
        max_exact = max(max_exact, float(np.max(abs(state[:2]-exact))))
    rows.append(record(time, *last))
    completed = rejection is None
    steady = ([r for r in rows if .009 <= r["time_s"] < .012
               or .021 <= r["time_s"] < .024] if completed else [])
    metrics = dict(completed=completed, commands=commands, samples=len(rows),
                   rpm=rpm, vdc_v=vdc, microstep_s=dt, exact_error_a=max_exact,
                   max_balance_j=max_balance, max_l1_current_a=max_domain,
                   limited_commands=limited, rejection=rejection,
                   steady_q_error_a=(max(abs(r["iq_a"]-r["reference_a"]) for r in steady)
                                     if steady else None),
                   steady_d_a=max(abs(r["id_a"]) for r in steady) if steady else None,
                   max_voltage_v=max(math.hypot(r["vd_v"], r["vq_v"]) for r in rows))
    return rows, metrics


def main():
    fields = json.loads((OUT / "fields.json").read_text())
    parameters = json.loads((OUT / "model.json").read_text())
    knots = [next(r["actual_wb"] for r in fields["rows"]
                  if r["angle_deg"] == angle and (r["id_a"], r["iq_a"]) == (0, 0))
             for angle in (0., 11.25, 22.5, 33.75, 45.)]
    model = AngleFlux(knots, parameters["inductance_h"])
    scenarios = []
    for name, rpm, vdc, dt in (("control-forward", 300., 48., 5e-6),
                                ("control-reverse", -300., 48., 5e-6),
                                ("control-fine", 300., 48., 2.5e-6),
                                ("control-undervoltage", 300., 6., 5e-6)):
        rows, metrics = simulate(model, rpm, vdc, dt)
        with (OUT / (name+".csv")).open("w", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        scenarios.append(dict(name=name, rows=rows, **metrics))
    normal = scenarios[:3]
    low = scenarios[3]
    completed = all(s["completed"] and s["commands"] == 500 for s in normal)
    refinement = (max(max(abs(a["id_a"]-b["id_a"]), abs(a["iq_a"]-b["iq_a"]))
                      for a, b in zip(normal[0]["rows"], normal[2]["rows"], strict=True))
                  if completed else None)
    checks = dict(completed=completed,
                  tracking=completed and all(s["steady_q_error_a"] <= .005
                                             and s["steady_d_a"] <= .005 for s in normal),
                  exact=completed and max(s["exact_error_a"] for s in normal) <= 1e-5,
                  refinement=completed and refinement <= 1e-5,
                  energy=max(s["max_balance_j"] for s in scenarios) <= 1e-5,
                  domain=max(s["max_l1_current_a"] for s in scenarios) <= 2,
                  voltage=all(s["max_voltage_v"] <= s["vdc_v"]/math.sqrt(3)+1e-12
                              for s in scenarios),
                  rejection=not low["completed"] and low["rejection"]["time_s"] < .025)
    data = dict(passed=all(checks.values()), checks=checks, refinement_error_a=refinement,
                scenarios=scenarios, model="periodic piecewise-linear flux; prescribed speed")
    (OUT / "control.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("angle-control: "+json.dumps({k: v for k, v in data.items() if k != "scenarios"})
          +", cases="+json.dumps([{k: v for k, v in c.items() if k != "rows"}
                                  for c in scenarios]), flush=True)


if __name__ == "__main__":
    main()
