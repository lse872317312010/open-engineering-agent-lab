"""Split user-labelled magnetic CSV points without selecting data for the user."""
import argparse
import csv
import hashlib
import json
import tempfile
from pathlib import Path

from import_magnetic_points import REQUIRED, convert
from p8_fit_external import check_exact_separation, load_points

ROLES = ("train", "validation", "holdout")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_points(source, metadata, output):
    """Preserve source rows and reject exact or q-reflected inputs shared by splits."""
    if output.exists():
        raise ValueError("output path must not already exist")
    source_bytes = source.read_bytes()
    metadata_hash = digest(metadata)
    reader = csv.DictReader(source_bytes.decode("utf-8-sig").splitlines())
    if reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError("missing or duplicated CSV header")
    if not set((*REQUIRED, "split")).issubset(reader.fieldnames):
        raise ValueError("CSV requires split and the four dq columns")
    rows = {role: [] for role in ROLES}
    row_index = []
    for line, row in enumerate(reader, start=2):
        role = row["split"]
        if role not in rows or None in row:
            raise ValueError(f"invalid split or unexpected fields at row {line}")
        rows[role].append({key: row[key] for key in REQUIRED})
        row_index.append((line, role))
    if any(len(rows[role]) < 4 for role in ROLES):
        raise ValueError("each split needs at least four rows")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".p8-split-", dir=output.parent) as tmp:
        folder = Path(tmp) / "bundle"
        folder.mkdir()
        parsed = {}
        for role in ROLES:
            csv_path = folder / f"{role}.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=REQUIRED)
                writer.writeheader()
                writer.writerows(rows[role])
            npz = folder / f"{role}.npz"
            convert(csv_path, metadata, npz)
            parsed[role] = load_points(npz)
        for left, right in (("train", "validation"), ("train", "holdout"),
                            ("validation", "holdout")):
            check_exact_separation(parsed[left], parsed[right])
        with (folder / "source-rows.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(("source_row_number", "split"))
            writer.writerows(row_index)
        manifest = {
            "source_csv_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "metadata_sha256": metadata_hash,
            "counts": {role: len(rows[role]) for role in ROLES},
            "split_npz_sha256": {role: digest(folder / f"{role}.npz") for role in ROLES},
            "source_row_mapping_sha256": digest(folder / "source-rows.csv"),
            "limitations": [
                "exact and q-reflected duplicates checked; near-duplicates are not",
                "labels and domain originate from the user, not physical validation",
                "holdout must not be used for training or model selection",
            ],
        }
        (folder / "split-manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        folder.rename(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    split_points(args.csv, args.metadata, args.output)


if __name__ == "__main__":
    main()
