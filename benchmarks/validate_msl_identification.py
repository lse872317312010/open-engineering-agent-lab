"""Independent frozen-parameter evaluation, new FMU predictions and unused-case checks."""
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
from msl_identification_protocol import (
    AREA,
    GC,
    SPLITS,
    inputs,
    physical_vector,
    truth,
)
from msl_identification_simulator import COLUMNS, OUT, simulate
from msl_rc_reference import rates
from scipy.integrate import solve_ivp

from oeal.thermal_identification import NOMINAL_C, NOMINAL_G, fit_network

ROOT = Path(__file__).resolve().parents[1]


def physical(fit):
    return {n:fit[n] for n in ("capacities_j_per_k", "link_resistances_k_per_w",
                              "case_resistance_k_per_w")}


def reference(case, parameters):
    power = inputs(case)
    times = np.linspace(0., case["duration_s"], len(power))
    changes = np.where(np.any(np.diff(power[:-1], axis=0) != 0, axis=1))[0]+1
    edges = [0, *changes.tolist(), len(power)-1]
    state = np.r_[case["initial_c"], np.zeros(4)]
    result = [state.copy()]
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        held = power[a].copy()

        def generated(t, x, heat=held):
            value = rates(x[:6], heat, GC, AREA, case["ambient_c"],
                          parameters["capacities_j_per_k"],
                          parameters["link_resistances_k_per_w"],
                          parameters["case_resistance_k_per_w"])[0]
            return np.r_[value[:7], value[8:]]

        solution = solve_ivp(generated, (times[a], times[b]), state, method="Radau",
                             rtol=1e-11, atol=1e-11, dense_output=True)
        assert solution.success
        result.extend(solution.sol(times[a+1:b+1]).T)
        state = solution.y[:, -1]
    return np.asarray(result)


def main():
    fit_path = OUT / "fitted.json"
    frozen_hash = hashlib.sha256(fit_path.read_bytes()).hexdigest()
    fit = json.loads(fit_path.read_text())
    truth_parameters = json.loads((OUT / "reference/truth.json").read_text())
    assert truth_parameters == truth()
    expected = physical_vector(truth_parameters)
    relative = abs(physical_vector(fit)/expected-1)
    train = np.loadtxt(OUT / "train/trajectory.csv", delimiter=",", skiprows=1)
    ideal = fit_network(train[:, 0], train[:, 1:7], train[:-1, 11:17], 25., AREA, GC)
    ideal_relative = abs(physical_vector(ideal)/expected-1)
    training_packet = OUT / "train/measurements.csv"
    assert fit["source"]["measurement_sha256"] == hashlib.sha256(
        training_packet.read_bytes()).hexdigest()
    assert fit["source"]["opened_data_files"] == ["train/measurements.csv", "train/public.json"]
    nominal = dict(capacities_j_per_k=NOMINAL_C.tolist(),
                   link_resistances_k_per_w=(1/NOMINAL_G[:5]).tolist(),
                   case_resistance_k_per_w=float(1/NOMINAL_G[5]))
    evaluated = []
    for case in SPLITS[1:]:
        destination = OUT / ("prediction-"+case["id"])
        actual, simulation = simulate(case, physical(fit), destination)
        clean = np.loadtxt(OUT / case["id"] / "trajectory.csv", delimiter=",", skiprows=1)
        predicted_reference = reference(case, physical(fit))
        nominal_reference = reference(case, nominal)
        rmse = np.sqrt(np.mean((actual[:, 1:7]-clean[:, 1:7])**2, axis=0))
        peak = float(np.max(abs(actual[:, 1:7]-clean[:, 1:7])))
        total = float(np.sqrt(np.mean((actual[:, 1:7]-clean[:, 1:7])**2)))
        baseline = float(np.sqrt(np.mean((nominal_reference[:, :6]-clean[:, 1:7])**2)))
        numerical_t = float(np.max(abs(actual[:, 1:7]-predicted_reference[:, :6])))
        numerical_j = float(np.max(abs(actual[:, 7:11]-predicted_reference[:, 6:10])))
        passed = bool(max(rmse) <= .5 and peak <= 1.5 and total <= .5*baseline
                      and numerical_t <= 2e-7 and numerical_j <= 1e-5
                      and simulation["passed"])
        columns = [*COLUMNS, *["truth_"+n for n in COLUMNS[1:7]],
                   *["nominal_"+n for n in COLUMNS[1:7]], "balance_j"]
        balance = ((actual[:, 1:7]-case["initial_c"]) @ fit["capacities_j_per_k"]
                   -actual[:, 7]+actual[:, 8:11].sum(axis=1))
        csv_data = np.column_stack([actual, clean[:, 1:7], nominal_reference[:, :6], balance])
        np.savetxt(destination / "prediction.csv", csv_data, delimiter=",",
                   header=",".join(columns), comments="")
        stride = max(1, len(actual)//240)
        indices = sorted(set(range(0, len(actual), stride)) | {len(actual)-1})
        result = dict(id=case["id"], passed=passed, config=case, rows=len(actual),
                      rmse_by_node_k=rmse.tolist(), peak_error_k=peak, total_rmse_k=total,
                      nominal_total_rmse_k=baseline, rmse_ratio=total/baseline,
                      numerical_temperature_k=numerical_t, numerical_energy_j=numerical_j,
                      simulation=simulation, columns=columns, samples=csv_data[indices].tolist())
        evaluated.append(result)
        print("identification-evaluation: "+json.dumps(
            {k:v for k,v in result.items() if k not in {"samples", "columns"}}), flush=True)
    measurement = np.loadtxt(training_packet, delimiter=",", skiprows=1)
    corrupted = measurement.copy()
    corrupted[:, [1, 2]] = corrupted[:, [2, 1]]
    np.savetxt(OUT / "fault-swapped-measurements.csv", corrupted, delimiter=",",
               header=(OUT / "train/measurements.csv").read_text().splitlines()[0], comments="")
    try:
        wrong = fit_network(corrupted[:, 0], corrupted[:, 1:7], corrupted[:-1, 7:13],
                            25., AREA, GC)
        fault_error = float(np.max(abs(physical_vector(wrong)/expected-1)))
        swap_detected = bool(fault_error > .1 or any(wrong["active_bounds"]))
        swap_reason = dict(parameter_relative_error=fault_error,
                           active_bounds=wrong["active_bounds"])
    except ValueError as error:
        swap_detected, swap_reason = True, dict(error=str(error))
    try:
        times = np.linspace(0., 40., 801)
        fit_network(times, np.full((len(times), 6), 25.), np.zeros((len(times)-1, 6)), 25.)
        zero_detected = False
    except ValueError:
        zero_detected = True
    assert frozen_hash == hashlib.sha256(fit_path.read_bytes()).hexdigest()
    generation = json.loads((OUT / "generation.json").read_text())
    passed = bool(generation["passed"] and max(relative) <= .1 and max(ideal_relative) <= .005
                  and not any(fit["active_bounds"]) and all(c["passed"] for c in evaluated)
                  and swap_detected and zero_detected)
    sources = ("src/oeal/thermal_identification.py", "benchmarks/msl_identification_protocol.py",
               "benchmarks/msl_identification_simulator.py",
               "benchmarks/generate_msl_identification.py", "benchmarks/fit_msl_identification.py",
               "benchmarks/validate_msl_identification.py",
               "models/modelica/OEALMSLParametric.mo", "docs/msl-identification-contract.md")
    report = dict(passed=passed, fit=fit, ideal_fit=ideal, truth=truth_parameters,
                  parameter_relative_errors=relative.tolist(),
                  ideal_relative_errors=ideal_relative.tolist(), evaluated=evaluated,
                  zero_excitation_rejected=zero_detected, swapped_nodes_rejected=swap_detected,
                  swapped_fault=swap_reason, frozen_fit_sha256=frozen_hash,
                  generation=generation, evidence_level="model_simulated",
                  scope="full-observation synthetic identification; no physical calibration",
                  metadata=dict(commit=subprocess.check_output(
                      ["git", "rev-parse", "HEAD"], text=True).strip(),
                      source_sha256={p:hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                                     for p in sources},
                      build=json.loads((ROOT / "outputs/msl-parametric/build-provenance.json")
                                       .read_text())))
    (OUT / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("identification-summary: "+json.dumps(
        {k:v for k,v in report.items() if k != "evaluated"}), flush=True)
    assert passed, "fixed synthetic identification and unused-case prediction gates failed"


if __name__ == "__main__":
    main()
