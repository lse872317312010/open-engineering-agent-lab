"""Train upstream GradNet magnetic maps from explicitly separated NPZ datasets."""
import argparse
import hashlib
import json
import math
from importlib.metadata import version
from pathlib import Path

import numpy as np


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_points(path):
    with np.load(path, allow_pickle=False) as data:
        current = np.asarray(data["i_s_dq"]).flatten()
        flux = np.asarray(data["psi_s_dq"]).flatten()
    if (current.shape != flux.shape or current.size < 4
            or not np.isfinite(current).all() or not np.isfinite(flux).all()):
        raise ValueError(f"invalid or insufficient point pairs: {path}")
    if not np.iscomplexobj(current) or not np.iscomplexobj(flux):
        raise ValueError("i_s_dq and psi_s_dq must be complex d + j*q arrays")
    return current, flux


def check_exact_separation(train, validation):
    """Reject exact and q-reflected duplicate current or flux inputs across splits."""
    for index, label in ((0, "current"), (1, "flux")):
        def canonical(values):
            return set(zip(values.real.tolist(), np.abs(values.imag).tolist(), strict=True))
        overlap = canonical(train[index]) & canonical(validation[index])
        if overlap:
            raise ValueError(f"{label} input overlaps across splits, including q reflection")


def positive_number(config, key):
    value = config[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{key} must be finite and positive")
    return float(value)


def evaluate(target, prediction):
    error = np.abs(np.asarray(prediction) - target)
    if error.shape != target.shape or not np.isfinite(error).all():
        raise ValueError("invalid map prediction")
    return {"rmse": float(np.sqrt(np.mean(error**2))),
            "p95": float(np.percentile(error, 95)), "max": float(np.max(error))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--nominal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=2000)
    args = parser.parse_args()
    if args.epochs <= 0:
        parser.error("--epochs must be positive")
    input_paths = [args.train, args.validation, args.nominal]
    if len({p.resolve() for p in input_paths}) != 3:
        raise ValueError("training, validation and nominal inputs must be different files")
    output = args.output
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    train = load_points(args.train)
    validation = load_points(args.validation)
    check_exact_separation(train, validation)
    cfg = json.loads(args.nominal.read_text(encoding="utf-8"))
    pole_pairs = cfg["pole_pairs"]
    if isinstance(pole_pairs, bool) or not isinstance(pole_pairs, int) or pole_pairs < 1:
        raise ValueError("pole_pairs must be a positive integer")
    vals = {key: positive_number(cfg, key) for key in
            ("voltage_v", "current_a", "frequency_hz", "power_w", "torque_nm")}
    import motulator.drive.gradnet as gn
    import torch
    from motulator.drive import utils
    from motulator_gradnet import train_gradnet

    nominal = utils.NominalValues(U=vals["voltage_v"], I=vals["current_a"],
                                  f=vals["frequency_hz"], P=vals["power_w"],
                                  tau=vals["torque_nm"])
    base = utils.BaseValues.from_nominal(nominal, n_p=pole_pairs)
    models = {}
    for is_flux, name in ((True, "flux"), (False, "current")):
        path = output / (name + "-model.npz")
        train_gradnet(dataset_path=args.train, base=base, is_flux_map=is_flux,
                      epochs=args.epochs, save_model_path=path, device=torch.device("cpu"))
        loaded = gn.load_gradnet(path)
        models[name] = gn.FluxMap(loaded) if is_flux else gn.CurrentMap(loaded)
    results = {}
    for label, (current, flux) in (("training", train), ("validation", validation)):
        flux_error = evaluate(flux, models["flux"](current))
        current_error = evaluate(current, models["current"](flux))
        results[label] = {"points": len(current), "flux_error_wb": flux_error,
                          "current_error_a": current_error,
                          "flux_rmse_pu": flux_error["rmse"] / float(base.psi),
                          "current_rmse_pu": current_error["rmse"] / float(base.i)}
    summary = {
        "input_sha256": {name: file_hash(path) for name, path in
                         (("train", args.train), ("validation", args.validation),
                          ("nominal", args.nominal))},
        "model_sha256": {name: file_hash(output / (name + "-model.npz")) for name in models},
        "versions": {name: version(name) for name in ("motulator", "motulator-gradnet",
                                                        "torch", "numpy", "scipy")},
        "nominal": cfg, "base_current_a": float(base.i), "base_flux_wb": float(base.psi),
        "epochs": args.epochs, "device": "cpu", "upstream_seed": 42, "results": results,
        "limitations": [
            "validation is used for evaluation and is not a protected final holdout",
            "exact input and q-reflection checks do not detect near-duplicates or spatial leakage",
            "input units, dq convention, physical domain and provenance must be supplied by user",
            "no torque, loss, extrapolation safety, physical validation, or drive simulation",
        ],
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
