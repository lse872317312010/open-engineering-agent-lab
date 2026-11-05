"""Hand limits retain an unsupported physical-model result and reject corrupt inputs."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "angular_gate", Path(__file__).resolve().parents[1] / "benchmarks/p7_angular_reference.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)


def test_failed_model_is_retained():
    result = ref.evaluate([[.002, 0], [0, 0]], [[0, 0], [0, 0]], [.2, 0], [0, 0])
    assert not result["model_supported"]
    assert result["flux_error"] == pytest.approx([.04, 0])
    assert result["torque_error"] == pytest.approx([.2, 0])
    assert result["failed_indices"] == [0]
    assert result["supported"] == [False, True]


def test_exact_values_support():
    assert ref.evaluate([[.06, 0]], [[.06, 0]], [.7], [.7])["model_supported"]


@pytest.mark.parametrize("actual", [[[np.nan, 0]], [[1, 2, 3]], []])
def test_corrupt_data_rejected(actual):
    with pytest.raises(ValueError):
        ref.evaluate(actual, [[0, 0]], [0], [0])
