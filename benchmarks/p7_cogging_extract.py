"""Extract the immutable published report after verifying its exact archive digest."""
import hashlib
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "outputs/open-engineering-report.zip"
DEST = ROOT / "outputs/cogging-source"
SHA = "4667c4b88116b892719016fa42564bcbac2ea223702a51d5c4bb3eba7304802e"


def main():
    actual = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    if actual != SHA:
        raise ValueError("published source archive SHA256 mismatch")
    with zipfile.ZipFile(ARCHIVE) as archive:
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
                raise ValueError("unsafe source archive path")
        archive.extractall(DEST)
    print("cogging-source-archive-sha256: "+actual)


if __name__ == "__main__":
    main()
