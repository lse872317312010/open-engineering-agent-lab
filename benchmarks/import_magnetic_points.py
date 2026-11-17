"""Convert explicitly described SI dq point data to the upstream GradNet NPZ format."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

REQUIRED = ("id_A", "iq_A", "psi_d_Wb", "psi_q_Wb")
REQUIRED_METADATA = ("source_software", "source_version", "model_id", "pole_pairs",
                     "temperature_c", "dq_convention", "phase_sequence", "domain")
CONVENTION = "motulator_peak_d_plus_jq"


def convert(csv_path: Path, metadata_path: Path, output_path: Path) -> None:
    """Preserve input point pairs and provenance without interpolating or extrapolating."""
    if output_path.resolve() in (csv_path.resolve(), metadata_path.resolve()):
        raise ValueError("output must not overwrite an input file")
    raw = csv_path.read_bytes()
    metadata_raw = metadata_path.read_bytes()
    metadata = json.loads(metadata_raw)
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be a JSON object")
    for name in REQUIRED_METADATA:
        if name not in metadata or metadata[name] is None or metadata[name] == "":
            raise ValueError(f"missing metadata: {name}")
    if metadata["dq_convention"] != CONVENTION:
        raise ValueError("convert coordinates to the declared motulator peak convention first")
    poles = metadata["pole_pairs"]
    if isinstance(poles, bool) or not isinstance(poles, int) or poles < 1:
        raise ValueError("pole_pairs must be a positive integer")
    temperature = metadata["temperature_c"]
    if (isinstance(temperature, bool) or not isinstance(temperature, (int, float))
            or not math.isfinite(temperature)):
        raise ValueError("temperature_c must be finite")
    for name in ("source_software", "source_version", "model_id", "phase_sequence", "domain"):
        if not isinstance(metadata[name], str) or not metadata[name].strip():
            raise ValueError(f"{name} must be a non-empty string")
    reader = csv.DictReader(raw.decode("utf-8-sig").splitlines())
    if reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError("missing or duplicate CSV column names")
    rows = list(reader)
    if not rows or any(name not in reader.fieldnames for name in REQUIRED):
        raise ValueError("CSV must contain the four required columns and at least one row")
    points, seen = [], set()
    for index, row in enumerate(rows, start=2):
        try:
            point = tuple(float(row[name]) for name in REQUIRED)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid numeric field at CSV row {index}") from exc
        if not all(math.isfinite(value) for value in point):
            raise ValueError(f"nonfinite value at CSV row {index}")
        if point[:2] in seen:
            raise ValueError(f"duplicate current coordinates at CSV row {index}")
        seen.add(point[:2])
        points.append(point)
    data = np.asarray(points, dtype=np.float64)
    manifest = {
        "format": "oeal-magnetic-points-v1",
        "source_csv_sha256": hashlib.sha256(raw).hexdigest(),
        "metadata_sha256": hashlib.sha256(metadata_raw).hexdigest(),
        "metadata": metadata,
        "point_count": len(points),
        "units": {"current": "A peak", "flux_linkage": "Wb"},
        "limits": "source points only; valid interpolation domain is not established",
    }
    # Save through a file handle: numpy otherwise silently appends .npz to the name.
    with output_path.open("wb") as output:
        np.savez_compressed(output, i_s_dq=data[:, 0] + 1j * data[:, 1],
                            psi_s_dq=data[:, 2] + 1j * data[:, 3],
                            manifest_json=np.asarray(json.dumps(manifest, ensure_ascii=False)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    convert(args.csv, args.metadata, args.output)


if __name__ == "__main__":
    main()
