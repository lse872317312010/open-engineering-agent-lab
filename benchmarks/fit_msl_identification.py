"""Noisy fitting process: opens only the public training packet, never truth or heldout data."""
import hashlib
import json
from pathlib import Path

import numpy as np

from oeal.thermal_identification import design_matrix, fit_network

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/msl-identification"


def main():
    path = OUT / "train/measurements.csv"
    public_path = OUT / "train/public.json"
    public = json.loads(public_path.read_text())
    if public["split"] != "train":
        raise ValueError("only the training packet is accepted by the fitting process")
    data = np.loadtxt(path, delimiter=",", skiprows=1)
    arguments = (data[:, 0], data[:, 1:7], data[:-1, 7:13], public["ambient_c"],
                 public["area_m2"], public["convection_w_per_k"])
    fit = fit_network(*arguments)
    design, right, nodes = design_matrix(*arguments)
    np.savez_compressed(OUT / "training-design.npz", design=design, right=right, nodes=nodes)
    fit["source"] = dict(split="train", measurement_sha256=hashlib.sha256(
        path.read_bytes()).hexdigest(), public_config_sha256=hashlib.sha256(
            public_path.read_bytes()).hexdigest(), rows=len(data),
        opened_data_files=["train/measurements.csv", "train/public.json"],
        truth_or_validation_arguments=False)
    (OUT / "fitted.json").write_text(json.dumps(fit, indent=2))
    print("identification-fit: "+json.dumps(fit), flush=True)


if __name__ == "__main__":
    main()
