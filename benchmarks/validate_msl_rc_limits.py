"""Actual parametric FMU versus exact RC matrix exponential and time/energy scaling."""
import json
from pathlib import Path

import numpy as np
from msl_parametric_drive_adapter import MSLParametricDrive
from msl_rc_reference import CAPACITY, RESISTANCE, linear_solution
from scipy.integrate import solve_ivp

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/msl-rc"
INITIAL = [80.,70.,60.,100.,65.,50.]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    reports, kept = [], {}
    for name, capacities, resistances, case_r, h, duration in [
        ("linear-default", CAPACITY, RESISTANCE, 2., .1, 4.),
        ("linear-double-c", 2*CAPACITY, RESISTANCE, 2., .2, 8.),
        ("linear-double-r", CAPACITY, 2*RESISTANCE, 4., .1, 4.),
    ]:
        provider = MSLParametricDrive(
            OUT / (name+"-rhs.csv.gz"), duration, 0., initial_temperatures_c=INITIAL,
            capacities_j_per_k=capacities, link_resistances_k_per_w=resistances,
            case_resistance_k_per_w=case_r)
        state = np.r_[INITIAL, np.zeros(4)]
        rows = [state.copy()]
        provider.evaluate(0., state[:6], np.zeros(6), 0., 0.,
                          branch_energy_j=[0.]*3, accepted=True)

        def generated(t, x, model=provider):
            rate = model.evaluate(t, x[:6], np.zeros(6), x[6], sum(x[7:]),
                                     branch_energy_j=x[7:])
            return np.r_[rate[:7], rate[8:]]

        try:
            for k in range(round(duration/h)):
                t = k*h
                solution = solve_ivp(generated, (t, t+h), state, method="DOP853",
                                     rtol=2e-12, atol=2e-12)
                assert solution.success
                state = solution.y[:, -1]
                provider.evaluate(t+h, state[:6], np.zeros(6), state[6], sum(state[7:]),
                                  branch_energy_j=state[7:], accepted=True)
                rows.append(state.copy())
            metadata = provider.describe()
        finally:
            provider.close()
        times = np.arange(len(rows))*h
        actual = np.asarray(rows)
        expected = np.asarray([linear_solution(t, INITIAL, 25., capacities, resistances,
                                               case_r) for t in times])
        temperature_error = float(np.max(abs(actual[:, :6]-expected[:, :6])))
        energy_error = float(np.max(abs(actual[:, 6:]-expected[:, 6:])))
        balance = (actual[:, :6]-INITIAL) @ capacities+actual[:, 7:].sum(axis=1)
        wrong_c = (actual[:, :6]-INITIAL) @ CAPACITY+actual[:, 7:].sum(axis=1)
        c_fault = bool(max(abs(wrong_c)) > 1e-5) if name == "linear-double-c" else None
        np.savetxt(OUT / (name+".csv"),
                   np.column_stack([times, actual, expected, balance, wrong_c]),
                   delimiter=",", header="time_s,"+",".join(
                       [f"actual_{i}" for i in range(10)]+[f"exact_{i}" for i in range(10)]
                       +["balance_j", "wrong_default_c_balance_j"]), comments="")
        passed = bool(temperature_error <= 2e-7 and energy_error <= 1e-5
                      and max(abs(balance)) <= 1e-5 and np.all(actual[:, 6] == 0)
                      and c_fault is not False)
        result = dict(id=name, passed=passed, temperature_error_k=temperature_error,
                      energy_error_j=energy_error, balance_peak_j=float(max(abs(balance))),
                      wrong_capacity_fault_detected=c_fault, provider=metadata)
        reports.append(result)
        kept[name] = actual
    a, b = kept["linear-default"], kept["linear-double-c"]
    scaling_temperature = float(np.max(abs(a[:, :6]-b[:, :6])))
    scaling_energy = float(np.max(abs(2*a[:, 7:]-b[:, 7:])))
    summary = dict(passed=all(c["passed"] for c in reports) and scaling_temperature <= 2e-7
                   and scaling_energy <= 1e-5, cases=reports,
                   scaling_temperature_k=scaling_temperature, scaling_energy_j=scaling_energy)
    (OUT / "linear-limits.json").write_text(json.dumps(summary, indent=2))
    print("rc-linear-limits: "+json.dumps(summary), flush=True)
    assert summary["passed"]


if __name__ == "__main__":
    main()
