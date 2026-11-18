"""Exercise open CSV import and upstream GradNet on a fixed spatial holdout."""
import csv
import hashlib
import json
from importlib.metadata import version
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import motulator.drive.gradnet as gn  # noqa: E402
from import_magnetic_points import convert  # noqa: E402
from motulator.drive import utils  # noqa: E402
from motulator_gradnet import train_gradnet  # noqa: E402


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source = Path("upstream-gradnet/examples/datasets/baldor_meas.npz")
    out = Path("outputs/p8-gradnet-extended")
    out.mkdir(parents=True, exist_ok=True)
    with np.load(source, allow_pickle=False) as data:
        current = np.asarray(data["i_s_dq"]).flatten()
        flux = np.asarray(data["psi_s_dq"]).flatten()
    if current.shape != flux.shape or not (np.isfinite(current).all() and np.isfinite(flux).all()):
        raise ValueError("upstream dataset contains inconsistent or nonfinite points")
    csv_path = out / "source.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("id_A", "iq_A", "psi_d_Wb", "psi_q_Wb"))
        writer.writerows(zip(current.real, current.imag, flux.real, flux.imag, strict=True))
    metadata = {
        "source_software": "motulator-gradnet measured example",
        "source_version": "940d3b2daf3abd3ecca157f93cf4cc5363f5bb80",
        "model_id": "Baldor ECS101M0H7EF4",
        "pole_pairs": 2,
        "temperature_c": None,
        "temperature_note": "unknown in upstream example",
        "dq_convention": "motulator_peak_d_plus_jq",
        "phase_sequence": "unspecified in upstream example",
        "domain": "upstream measured point set; no interpolation domain asserted",
    }
    meta_path = out / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    imported = out / "imported.npz"
    convert(csv_path, meta_path, imported)
    with np.load(imported, allow_pickle=False) as data:
        i = data["i_s_dq"]
        psi = data["psi_s_dq"]
    np.testing.assert_array_equal(i, current)
    np.testing.assert_array_equal(psi, flux)

    # Freeze disjoint regions before fitting either model. This is a new experiment.
    validation = (i.real >= -4.0) & (i.real <= 4.0)
    final = (~validation) & (np.abs(i.imag) >= 16.0)
    train = ~(validation | final)
    if min(np.count_nonzero(mask) for mask in (train, validation, final)) < 10:
        raise ValueError("predeclared partition has too few points")
    train_path = out / "train.npz"
    holdout_path = out / "holdout.npz"
    np.savez_compressed(train_path, i_s_dq=i[train], psi_s_dq=psi[train])
    np.savez_compressed(holdout_path, i_s_dq=i[final], psi_s_dq=psi[final])
    validation_path = out / "validation.npz"
    np.savez_compressed(validation_path, i_s_dq=i[validation], psi_s_dq=psi[validation])
    nominal = utils.NominalValues(U=460, I=8.8, f=60, P=5.6e3, tau=29.7)
    base = utils.BaseValues.from_nominal(nominal, n_p=2)
    models = {}
    for is_flux, name in ((True, "flux"), (False, "current")):
        path = out / (name + "-model.npz")
        train_gradnet(dataset_path=train_path, base=base, save_model_path=path,
                      is_flux_map=is_flux, epochs=2000, device=None)
        model = gn.load_gradnet(path)
        models[name] = gn.FluxMap(model) if is_flux else gn.CurrentMap(model)

    def metrics(target, predicted):
        error = np.abs(np.asarray(predicted) - target)
        if not np.isfinite(error).all():
            raise ValueError("nonfinite prediction")
        return {"rmse": float(np.sqrt(np.mean(error**2))),
                "p95": float(np.percentile(error, 95)), "max": float(np.max(error))}
    results = {}
    for label, mask in (("training", train), ("validation", validation), ("final_holdout", final)):
        results[label] = {
            "points": int(np.count_nonzero(mask)),
            "flux_error_wb": metrics(psi[mask], models["flux"](i[mask])),
            "current_error_a": metrics(i[mask], models["current"](psi[mask])),
        }
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(i.real[train], i.imag[train], s=8, label="Training")
    ax.scatter(i.real[validation], i.imag[validation], s=8, label="Validation")
    ax.scatter(i.real[final], i.imag[final], s=8, label="Final holdout")
    ax.set(xlabel="d-axis current (A peak)", ylabel="q-axis current (A peak)",
           title="Frozen spatial partition of upstream measured data")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "partition.png", dpi=160)
    plt.close(fig)
    report = {
        "source_npz_sha256": sha(source), "csv_sha256": sha(csv_path),
        "imported_sha256": sha(imported), "training_sha256": sha(train_path),
        "holdout_sha256": sha(holdout_path), "validation_sha256": sha(validation_path),
        "model_sha256": {name: sha(out / (name + "-model.npz")) for name in models},
        "versions": {name: version(name) for name in ("motulator", "motulator-gradnet", "torch",
                                                        "numpy", "scipy")},
        "split": ("validation -4 <= id <= 4 A; final |iq| >= 16 A outside validation; "
                  "remainder train"),
        "training": "upstream train_gradnet, 2000 epochs each, default seed and parameters",
        "results": results,
        "limitations": [
            "single fixed split; no predeclared numerical acceptance thresholds",
            "the previous experiment trained on points in the new final region",
            "upstream symmetrizes q; both q signs are held out together",
            "temperature and phase sequence not supplied by upstream example",
            "same source dataset: not independent physical validation",
            "no domain safety, torque, controller simulation, or optimization evaluation",
        ],
    }
    (out / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
