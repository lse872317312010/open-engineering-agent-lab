"""Parameterized thermal-component report using full actual-drive traces and Chrome gates."""
from pathlib import Path

from build_msl_cooling_drive_report import main

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    main(source=ROOT / "outputs/msl-rc", output=ROOT / "outputs/msl-rc-report",
         template="reports/msl-rc.html", contract="docs/msl-rc-contract.md",
         fmu="outputs/msl-parametric/OEALMSLParametric.fmu")
