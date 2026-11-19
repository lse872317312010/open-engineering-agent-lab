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



def load_source_manifest(path):
    """Require importer metadata without inferring unprovided source conventions."""
    with np.load(path, allow_pickle=False) as data:
        if "manifest_json" not in data or np.asarray(data["manifest_json"]).shape != ():
            raise ValueError(f"missing scalar importer manifest: {path}")
        manifest = json.loads(str(data["manifest_json"].item()))
    if not isinstance(manifest, dict) or manifest.get("format") != "oeal-magnetic-points-v1":
        raise ValueError("unsupported magnetic point manifest")
    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("magnetic point metadata is missing")
    for key in ("source_software", "source_version", "model_id", "phase_sequence", "domain"):
        if not isinstance(metadata.get(key), str) or not metadata[key].strip():
            raise ValueError(f"missing source metadata: {key}")
    if metadata.get("dq_convention") != "motulator_peak_d_plus_jq":
        raise ValueError("source dq convention is unsupported or unknown")
    poles = metadata.get("pole_pairs")
    if isinstance(poles, bool) or not isinstance(poles, int) or poles < 1:
        raise ValueError("source pole_pairs must be a positive integer")
    if "temperature_c" not in metadata:
        raise ValueError("source temperature must be specified or explicitly unknown")
    temperature = metadata["temperature_c"]
    if temperature is None:
        if (not isinstance(metadata.get("temperature_note"), str)
                or not metadata["temperature_note"].strip()):
            raise ValueError("unknown temperature requires a source note")
    elif (isinstance(temperature, bool) or not isinstance(temperature, (int, float))
          or not math.isfinite(temperature)):
        raise ValueError("source temperature must be finite or explicitly unknown")
    for key in ("source_csv_sha256", "metadata_sha256"):
        value = manifest.get(key)
        if (not isinstance(value, str) or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)):
            raise ValueError(f"missing or invalid recorded source hash: {key}")
    return manifest


def check_source_compatibility(train_manifest, validation_manifest, pole_pairs):
    train = train_manifest["metadata"]
    validation = validation_manifest["metadata"]
    for key in ("model_id", "pole_pairs", "temperature_c", "dq_convention", "phase_sequence"):
        if train[key] != validation[key]:
            raise ValueError(f"incompatible source metadata: {key}")
    if train["pole_pairs"] != pole_pairs:
        raise ValueError("nominal pole_pairs differs from source data")

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
    train_manifest = load_source_manifest(args.train)
    validation_manifest = load_source_manifest(args.validation)
    train = load_points(args.train)
    validation = load_points(args.validation)
    check_exact_separation(train, validation)
    cfg = json.loads(args.nominal.read_text(encoding="utf-8"))
    pole_pairs = cfg["pole_pairs"]
    if isinstance(pole_pairs, bool) or not isinstance(pole_pairs, int) or pole_pairs < 1:
        raise ValueError("pole_pairs must be a positive integer")
    check_source_compatibility(train_manifest, validation_manifest, pole_pairs)
    vals = {key: positive_number(cfg, key) for key in
            ("voltage_v", "current_a", "frequency_hz", "power_w", "torque_nm")}
    import matplotlib.pyplot as plt
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
    # Point-only plots avoid suggesting that unsampled areas are valid.
    valid_i, valid_psi = validation
    valid_flux_prediction = np.asarray(models["flux"](valid_i))
    valid_current_prediction = np.asarray(models["current"](valid_psi))
    np.savez_compressed(output / "validation-predictions.npz",
                        current_dq=valid_i, flux_dq=valid_psi,
                        predicted_current_dq=valid_current_prediction,
                        predicted_flux_dq=valid_flux_prediction)
    for name, inputs, target, predicted, input_unit, output_unit in (
        ("flux", valid_i, valid_psi, valid_flux_prediction, "A peak", "Wb"),
        ("current", valid_psi, valid_i, valid_current_prediction, "Wb", "A peak"),
    ):
        fig, axes = plt.subplots(2, 3, figsize=(13, 8), sharex=True, sharey=True)
        for row, (source, prediction, component) in enumerate((
            (target.real, predicted.real, "d"), (target.imag, predicted.imag, "q")
        )):
            lo = float(min(np.min(source), np.min(prediction)))
            hi = float(max(np.max(source), np.max(prediction)))
            panels = ((source, f"Source {component}", lo, hi),
                      (prediction, f"Predicted {component}", lo, hi),
                      (np.abs(prediction - source), f"Absolute {component} error", None, None))
            for ax, (colors, title, vmin, vmax) in zip(axes[row], panels, strict=True):
                scatter = ax.scatter(inputs.real, inputs.imag, c=colors, s=18, cmap="viridis",
                                     vmin=vmin, vmax=vmax)
                ax.set(title=title, xlabel=f"d input ({input_unit})")
                fig.colorbar(scatter, ax=ax, label=output_unit)
            axes[row, 0].set_ylabel(f"q input ({input_unit})")
        fig.suptitle(f"{name.capitalize()} map: validation points only")
        fig.tight_layout()
        fig.savefig(output / f"validation-{name}.png", dpi=160)
        plt.close(fig)
    # Differentiate only at validation points using the upstream GradNet Jacobian.
    incremental = np.asarray(models["flux"].jacobian(valid_i))
    if incremental.shape != (len(valid_i), 2, 2) or not np.isfinite(incremental).all():
        raise ValueError("upstream incremental inductance is nonfinite or has an unexpected shape")
    np.savez_compressed(output / "validation-inductance.npz",
                        current_dq=valid_i, incremental_h=incremental)
    fig, axes = plt.subplots(2, 2, figsize=(10, 8), sharex=True, sharey=True)
    for row in range(2):
        for col in range(2):
            ax = axes[row, col]
            scatter = ax.scatter(valid_i.real, valid_i.imag, c=incremental[:, row, col],
                                 s=18, cmap="viridis")
            component = ("d", "q")
            ax.set(title=f"L{component[row]}{component[col]}",
                   xlabel="d-axis current (A peak)", ylabel="q-axis current (A peak)")
            fig.colorbar(scatter, ax=ax, label="Incremental inductance (H)")
    fig.suptitle("Upstream GradNet Jacobian: validation points only")
    fig.tight_layout()
    fig.savefig(output / "validation-inductance.png", dpi=160)
    plt.close(fig)
    summary = {
        "input_sha256": {name: file_hash(path) for name, path in
                         (("train", args.train), ("validation", args.validation),
                          ("nominal", args.nominal))},
        "model_sha256": {name: file_hash(output / (name + "-model.npz")) for name in models},
        "versions": {name: version(name) for name in ("motulator", "motulator-gradnet",
                                                        "torch", "numpy", "scipy")},
        "nominal": cfg, "base_current_a": float(base.i), "base_flux_wb": float(base.psi),
        "source_manifests": {"train": train_manifest, "validation": validation_manifest},
        "epochs": args.epochs, "device": "cpu", "upstream_seed": 42, "results": results,
        "plots": ["validation-flux.png", "validation-current.png", "validation-inductance.png"],
        "jacobian_cross_asymmetry_max_h": float(
            np.max(np.abs(incremental[:, 0, 1] - incremental[:, 1, 0]))),
        "limitations": [
            "validation is used for evaluation and is not a protected final holdout",
            "exact input and q-reflection checks do not detect near-duplicates or spatial leakage",
            "source metadata and hashes are user declarations, not authenticated measurements",
            "input physical domain and source provenance must be verified independently",
            "Jacobian is model-derived and not validated against source differential inductance",
            "no torque, loss, extrapolation safety, physical validation, or drive simulation",
        ],
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
