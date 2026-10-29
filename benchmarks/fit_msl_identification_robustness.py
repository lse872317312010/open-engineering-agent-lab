"""Fit only perturbed public training packets; no protocol/truth/heldout imports."""
import hashlib
import json
from pathlib import Path

import numpy as np

from oeal.thermal_identification import fit_network

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/msl-identification-robustness"


def main():
    manifest = json.loads((OUT / "packets.json").read_text())
    summaries = []
    for spec in manifest["cases"]:
        folder = OUT / "packets" / spec["id"]
        packet, public_path = folder / "measurements.csv", folder / "public.json"
        public = json.loads(public_path.read_text())
        assert public["split"] == "train"
        assert hashlib.sha256(packet.read_bytes()).hexdigest() == spec["packet_sha256"]
        assert hashlib.sha256(public_path.read_bytes()).hexdigest() == spec["public_sha256"]
        data = np.loadtxt(packet, delimiter=",", skiprows=1)
        try:
            fit = fit_network(data[:, 0], data[:, 1:7], data[:-1, 7:13],
                              public["ambient_c"], public["area_m2"],
                              public["convection_w_per_k"])
            result = dict(id=spec["id"], solver_succeeded=True, fit=fit)
        except ValueError as error:
            result = dict(id=spec["id"], solver_succeeded=False, error=str(error))
        result["opened_data_files"] = [str(packet.relative_to(OUT)),
                                      str(public_path.relative_to(OUT))]
        path = OUT / "fits" / (spec["id"]+".json")
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(result, indent=2))
        summaries.append(dict(id=spec["id"], solver_succeeded=result["solver_succeeded"],
                              frozen_fit_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        print("robustness-fit: "+json.dumps(result), flush=True)
    (OUT / "frozen-fits.json").write_text(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
