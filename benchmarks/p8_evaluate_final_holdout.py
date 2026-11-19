"""Evaluate fitted upstream magnetic maps on a separately provided final holdout."""
import argparse
import hashlib
import json
import math
from importlib.metadata import version
from pathlib import Path

import numpy as np
from p8_fit_external import check_exact_separation, evaluate, load_points, positive_number


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
    train, validation, holdout = (load_points(path) for path in paths)
    for left, right in ((train, validation), (train, holdout), (validation, holdout)):
        check_exact_separation(left, right)
    return fit, model_paths, holdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--budget", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("output directory must be empty")
    _, models, (current, flux) = verify_inputs(
        args.fit_dir, args.train, args.validation, args.holdout
    )
    cfg = json.loads(args.budget.read_text(encoding="utf-8"))
    keys = ("flux_rmse_wb", "flux_max_wb", "current_rmse_a", "current_max_a")
    limits = {key: positive_number(cfg, key) for key in keys}
    import matplotlib.pyplot as plt
    import motulator.drive.gradnet as gn

    flux_map = gn.FluxMap(gn.load_gradnet(models["flux"]))
    current_map = gn.CurrentMap(gn.load_gradnet(models["current"]))
    predicted_flux = np.asarray(flux_map(current))
    predicted_current = np.asarray(current_map(flux))
    flux_error = evaluate(flux, predicted_flux)
    current_error = evaluate(current, predicted_current)
    observed = {"flux_rmse_wb": flux_error["rmse"], "flux_max_wb": flux_error["max"],
                "current_rmse_a": current_error["rmse"], "current_max_a": current_error["max"]}
    if not all(math.isfinite(x) for x in observed.values()):
        raise ValueError("nonfinite holdout result")
    decisions = {key: observed[key] <= limits[key] for key in keys}
    args.output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output / "holdout-predictions.npz", current_dq=current, flux_dq=flux,
                        predicted_current_dq=predicted_current, predicted_flux_dq=predicted_flux)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharex=True, sharey=True)
    for ax, errors, title, unit in (
        (axes[0], np.abs(predicted_flux - flux), "Flux vector error", "Wb"),
        (axes[1], np.abs(predicted_current - current), "Current vector error", "A peak"),
    ):
        plot = ax.scatter(current.real, current.imag, c=errors, s=22, cmap="viridis")
        ax.set(title=title, xlabel="d-axis current (A peak)")
        fig.colorbar(plot, ax=ax, label=unit)
    axes[0].set_ylabel("q-axis current (A peak)")
    fig.suptitle("Final holdout: supplied points only")
    fig.tight_layout()
    fig.savefig(args.output / "holdout-error.png", dpi=160)
    plt.close(fig)
    report = {
        "fit_summary_sha256": digest(args.fit_dir / "summary.json"),
        "input_sha256": {"train": digest(args.train), "validation": digest(args.validation),
                         "holdout": digest(args.holdout), "budget": digest(args.budget)},
        "model_sha256": {name: digest(path) for name, path in models.items()},
        "versions": {name: version(name) for name in ("motulator", "numpy", "scipy")},
        "points": int(len(current)), "errors": {"flux_wb": flux_error,
                                                 "current_a": current_error},
        "budgets": limits, "checks": decisions, "passed": all(decisions.values()),
        "limitations": [
            "separation checks reject exact and q-reflected duplicates only",
            "user must predeclare budgets and establish independence and physical provenance",
            "point errors do not certify continuous domain, torque, losses or solver stages",
        ],
    }
    (args.output / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit("one or more declared holdout error budgets failed")


if __name__ == "__main__":
    main()
