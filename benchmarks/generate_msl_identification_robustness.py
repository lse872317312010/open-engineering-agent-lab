"""Twenty frozen training packets; clean MSL data accessed only in this generation process."""
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/msl-identification"
OUT = ROOT / "outputs/msl-identification-robustness"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = np.loadtxt(SOURCE / "train/trajectory.csv", delimiter=",", skiprows=1)
    public = json.loads((SOURCE / "train/public.json").read_text())
    clean = np.column_stack([data[:, 0], data[:, 1:7], data[:, 11:17]])
    specs = [dict(id="ideal", kind="ideal", noise_k=0., seed=2026102901)]
    for noise in (.02, .1, .5):
        for k in range(4):
            specs.append(dict(id=f"noise-{noise:.2f}-{k+1}", kind="noise",
                              noise_k=noise, seed=2026102901+k))
    for name in ("winding-bias", "common-bias", "power-half", "winding-power-zero",
                 "missing-core", "equilibrium", "equilibrium-noisy"):
        specs.append(dict(id=name, kind=name,
                          noise_k=0. if name == "equilibrium" else .02, seed=2026102901))
    header = ",".join(public["columns"])
    for spec in specs:
        packet = clean.copy()
        if spec["kind"].startswith("equilibrium"):
            packet[:, 1:7], packet[:, 7:13] = 25., 0.
        packet[:, 1:7] += np.random.default_rng(spec["seed"]).normal(
            0., spec["noise_k"], size=packet[:, 1:7].shape)
        if spec["kind"] == "winding-bias":
            packet[:, 1] += 2.
        if spec["kind"] == "common-bias":
            packet[:, 1:7] += 2.
        if spec["kind"] == "power-half":
            packet[:, 7:13] *= .5
        if spec["kind"] == "winding-power-zero":
            packet[:, 7] = 0.
        if spec["kind"] == "missing-core":
            packet[:, 2] = np.nan
        folder = OUT / "packets" / spec["id"]
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "measurements.csv"
        np.savetxt(path, packet, delimiter=",", header=header, comments="")
        packet_public = dict(public, noise_sigma_k=spec["noise_k"], perturbation=spec["kind"])
        (folder / "public.json").write_text(json.dumps(packet_public, indent=2))
        spec["packet_sha256"] = digest(path)
        spec["public_sha256"] = digest(folder / "public.json")
    manifest = dict(cases=specs, count=len(specs), source_training_sha256=digest(
        SOURCE / "train/trajectory.csv"), scope="synthetic training perturbations only")
    (OUT / "packets.json").write_text(json.dumps(manifest, indent=2))
    assert len(specs) == 20
    print("robustness-packets: "+json.dumps(manifest), flush=True)


if __name__ == "__main__":
    main()
