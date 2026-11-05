"""Challenge native readback audit and restore all source bytes."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "outputs/native-results/native-coenergy-0"
CMD = [sys.executable, "benchmarks/p7_native_coenergy_report.py"]


def rejected(env=None):
    result = subprocess.run(CMD, cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode != 0, "corrupt native readback was accepted"


def main():
    path = FOLDER / "native-coenergy.json"
    manifest_path = FOLDER / "manifest.json"
    original, original_manifest = path.read_bytes(), manifest_path.read_bytes()
    try:
        path.write_bytes(original+b"corruption")
        rejected()
        data = json.loads(original)
        data["samples"].pop()
        path.write_text(json.dumps(data), encoding="utf-8")
        manifest = {"native-coenergy.json": hashlib.sha256(path.read_bytes()).hexdigest()}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        rejected()
    finally:
        path.write_bytes(original)
        manifest_path.write_bytes(original_manifest)
    archived = ROOT / "outputs/p7-cogging-report/native-evidence/shard-0/native-coenergy.json"
    assert archived.read_bytes() == original
    env = os.environ.copy()
    env["NATIVE_COMMIT"] = "4030532a05a932b3c84f7742218d23130be2f819"
    rejected(env)
    print("native-coenergy-negative: corruption, missing sample, wrong producer rejected")


if __name__ == "__main__":
    main()
