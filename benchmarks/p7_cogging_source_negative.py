"""Verify corruption of either locked upstream input is rejected and restored."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/cogging-source"
CMD = [sys.executable, "benchmarks/p7_cogging_evaluate.py"]


def main():
    for name in ("deep.json", "model.json"):
        path = SOURCE / name
        original = path.read_bytes()
        try:
            path.write_bytes(original+b"corruption")
            result = subprocess.run(CMD, cwd=ROOT, capture_output=True, text=True)
            assert result.returncode != 0, f"tampered {name} accepted"
        finally:
            path.write_bytes(original)
    print("cogging-source-negative: tampered field and model rejected")


if __name__ == "__main__":
    main()
