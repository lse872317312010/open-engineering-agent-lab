"""Challenge the report auditor with tampered inputs; restore all source bytes."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "outputs/deep/deep-angle-0"
CMD = [sys.executable, "benchmarks/p7_deep_angle_evaluate.py"]


def rejected(env=None):
    result = subprocess.run(CMD, cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode != 0, "corrupt evidence was accepted"


def main():
    manifest_path = FOLDER / "manifest.json"
    lane_path = FOLDER / "deep-angle.json"
    original_manifest = manifest_path.read_bytes()
    original_lane = lane_path.read_bytes()
    manifest = json.loads(original_manifest)
    native_name = next(name for name in manifest if name.endswith(".ans"))
    native_path = FOLDER / native_name
    native_bytes = native_path.read_bytes()
    try:
        native_path.write_bytes(native_bytes+b"corruption")
        rejected()
    finally:
        native_path.write_bytes(native_bytes)
    try:
        lane = json.loads(original_lane)
        lane["cases"].pop()
        lane_path.write_text(json.dumps(lane), encoding="utf-8")
        manifest["deep-angle.json"] = hashlib.sha256(lane_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        rejected()
    finally:
        lane_path.write_bytes(original_lane)
        manifest_path.write_bytes(original_manifest)
    env = os.environ.copy()
    env["DEEP_COMMIT"] = "9b9482284ff18664abb1537ba050debb0ee556b0"
    rejected(env)
    print("deep-angle-audit-negative: native tamper, missing point, wrong producer rejected")


if __name__ == "__main__":
    main()
