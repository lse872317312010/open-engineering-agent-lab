"""Reuse full-trajectory figures and UI gates for configured actual-drive evidence."""
from pathlib import Path

from build_msl_cooling_drive_report import main

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    main(source=ROOT / "outputs/msl-configured-drive",
         output=ROOT / "outputs/msl-configured-drive-report",
         template="reports/msl-configured-drive.html",
         contract="docs/msl-configured-drive-contract.md")
