"""Actual MSL ME thermal experiment; independent full-stream derivative and energy audit."""
import csv
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from msl_identification_protocol import AREA, DT, GC, NODES, NOISE, inputs
from msl_parametric_drive_adapter import LOG_COLUMNS, MSLParametricDrive
from msl_rc_reference import rates
from scipy.integrate import solve_ivp

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/msl-identification"
COLUMNS = ["time_s", *[n+"_c" for n in NODES], "input_j", "case_j", "convection_j",
           "radiation_j", *[n+"_next_power_w" for n in NODES]]
MEASURED = ["time_s", *[n+"_c" for n in NODES], *[n+"_next_power_w" for n in NODES]]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(path, physical, ambient):
    worst = np.zeros(11)
    balance = 0.
    count = 0
    capacities = np.asarray(physical["capacities_j_per_k"])

    def process(rows):
        nonlocal balance, count
        a = np.asarray(rows, dtype=float)
        expected = rates(a[:, 2:8], a[:, 8:14], a[:, 19], AREA, ambient, capacities,
                         physical["link_resistances_k_per_w"],
                         physical["case_resistance_k_per_w"])
        worst[:] = np.maximum(worst, np.max(abs(a[:, 20:31]-expected), axis=0))
        balance = max(balance, float(np.max(abs(
            a[:, 20:26] @ capacities+a[:, 27]-a[:, 8:14].sum(axis=1)))))
        count += len(a)

    with gzip.open(path, "rt") as f:
        reader = csv.reader(f)
        assert next(reader) == LOG_COLUMNS
        batch = []
        for row in reader:
            batch.append(row)
            if len(batch) == 20000:
                process(batch)
                batch = []
        if batch:
            process(batch)
    passed = bool(max(worst[:6]) <= 2e-7 and worst[6] <= 1e-8
                  and max(worst[7:]) <= 2e-7 and balance <= 1e-8)
    return dict(passed=passed, rows=count, derivative_errors=worst.tolist(),
                power_balance_w=balance)


def simulate(case, physical, destination):
    destination.mkdir(parents=True, exist_ok=True)
    times = np.arange(round(case["duration_s"]/DT)+1)*DT
    power = inputs(case)
    state = np.r_[case["initial_c"], np.zeros(4)]
    rows = [state.copy()]
    provider = MSLParametricDrive(
        destination / "rhs.csv.gz", case["duration_s"], AREA,
        ambient_c=case["ambient_c"], initial_temperatures_c=case["initial_c"], **physical)
    try:
        provider.evaluate(0., state[:6], power[0], 0., 0.,
                          branch_energy_j=[0.]*3, accepted=True)
        for k in range(len(times)-1):
            held = power[k].copy()

            def generated(t, x, heat=held, model=provider):
                value = model.evaluate(t, x[:6], heat, x[6], sum(x[7:]),
                                       branch_energy_j=x[7:])
                return np.r_[value[:7], value[8:]]

            h = times[k+1]-times[k]
            solution = solve_ivp(generated, (times[k], times[k+1]), state, method="DOP853",
                                 rtol=2e-12, atol=2e-12, first_step=h, max_step=h)
            assert solution.success, solution.message
            state = solution.y[:, -1]
            provider.evaluate(times[k+1], state[:6], held, state[6], sum(state[7:]),
                              branch_energy_j=state[7:], accepted=True)
            rows.append(state.copy())
        metadata = provider.describe()
    finally:
        provider.close()
    actual = np.asarray(rows)
    balance = ((actual[:, :6]-case["initial_c"]) @ physical["capacities_j_per_k"]
               -actual[:, 6]+actual[:, 7:].sum(axis=1))
    data = np.column_stack([times, actual, power])
    np.savetxt(destination / "trajectory.csv", data, delimiter=",", header=",".join(COLUMNS),
               comments="")
    rhs_audit = audit(destination / "rhs.csv.gz", physical, case["ambient_c"])
    assert rhs_audit["rows"] == metadata["rhs_calls"]+metadata["accepted_checkpoints"]
    assert metadata["accepted_checkpoints"] == len(times)
    report = dict(passed=bool(rhs_audit["passed"] and max(abs(balance)) <= 1e-5),
                  id=case["id"], config=case, rows=len(times),
                  provider=metadata, rhs_audit=rhs_audit,
                  balance_peak_j=float(max(abs(balance))),
                  trajectory_sha256=sha(destination / "trajectory.csv"))
    (destination / "simulation.json").write_text(json.dumps(report, indent=2))
    print("identification-simulation: "+json.dumps(report), flush=True)
    assert report["passed"]
    return data, report


def measurements(case, data, destination):
    noise = np.random.default_rng(case["noise_seed"]).normal(0., NOISE, (len(data), 6))
    measured = np.column_stack([data[:, 0], data[:, 1:7]+noise, data[:, 11:17]])
    np.savetxt(destination / "measurements.csv", measured, delimiter=",",
               header=",".join(MEASURED), comments="")
    public = dict(split=case["id"], ambient_c=case["ambient_c"], area_m2=AREA,
                  convection_w_per_k=GC, period_s=DT, noise_sigma_k=NOISE,
                  columns=MEASURED,
                  observation_contract="six measured nodes; known interval powers")
    (destination / "public.json").write_text(json.dumps(public, indent=2))
    return sha(destination / "measurements.csv")
