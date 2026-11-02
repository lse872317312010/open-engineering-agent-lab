"""Real-file cross-platform manifest integrity and fail-closed metadata coverage."""
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from p7_femm_reuse import verify_manifest  # noqa: E402


def fixture_manifest(folder, separator):
    manifest = {}
    names = ["field-validation.json", "parameters.json", "validation.json",
             "probe-validation.json", "grid0/open24/a00/motor.ans"]
    for name in names:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("actual-file:"+name).encode())
        key = ("p7-femm/"+name).replace("/", separator)
        manifest[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


@pytest.mark.parametrize("separator", ["/", "\\"])
def test_manifest_checks_windows_and_posix_paths(tmp_path, separator):
    manifest = fixture_manifest(tmp_path, separator)
    verified = verify_manifest(tmp_path, manifest)
    assert len(verified) == 5
    assert "p7-femm/grid0/open24/a00/motor.ans" in verified


def test_manifest_rejects_changed_parameter_file(tmp_path):
    manifest = fixture_manifest(tmp_path, "\\")
    (tmp_path / "parameters.json").write_bytes(b"changed after validation")
    with pytest.raises(ValueError, match="mismatch"):
        verify_manifest(tmp_path, manifest)


def test_manifest_rejects_zero_covered_files(tmp_path):
    with pytest.raises(ValueError, match="empty or omits"):
        verify_manifest(tmp_path, {"unrelated/file":"not-a-valid-coverage-set"})
