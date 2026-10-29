"""Unused MSL holdout evaluation after all training-only fits are frozen."""
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
from msl_identification_protocol import NODES, SPLITS, physical_vector, truth
from validate_msl_identification import physical, reference

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/msl-identification"
OUT = ROOT / "outputs/msl-identification-robustness"


def main():
    manifest = json.loads((OUT / "packets.json").read_text())
    frozen = json.loads((OUT / "frozen-fits.json").read_text())
    assert [s["id"] for s in manifest["cases"]] == [s["id"] for s in frozen]
    holdout = SPLITS[2]
    clean_path = SOURCE / "holdout/trajectory.csv"
    clean = np.loadtxt(clean_path, delimiter=",", skiprows=1)
    expected = physical_vector(truth())
    cases = []
    for spec, frozen_case in zip(manifest["cases"], frozen, strict=True):
        fit_path = OUT / "fits" / (spec["id"]+".json")
        before = hashlib.sha256(fit_path.read_bytes()).hexdigest()
        assert before == frozen_case["frozen_fit_sha256"]
        fitted = json.loads(fit_path.read_text())
        result = dict(**spec, solver_succeeded=fitted["solver_succeeded"],
                      frozen_fit_sha256=before, suitable=False, quality=fitted["quality"])
        if not fitted["solver_succeeded"]:
            result["error"] = fitted["error"]
        else:
            fit = fitted["fit"]
            predicted = reference(holdout, physical(fit))
            assert predicted.shape == (len(clean), 10) and np.all(np.isfinite(predicted))
            delta = predicted[:, :6]-clean[:, 1:7]
            relative = abs(physical_vector(fit)/expected-1)
            rmse = np.sqrt(np.mean(delta**2, axis=0))
            peak = float(np.max(abs(delta)))
            suitable = bool(max(relative) <= .1 and max(rmse) <= .5 and peak <= 1.5
                            and not any(fit["active_bounds"]))
            filename = "prediction-"+spec["id"]+".csv"
            full = np.column_stack([clean[:, 0], predicted[:, :6], clean[:, 1:7],
                                    clean[:, 11:17]])
            np.savetxt(OUT / filename, full, delimiter=",", comments="",
                       header="time_s,"+",".join(
                           [n+"_c" for n in NODES]+["truth_"+n+"_c" for n in NODES]
                           +["power_"+n+"_w" for n in NODES]))
            indices = sorted(set(range(0, len(full), 25)) | {len(full)-1})
            result.update(fit=fit, suitable=suitable, parameters=physical_vector(fit).tolist(),
                          parameter_relative_errors=relative.tolist(),
                          max_parameter_relative_error=float(max(relative)),
                          rmse_by_node_k=rmse.tolist(), peak_error_k=peak,
                          total_rmse_k=float(np.sqrt(np.mean(delta**2))),
                          prediction_csv=filename, prediction_rows=len(full),
                          samples=full[indices].tolist())
        assert before == hashlib.sha256(fit_path.read_bytes()).hexdigest()
        cases.append(result)
        print("robustness-evaluation: "+json.dumps(
            {k:v for k,v in result.items() if k != "samples"}), flush=True)
    indexed = {c["id"]:c for c in cases}
    # Alternate solver is selected explicitly without changing the frozen Radau implementation.
    # It reproduces the same independent equations with a distinct integration algorithm.
    from msl_identification_protocol import AREA, GC, inputs
    from msl_rc_reference import rates
    from scipy.integrate import solve_ivp
    ideal = indexed["ideal"]
    parameters = physical(ideal["fit"])
    commands = inputs(holdout)
    changes = np.flatnonzero(np.any(np.diff(commands[:-1], axis=0), axis=1))+1
    edges = [0, *changes.tolist(), len(commands)-1]
    state = np.asarray(holdout["initial_c"], dtype=float)
    values = [state.copy()]
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        power = commands[a].copy()

        def rhs(t, x, held=power):
            return rates(x, held, GC, AREA, holdout["ambient_c"],
                         parameters["capacities_j_per_k"],
                         parameters["link_resistances_k_per_w"],
                         parameters["case_resistance_k_per_w"])[0, :6]

        times = clean[a+1:b+1, 0]
        solution = solve_ivp(rhs, (clean[a, 0], clean[b, 0]), state, method="DOP853",
                             rtol=1e-11, atol=1e-11, dense_output=True)
        assert solution.success
        values.extend(solution.sol(times).T)
        state = solution.y[:, -1]
    radau = np.loadtxt(OUT / ideal["prediction_csv"], delimiter=",", skiprows=1)[:, 1:7]
    numerical = float(np.max(abs(np.asarray(values)-radau)))
    required = ["ideal", *[f"noise-0.02-{i}" for i in range(1, 5)]]
    checks = dict(twenty_cases=len(cases) == 20,
                  clean_and_low_noise=all(indexed[n]["suitable"] for n in required),
                  missing_channel_rejected=not indexed["missing-core"]["solver_succeeded"],
                  no_excitation_rejected=not indexed["equilibrium"]["solver_succeeded"],
                  power_scale_not_certified=not indexed["power-half"]["suitable"],
                  numerical_solver_agreement=numerical <= 2e-6,
                  all_predictions_complete=all(c.get("prediction_rows") == len(clean)
                                              for c in cases if c["solver_succeeded"]))
    quality_checks = dict(
        all_cases_have_quality=all("quality" in c for c in cases),
        equilibria_insufficient=all(indexed[n]["quality"]["status"] == "insufficient"
                                   for n in ("equilibrium", "equilibrium-noisy")),
        missing_core_invalid=indexed["missing-core"]["quality"]["status"] == "invalid",
        low_noise_supported=all(indexed[n]["quality"]["status"] == "amplitude_supported"
                                for n in required),
        missing_prior_unknown=all(c["quality"]["without_noise_prior_status"] == "unknown"
                                 for c in cases if c["quality"]["status"] != "invalid"))
    checks.update(quality_checks)
    report = dict(passed=all(checks.values()), checks=checks, cases=cases,
                  numerical_temperature_difference_k=numerical,
                  holdout=holdout, truth=truth(), truth_parameters=expected.tolist(),
                  evidence_level="model_simulated",
                  prediction_backend="segmented Radau against actual MSL holdout",
                  scope="full observation, known-source synthetic stress study; not fault detector",
                  source_holdout_sha256=hashlib.sha256(
                      clean_path.read_bytes()).hexdigest(),
                  commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
    (OUT / "evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("robustness-summary: "+json.dumps({k:v for k,v in report.items() if k != "cases"}),
          flush=True)
    assert report["passed"], checks


if __name__ == "__main__":
    main()
