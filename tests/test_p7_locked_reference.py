"""Independent scalar RL current and energy balance, plus domain rejection."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "locked_ref", Path(__file__).resolve().parents[1] / "benchmarks/p7_locked_reference.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)


def test_scalar_rl_step_and_energy():
    inductance = np.diag([.001, .002])
    inverse = np.linalg.inv(inductance)
    value = np.zeros(4)
    for _ in range(20):
        value = ref.advance(value, np.array([0., .3]), .3, inverse, 50e-6)
    expected = 1-np.exp(-.3*.001/.002)
    assert value[1] == pytest.approx(expected, abs=1e-10)
    energy = .75*value[:2]@inductance@value[:2]
    assert abs(value[2]-value[3]-energy) < 1e-10


def test_out_of_domain_not_clipped():
    with pytest.raises(ValueError):
        ref.advance(np.array([3., 0., 0., 0.]), np.zeros(2), .3, np.eye(2), 1e-5)
