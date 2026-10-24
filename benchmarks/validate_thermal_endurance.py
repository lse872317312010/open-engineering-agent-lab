"""One-hour synthetic thermal endurance; independent ODE and energy accounting."""

import hashlib
import json
import os
import platform
from pathlib import Path

import numpy as np
import scipy
from scipy.integrate import simpson, solve_ivp

from oeal.refined_thermal import CAPACITIES, ThermalNetwork

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/thermal-endurance"
TEMPERATURE_LIMIT_K = 2e-7
ENERGY_LIMIT_J = 0.5
# Fixed scenarios, never optimized using these acceptance results.
BLOCKS = (
    (600, (40, 5, 0, 15, 0, 0)),
    (1200, (10, 2, 0, 3, 0, 0)),
    (600, (60, 8, 0, 20, 0, 0)),
    (1200, (0, 0, 0, 0, 0, 0)),
)


def reference(ambient):
    """Independent physical port equations, with integrated heat to ambient."""
    capacities = np.array([60, 70, 200, 0.5, 25, 100], dtype=float)
    state = np.r_[np.full(6, ambient), 0.0]
    endpoints = []
    for duration, powers in BLOCKS:
        def rhs(_time, y, powers=powers):
            heat = np.array(powers, dtype=float)
            for a, b, resistance in (
                (0, 1, 0.6), (1, 2, 0.4), (2, 4, 2), (3, 4, 0.8), (4, 5, 1.2)
            ):
                flow = (y[a] - y[b]) / resistance
                heat[a] -= flow
                heat[b] += flow
            rejected = (y[2] - ambient) / 2 + (y[5] - ambient) / 3
            heat[2] -= (y[2] - ambient) / 2
            heat[5] -= (y[5] - ambient) / 3
            return np.r_[heat / capacities, rejected]

        solution = solve_ivp(rhs, (0, duration), state, method="DOP853",
                             rtol=1e-11, atol=1e-11)
        if not solution.success:
            raise AssertionError(solution.message)
        state = solution.y[:, -1]
        endpoints.append(state.copy())
    return np.array(endpoints)


def run_case(ambient, period):
    network = ThermalNetwork(period_s=period, ambient_c=ambient)
    source_j, rejected_j, elapsed = 0.0, 0.0, 0.0
    rows = [[0.0, *network.temperatures, 0.0, 0.0]]
    endpoints = []
    for duration, powers in BLOCKS:
        rejected = [(network.temperatures[2] - ambient) / 2
                    + (network.temperatures[5] - ambient) / 3]
        count = round(duration / period)
        if count % 2 or count * period != duration:
            raise ValueError("blocks require an even number of exact sample intervals")
        for _ in range(count):
            temperatures = network.advance(powers)
            rejected.append((temperatures[2] - ambient) / 2
                            + (temperatures[5] - ambient) / 3)
            elapsed += period
            rows.append([elapsed, *temperatures, sum(powers), rejected[-1]])
        source_j += duration * sum(powers)
        rejected_j += float(simpson(rejected, dx=period))
        endpoints.append(network.temperatures.copy())
    stored_j = float(CAPACITIES @ (network.temperatures - ambient))
    residual = source_j - rejected_j - stored_j
    return np.array(rows), np.array(endpoints), {
        "source_j": source_j, "ambient_j": rejected_j, "stored_j": stored_j,
        "sampled_energy_residual_j": residual,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    reports = []
    for ambient in (-10.0, 25.0, 60.0):
        expected = reference(ambient)
        for period in (1.0, 0.5):
            rows, endpoints, metrics = run_case(ambient, period)
            error = float(np.max(np.abs(endpoints - expected[:, :6])))
            reference_residual = (metrics["source_j"] - expected[-1, 6]
                                  - float(CAPACITIES @ (expected[-1, :6] - ambient)))
            passed = (np.all(np.isfinite(rows)) and error <= TEMPERATURE_LIMIT_K
                      and abs(metrics["sampled_energy_residual_j"]) <= ENERGY_LIMIT_J
                      and abs(reference_residual) <= 1e-5
                      and np.min(rows[:, 1:7]) >= ambient - 1e-9)
            name = f"ambient-{ambient:g}-step-{period:g}"
            path = OUT / (name + ".csv")
            np.savetxt(path, rows, delimiter=",", header=(
                "time_s,winding_c,core_c,case_c,junction_c,board_c,sink_c,"
                "held_input_w,ambient_w"), comments="")
            reports.append({"id": name, "ambient_c": ambient, "period_s": period,
                            "passed": bool(passed), "endpoint_error_k": error,
                            "reference_energy_residual_j": reference_residual,
                            "csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            **metrics})
    # Corrupt only the accounting copy; acceptance must catch a missing 10 J.
    negative_detected = all(
        abs(case["sampled_energy_residual_j"] - 10) > ENERGY_LIMIT_J for case in reports
    )
    report = {
        "passed": all(case["passed"] for case in reports) and negative_detected,
        "evidence_level": "model_simulated", "duration_s": 3600,
        "source_commit": os.environ.get("GITHUB_SHA", "unrecorded"),
        "command": "python benchmarks/validate_thermal_endurance.py",
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (Path(__file__), ROOT / "src/oeal/refined_thermal.py")},
        "versions": {"python": platform.python_version(), "numpy": np.__version__,
                     "scipy": scipy.__version__},
        "blocks": BLOCKS, "temperature_limit_k": TEMPERATURE_LIMIT_K,
        "sampled_energy_limit_j": ENERGY_LIMIT_J,
        "negative_ledger_fault_detected": negative_detected, "cases": reports,
        "limits": ["synthetic fixed RC parameters, constant ambient per scenario",
                   "prescribed loss replay, not coupled one-hour motor/robot simulation",
                   "no physical temperature rating or calibration claim",
                   "energy quadrature is checked separately from endpoint temperature"],
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise AssertionError("thermal endurance fixed gate failed")


if __name__ == "__main__":
    main()
