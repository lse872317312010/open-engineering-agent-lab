"""Analytical sign, angular unit and sliding-gap omission counterexamples."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "coenergy_ref", Path(__file__).resolve().parents[1] / "benchmarks/p7_native_coenergy_ref.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)


def test_positive_and_negative_energy_gradients():
    theta = .2
    delta = np.array([-ref.COARSE_RAD, -ref.FINE_RAD, 0, ref.FINE_RAD, ref.COARSE_RAD])
    for sign in (-1, 1):
        values = sign*np.sin(theta+delta)
        expected = sign*np.cos(theta)
        result = ref.compare(values, np.zeros(5), expected, expected)
        assert result["energy_torque_nm"] == pytest.approx(expected, abs=3e-5)
        assert result["passed"]


def test_gap_omission_is_detected():
    delta = np.array([-ref.COARSE_RAD, -ref.FINE_RAD, 0, ref.FINE_RAD, ref.COARSE_RAD])
    result = ref.compare(np.zeros(5), 2*delta, 2., 2.)
    assert result["passed"]
    assert result["gap_omission_effect_nm"] == pytest.approx(2.)
    assert result["block_only_torque_nm"] == 0


def test_bad_data_and_failed_gate():
    with pytest.raises(ValueError):
        ref.compare([0, 0, float("nan"), 0, 0], [0]*5, 0, 0)
    assert not ref.compare([0]*5, [0]*5, 1, 1)["passed"]
