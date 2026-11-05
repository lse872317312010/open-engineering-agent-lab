"""Simulate an angle-dependent flux interface with independent matrix-exponential replay."""
import csv
import json
import math
from pathlib import Path

import numpy as np
from p7_angle_flux import AngleFlux
from scipy.linalg import expm

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-angle-dynamics"
J = np.array([[0., -1.], [1., 0.]])
PAIRS = ((0, 0), (0, 2), (1, 1), (-1, 1))


def rhs(model, omega, voltage, time, state, segment):
    current = state[:2]
    return np.concatenate((model.rhs(omega*time, omega, voltage, current, segment),
                           model.power(omega*time, omega, voltage, current, segment)))


def integrate(model, omega, voltage, dt):
    count = round(.025/dt)
    stride = round(.00005/dt)
    state = np.zeros(5)
    rows, rejection = [], None
    for n in range(count+1):
        time = n*dt
        if n % stride == 0:
            power = model.power(omega*time, omega, voltage, state[:2])
            rows.append(dict(time_s=time, theta_rad=omega*time, id_a=float(state[0]),
                             iq_a=float(state[1]), source_w=float(power[0]),
                             copper_w=float(power[1]), mechanical_w=float(power[2]),
                             source_j=float(state[2]), copper_j=float(state[3]),
                             mechanical_j=float(state[4]), stored_j=model.stored(state[:2]),
                             balance_j=float(state[2]-state[3]-state[4]-model.stored(state[:2]))))
        if n == count:
            break
        segment = int(((omega*(time+dt/2)) % model.period)/model.step)
        try:
            k1 = rhs(model, omega, voltage, time, state, segment)
            k2 = rhs(model, omega, voltage, time+dt/2, state+dt*k1/2, segment)
            k3 = rhs(model, omega, voltage, time+dt/2, state+dt*k2/2, segment)
            k4 = rhs(model, omega, voltage, time+dt, state+dt*k3, segment)
            candidate = state+dt*(k1+2*k2+2*k3+k4)/6
            model.current(candidate[:2])
            state = candidate
        except ValueError as exc:
            rejection = dict(time_s=time, reason=str(exc), last_valid=state[:2].tolist())
            break
    return rows, rejection


def exact_replay(model, omega, voltage, rows):
    current = np.zeros(2)
    errors = [0.]
    inv = np.linalg.inv(model.inductance)
    a = -inv@(model.resistance*np.eye(2)+4*omega*J@model.inductance)
    for row, next_row in zip(rows[:-1], rows[1:], strict=True):
        dt = next_row["time_s"]-row["time_s"]
        theta = omega*row["time_s"]
        segment = int(((theta+omega*dt/2) % model.period)/model.step)
        psi, slope = model.coefficients(theta, segment)
        b = inv@(voltage-omega*slope-4*omega*J@psi)
        c = -inv@(4*omega*omega*J@slope)
        matrix = np.zeros((4, 4))
        matrix[:2, :2], matrix[:2, 2], matrix[:2, 3], matrix[2, 3] = a, c, b, 1.
        current = (expm(matrix*dt)@np.r_[current, 0., 1.])[:2]
        errors.append(float(np.max(np.abs(current-[next_row["id_a"], next_row["iq_a"]]))))
    return max(errors)


def main():
    fields = json.loads((OUT / "fields.json").read_text())
    assert fields["evidence_passed"]
    model_data = json.loads((OUT / "model.json").read_text())
    knots = [next(r["actual_wb"] for r in fields["rows"]
                  if r["angle_deg"] == angle and (r["id_a"], r["iq_a"]) == (0, 0))
             for angle in (0., 11.25, 22.5, 33.75, 45.)]
    model = AngleFlux(knots, model_data["inductance_h"])
    results = []
    for rpm in (300, -300):
        omega = rpm*2*math.pi/60
        voltage = np.array([0., 4*omega*model.psi[0, 0]+.15])
        coarse, reject = integrate(model, omega, voltage, 5e-6)
        fine, fine_reject = integrate(model, omega, voltage, 2.5e-6)
        complete = reject is None and fine_reject is None and len(coarse) == len(fine) == 501
        replay = exact_replay(model, omega, voltage, coarse) if complete else None
        refinement = (max(max(abs(a["id_a"]-b["id_a"]), abs(a["iq_a"]-b["iq_a"]))
                          for a, b in zip(coarse, fine, strict=True)) if complete else None)
        balance = max(abs(row["balance_j"]) for row in coarse)
        passed = bool(complete and replay <= 1e-5 and refinement <= 1e-5 and balance <= 1e-5)
        name = "positive" if rpm > 0 else "negative"
        with (OUT / (name+".csv")).open("w", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=list(coarse[0]))
            writer.writeheader()
            writer.writerows(coarse)
        results.append(dict(name=name, rpm=rpm, voltage_dq=voltage.tolist(), rows=coarse,
                            rejection=reject, fine_rejection=fine_reject, passed=passed,
                            replay_error_a=replay, refinement_error_a=refinement,
                            max_balance_j=balance))
    midpoint = []
    for angle in (5.625, 16.875, 28.125, 39.375):
        row = next(r for r in fields["rows"]
                   if r["angle_deg"] == angle and (r["id_a"], r["iq_a"]) == (0, 0))
        difference = float(np.linalg.norm(model.flux(math.radians(angle), [0, 0])
                                          -row["actual_wb"])/.05)
        midpoint.append(dict(angle_deg=angle, flux_error=difference))
    summary = dict(passed=all(r["passed"] for r in results),
                   psi_knots_wb=knots, closure_correction_wb=model.closure_error.tolist(),
                   zero_midpoint_error=midpoint, cases=results,
                   limits="prescribed speed and dq voltage; synthetic angle-dependent model")
    (OUT / "dynamics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("angle-dynamics: "+json.dumps({k: v for k, v in summary.items() if k != "cases"})
          +", cases="+json.dumps([{k: v for k, v in c.items() if k != "rows"} for c in results]),
          flush=True)


if __name__ == "__main__":
    main()
