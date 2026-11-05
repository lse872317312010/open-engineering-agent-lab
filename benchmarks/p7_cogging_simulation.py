"""Coupled FOC and mechanical ODE with independent DOP853 replay."""
import csv
import hashlib
import json
import math
from functools import partial
from pathlib import Path

import numpy as np
import p7_cogging_model as cogging
from scipy.integrate import solve_ivp

from oeal.current_control import CurrentPIParameters, CurrentPIState, current_control_step
from oeal.foc import average_svpwm
from oeal.transforms import inverse_park, park

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-cogging-report"
OFFSET, TS, LOAD = -3.069879826333843e-5, 50e-6, .05


class DomainViolation(Exception):
    def __init__(self, time, current, reason):
        super().__init__(reason)
        self.time, self.current = time, current


def derivative(model, stationary, load, at, state):
    voltage = np.array(park(*stationary, OFFSET+4*state[2]))
    try:
        di, dtheta, domega = model.rhs(state[2], state[3], state[:2], voltage, load)
        powers = model.powers(state[2], state[3], state[:2], voltage, load)
    except ValueError as exc:
        raise DomainViolation(at, state[:2].tolist(), str(exc)) from exc
    return np.r_[di, dtheta, domega, powers]


def simulate(model, direction, dt):
    matrix = model.inductance
    p = CurrentPIParameters(matrix[0, 0]*1000, model.resistance*1000,
                            matrix[1, 1]*1000, model.resistance*1000,
                            48/math.sqrt(3), 1., 1000.)
    pi = CurrentPIState()
    state, replay = np.zeros(8), np.zeros(8)
    rows, rejection = [], None
    max_i = max_angle = max_speed = max_balance = max_domain = 0.
    time, commands, limited = 0., 0, 0
    last = None
    load = direction*LOAD

    def record(at, reference, stationary, saturated, duties):
        voltage = park(*stationary, OFFSET+4*state[2])
        total, cog, increment = model.torque(state[2], state[:2])
        stored = model.stored(state[2], state[:2])
        kinetic = .5*model.inertia*state[3]**2
        balance = state[4]-state[5]-state[6]-state[7]-stored-kinetic
        return dict(time_s=float(at), id_a=float(state[0]), iq_a=float(state[1]),
                    reference_a=reference, theta_rad=float(state[2]), omega_rad_s=float(state[3]),
                    vd_v=float(voltage[0]), vq_v=float(voltage[1]), torque_nm=total,
                    cog_torque_nm=cog, increment_torque_nm=increment, source_j=float(state[4]),
                    copper_j=float(state[5]), friction_j=float(state[6]), load_j=float(state[7]),
                    magnetic_j=stored, kinetic_j=float(kinetic), balance_j=float(balance),
                    limited=bool(saturated), duty_a=float(duties[0]), duty_b=float(duties[1]),
                    duty_c=float(duties[2]))

    for tick in range(1000):
        start = tick*TS
        angle, omega = state[2:4]
        flux = model.flux(angle, state[:2])
        feedforward = omega*(model.psi.derivative(angle)+4*cogging.JROT@flux)
        command = current_control_step(
            p, pi, reference_d_a=0., reference_q_a=direction*.5,
            measured_d_a=float(state[0]), measured_q_a=float(state[1]), period_s=TS,
            feedforward_d_v=float(feedforward[0]), feedforward_q_v=float(feedforward[1]))
        pi = command.next_state
        stationary = inverse_park(command.vd_v, command.vq_v, OFFSET+4*angle)
        alpha, beta, duties = average_svpwm(*stationary, 48.)
        stationary = np.array([alpha, beta])
        limited += int(command.voltage_limited)
        commands += 1
        last = (direction*.5, stationary, command.voltage_limited, duties)
        rows.append(record(start, *last))
        try:
            for substep in range(round(TS/dt)):
                at = start+substep*dt
                k1 = derivative(model, stationary, load, at, state)
                k2 = derivative(model, stationary, load, at+dt/2, state+dt*k1/2)
                k3 = derivative(model, stationary, load, at+dt/2, state+dt*k2/2)
                k4 = derivative(model, stationary, load, at+dt, state+dt*k3)
                candidate = state+dt*(k1+2*k2+2*k3+k4)/6
                try:
                    model.current(candidate[:2])
                except ValueError as exc:
                    raise DomainViolation(at+dt, candidate[:2].tolist(), str(exc)) from exc
                state = candidate
                time = at+dt
                max_domain = max(max_domain, float(np.sum(abs(state[:2]))))
                balance = (state[4]-state[5]-state[6]-state[7]-model.stored(state[2], state[:2])
                           -.5*model.inertia*state[3]**2)
                max_balance = max(max_balance, abs(float(balance)))
            reference = solve_ivp(partial(derivative, model, stationary, load),
                                  (start, start+TS), replay, method="DOP853",
                                  rtol=1e-10, atol=1e-12)
            assert reference.success
            replay = reference.y[:, -1]
            max_i = max(max_i, float(np.max(abs(state[:2]-replay[:2]))))
            max_angle = max(max_angle, abs(float(state[2]-replay[2])))
            max_speed = max(max_speed, abs(float(state[3]-replay[3])))
        except DomainViolation as exc:
            rejection = dict(time_s=exc.time, current_a=exc.current, reason=str(exc),
                             last_accepted_time_s=time)
            break
    rows.append(record(time, *last))
    return dict(completed=rejection is None, commands=commands, samples=len(rows),
                direction=direction, dt_s=dt, rows=rows, rejection=rejection,
                max_current_error_a=max_i, max_angle_error_rad=max_angle,
                max_speed_error_rad_s=max_speed, max_balance_j=max_balance,
                max_l1_current_a=max_domain, limited_commands=limited,
                max_voltage_v=max(math.hypot(r["vd_v"], r["vq_v"]) for r in rows),
                final_omega_rad_s=rows[-1]["omega_rad_s"],
                final_theta_rad=rows[-1]["theta_rad"])


def mechanical_limit(model):
    initial = np.array([.1, 0.])
    energy0 = -float(model.cog.integral(initial[0])[0])

    def rhs(_, y):
        return [y[1], float(model.cog.value(y[0])[0])/model.inertia]

    result = solve_ivp(rhs, (0, .05), initial, t_eval=np.linspace(0, .05, 101),
                       method="DOP853", rtol=1e-11, atol=1e-13)
    assert result.success
    errors = [abs(.5*model.inertia*speed**2-float(model.cog.integral(angle)[0])-energy0)
              for angle, speed in zip(*result.y, strict=True)]
    return dict(passed=bool(max(errors) <= 1e-8), max_balance_j=float(max(errors)),
                initial_theta_rad=initial[0], final_theta_rad=float(result.y[0, -1]),
                final_omega_rad_s=float(result.y[1, -1]))


def main():
    fields = json.loads((OUT / "fields.json").read_text())
    path = OUT / "coenergy-model.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == fields["model_sha256"]
    parameters = json.loads(path.read_text())
    psi = cogging.FourierSeries(parameters["psi_a"], parameters["psi_b"])
    cog = cogging.FourierSeries(parameters["cog_a"], parameters["cog_b"])
    motor = cogging.CoggingMotor(psi, cog, parameters["inductance_h"])
    cases = []
    for name, direction, dt in (("forward", 1., 5e-6), ("reverse", -1., 5e-6),
                                ("fine", 1., 2.5e-6)):
        case = simulate(motor, direction, dt)
        case["name"] = name
        with (OUT / (name+".csv")).open("w", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=list(case["rows"][0]))
            writer.writeheader()
            writer.writerows(case["rows"])
        cases.append(case)
    completed = all(c["completed"] and c["commands"] == 1000 for c in cases)
    if completed:
        refinement = {key: max(abs(a[key]-b[key]) for a, b in
                               zip(cases[0]["rows"], cases[2]["rows"], strict=True))
                      for key in ("id_a", "iq_a", "theta_rad", "omega_rad_s")}
    else:
        refinement = None
    isolated = mechanical_limit(motor)
    checks = dict(completed=completed, mechanical_limit=isolated["passed"],
                  replay=completed and max(c["max_current_error_a"] for c in cases) <= 1e-4
                  and max(c["max_angle_error_rad"] for c in cases) <= 1e-5
                  and max(c["max_speed_error_rad_s"] for c in cases) <= 1e-3,
                  refinement=completed and max(refinement["id_a"], refinement["iq_a"]) <= 1e-4
                  and refinement["theta_rad"] <= 1e-5 and refinement["omega_rad_s"] <= 1e-3,
                  energy=max(c["max_balance_j"] for c in cases) <= 1e-5,
                  domain=max(c["max_l1_current_a"] for c in cases) <= 2,
                  voltage=all(c["max_voltage_v"] <= 48/math.sqrt(3)+1e-12 for c in cases),
                  model_frozen=hashlib.sha256(path.read_bytes()).hexdigest()
                  == fields["model_sha256"])
    checks = {name: bool(value) for name, value in checks.items()}
    data = dict(passed=all(checks.values()), checks=checks,
                model_supported=fields["model_supported"],
                refinement=refinement, mechanical_limit=isolated, cases=cases,
                model_sha256=fields["model_sha256"], inertia_kg_m2=motor.inertia,
                friction_nm_s_rad=motor.friction, load_nm=LOAD, resistance_ohm=motor.resistance)
    (OUT / "dynamics.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("cogging-dynamic-summary: "+json.dumps({k: v for k, v in data.items() if k != "cases"})
          +", cases="+json.dumps([{k: v for k, v in c.items() if k != "rows"} for c in cases]),
          flush=True)


if __name__ == "__main__":
    main()
