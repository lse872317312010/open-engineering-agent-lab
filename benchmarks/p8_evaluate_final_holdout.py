"""Evaluate fitted upstream magnetic maps on a separately provided final holdout."""
import argparse
import hashlib
import json
import math
import os
import platform
from importlib.metadata import version
from pathlib import Path
from time import perf_counter_ns

import numpy as np
from p8_fit_external import (
    check_exact_separation,
    check_source_compatibility,
    evaluate,
    load_points,
    load_source_manifest,
    positive_number,
)

HOLDOUT_METRICS = {
    "flux_rmse_wb": ("flux_wb", "rmse"),
    "flux_max_wb": ("flux_wb", "max"),
    "current_rmse_a": ("current_a", "rmse"),
    "current_max_a": ("current_a", "max"),
}
TIMING_WARMUP_PASSES = 3
TIMING_ROUNDS = 15
TIMING_PASSES_PER_ROUND = 5


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_inputs(fit_dir, train_path, validation_path, holdout_path):
    """Verify fit inputs and exact or q-reflected separation across all three sets."""
    paths = (train_path, validation_path, holdout_path)
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("training, validation and holdout must be different files")
    fit = json.loads((fit_dir / "summary.json").read_text(encoding="utf-8"))
    for label, path in (("train", train_path), ("validation", validation_path)):
        if digest(path) != fit["input_sha256"][label]:
            raise ValueError(f"{label} file does not match fit summary")
    model_paths = {name: fit_dir / (name + "-model.npz") for name in ("flux", "current")}
    for name, path in model_paths.items():
        if digest(path) != fit["model_sha256"][name]:
            raise ValueError(f"{name} model does not match fit summary")
    train_manifest, validation_manifest, holdout_manifest = (
        load_source_manifest(path) for path in paths
    )
    pole_pairs = fit["nominal"]["pole_pairs"]
    check_source_compatibility(train_manifest, validation_manifest, pole_pairs)
    check_source_compatibility(train_manifest, holdout_manifest, pole_pairs)
    if fit.get("source_manifests") != {"train": train_manifest, "validation": validation_manifest}:
        raise ValueError("fit source manifests do not match the input files")
    train, validation, holdout = (load_points(path) for path in paths)
    for left, right in ((train, validation), (train, holdout), (validation, holdout)):
        check_exact_separation(left, right)
    return fit, model_paths, train, holdout, holdout_manifest


def time_holdout_inference(gradnet, linear, inputs):
    """Measure repeated passes over one shared set of supported API inputs."""
    result = {}
    methods = [("gradnet", gradnet), ("linear", linear)]
    for workload, calls in (("scalar", tuple(inputs)), ("batch", (inputs,))):
        for _, evaluate_map in methods:
            for _ in range(TIMING_WARMUP_PASSES):
                for dq in calls:
                    evaluate_map(dq)
        samples = {name: [] for name, _ in methods}
        for index in range(TIMING_ROUNDS):
            ordered_methods = methods if index % 2 == 0 else reversed(methods)
            for name, evaluate_map in ordered_methods:
                start = perf_counter_ns()
                for _ in range(TIMING_PASSES_PER_ROUND):
                    for dq in calls:
                        evaluate_map(dq)
                elapsed = perf_counter_ns() - start
                samples[name].append(elapsed / (len(calls) * TIMING_PASSES_PER_ROUND))
        result[workload] = {
            "calls_per_pass": len(calls), "points_per_call": len(inputs) // len(calls),
            "methods": {
                name: {"median_ns_per_call": float(np.median(values)),
                       "p95_ns_per_call": float(np.percentile(values, 95)),
                       "round_mean_ns_per_call": values}
                for name, values in samples.items()
            },
        }
    return result


def compare_training_coverage(
    train_input, train_target, holdout_input, target, predicted, base, *, timed_map=None
):
    """Compare GradNet with linear interpolation where the training geometry supports it."""
    from scipy.interpolate import LinearNDInterpolator
    from scipy.spatial import Delaunay, QhullError

    coverage = np.full(target.shape, "unavailable", dtype="<U11")
    linear = np.full(target.shape, complex(np.nan, np.nan))
    _, first, inverse = np.unique(train_input, return_index=True, return_inverse=True)
    unique_rows = np.sort(first)
    train_xy = np.column_stack((train_input.real, train_input.imag))[unique_rows]
    holdout_xy = np.column_stack((holdout_input.real, holdout_input.imag))
    geometry_reason = linear_reason = None

    def linear_map(dq):
        return interpolate(dq.real, dq.imag)

    try:
        triangulation = Delaunay(train_xy)
    except QhullError:
        geometry_reason = linear_reason = "training_inputs_do_not_support_2d_triangulation"
    else:
        inside = triangulation.find_simplex(holdout_xy) >= 0
        coverage[:] = np.where(inside, "inside", "outside")
        if not np.array_equal(train_target, train_target[first[inverse]]):
            linear_reason = "conflicting_targets_at_duplicate_training_inputs"
        elif inside.any():
            try:
                interpolate = LinearNDInterpolator(triangulation, train_target[unique_rows])
                linear[inside] = linear_map(holdout_input[inside])
            except QhullError:
                linear_reason = "scipy_interpolation_triangulation_failed"

    def metrics(mask, values):
        if not mask.any():
            return None
        actual, estimate = target[mask], values[mask]
        errors = evaluate(actual, estimate)
        errors["mae"] = float(np.mean(np.abs(estimate - actual)))
        errors["rmse_pu"] = errors["rmse"] / base
        return errors

    groups = {}
    for label in ("inside", "outside", "unavailable"):
        mask = coverage == label
        groups[label] = {"points": int(mask.sum()), "gradnet_errors": metrics(mask, predicted)}
    comparable = (coverage == "inside") & np.isfinite(linear)
    report = {
        "unavailable_reason": geometry_reason,
        "coverage": groups,
        "linear_comparison": {
            "points": int(comparable.sum()), "unavailable_reason": linear_reason,
            "linear_errors": metrics(comparable, linear),
            "gradnet_same_points": metrics(comparable, predicted),
        },
    }
    if timed_map is not None:
        report["inference_timing"] = (
            time_holdout_inference(timed_map, linear_map, holdout_input[comparable])
            if comparable.any() else None
        )
    return report, coverage, linear


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--budget", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--benchmark-inference", action="store_true",
                        help="time warmed GradNet and linear calls on identical supported points")
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("output directory must be empty")
    fit, models, (train_current, train_flux), (current, flux), holdout_manifest = verify_inputs(
        args.fit_dir, args.train, args.validation, args.holdout
    )
    cfg = json.loads(args.budget.read_text(encoding="utf-8"))
    limits = {key: positive_number(cfg, key) for key in HOLDOUT_METRICS}
    import matplotlib.pyplot as plt
    import motulator.drive.gradnet as gn

    flux_map = gn.FluxMap(gn.load_gradnet(models["flux"]))
    current_map = gn.CurrentMap(gn.load_gradnet(models["current"]))
    predicted_flux = np.asarray(flux_map(current))
    predicted_current = np.asarray(current_map(flux))
    errors = {
        "flux_wb": evaluate(flux, predicted_flux),
        "current_a": evaluate(current, predicted_current),
    }
    observed = {
        key: errors[quantity][metric] for key, (quantity, metric) in HOLDOUT_METRICS.items()
    }
    if not all(math.isfinite(x) for x in observed.values()):
        raise ValueError("nonfinite holdout result")
    decisions = {key: value <= limits[key] for key, value in observed.items()}
    base_current = positive_number(fit, "base_current_a")
    base_flux = positive_number(fit, "base_flux_wb")
    flux_coverage, flux_labels, linear_flux = compare_training_coverage(
        train_current, train_flux, current, flux, predicted_flux, base_flux,
        timed_map=flux_map if args.benchmark_inference else None,
    )
    current_coverage, current_labels, linear_current = compare_training_coverage(
        train_flux, train_current, flux, current, predicted_current, base_current,
        timed_map=current_map if args.benchmark_inference else None,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    predictions_path = args.output / "holdout-predictions.npz"
    np.savez_compressed(
        predictions_path, current_dq=current, flux_dq=flux,
        predicted_current_dq=predicted_current, predicted_flux_dq=predicted_flux,
        flux_map_input_coverage=flux_labels, current_map_input_coverage=current_labels,
        linear_current_dq=linear_current, linear_flux_dq=linear_flux,
    )
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for ax, inputs, labels, point_errors, title, input_unit, output_unit in (
        (axes[0], current, flux_labels, np.abs(predicted_flux - flux),
         "Flux vector error", "A peak", "Wb"),
        (axes[1], flux, current_labels, np.abs(predicted_current - current),
         "Current vector error", "Wb", "A peak"),
    ):
        plot = ax.scatter(inputs.real, inputs.imag, c=point_errors, s=22, cmap="viridis")
        for label, marker, legend in (("outside", "o", "Outside training hull"),
                                      ("unavailable", "s", "Coverage unavailable")):
            mask = labels == label
            if mask.any():
                ax.scatter(inputs.real[mask], inputs.imag[mask], s=60, marker=marker,
                           facecolors="none", edgecolors="black", label=legend)
        if np.any(labels != "inside"):
            ax.legend()
        ax.set(title=title, xlabel=f"d-axis input ({input_unit})",
               ylabel=f"q-axis input ({input_unit})")
        fig.colorbar(plot, ax=ax, label=output_unit)
    fig.suptitle("Final holdout GradNet errors and training coverage")
    fig.tight_layout()
    fig.savefig(args.output / "holdout-error.png", dpi=160)
    plt.close(fig)
    report = {
        "fit_summary_sha256": digest(args.fit_dir / "summary.json"),
        "input_sha256": {"train": digest(args.train), "validation": digest(args.validation),
                         "holdout": digest(args.holdout), "budget": digest(args.budget)},
        "model_sha256": {name: digest(path) for name, path in models.items()},
        "predictions_sha256": digest(predictions_path),
        "versions": {name: version(name) for name in ("motulator", "numpy", "scipy")},
        "points": int(len(current)), "source_manifests": fit["source_manifests"],
        "holdout_source_manifest": holdout_manifest,
        "errors": errors,
        "training_coverage": {"flux_wb": flux_coverage, "current_a": current_coverage},
        "base_current_a": base_current, "base_flux_wb": base_flux,
        "flux_rmse_pu": observed["flux_rmse_wb"] / base_flux,
        "current_rmse_pu": observed["current_rmse_a"] / base_current,
        "budgets": limits, "checks": decisions, "passed": all(decisions.values()),
        "limitations": [
            "separation checks reject exact and q-reflected duplicates only",
            "source checks compare user-declared metadata",
            "user must predeclare budgets and establish independence and physical provenance",
            "training hulls describe geometric coverage and may contain unsampled regions",
            "point errors do not certify continuous domain, torque, losses or solver stages",
        ],
    }
    if args.benchmark_inference:
        report["inference_benchmark"] = {
            "clock": "perf_counter_ns", "warmup_passes": TIMING_WARMUP_PASSES,
            "rounds": TIMING_ROUNDS, "passes_per_round": TIMING_PASSES_PER_ROUND,
            "host": {"platform": platform.platform(), "cpu_count": os.cpu_count(),
                     "python": platform.python_version()},
            "thread_environment": {key: os.environ.get(key) for key in (
                "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS",
            )},
            "scope": "warmed API calls and loop overhead; excludes training and map setup",
        }
    (args.output / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit("one or more declared holdout error budgets failed")


if __name__ == "__main__":
    main()
