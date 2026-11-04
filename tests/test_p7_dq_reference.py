"""Independent known frame/zero-sequence and swapped-phase rejection."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "frame", Path(__file__).resolve().parents[1] / "benchmarks/p7_dq_reference.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)


def test_known_offset_and_zero_sequence():
    angle = np.arange(12)*np.pi/24
    phase = 4*angle + .37
    flux = .06*np.cos(phase[:, None] - np.array([0, 2*np.pi/3, -2*np.pi/3])) + .002
    result = ref.fit_frame(angle, flux)
    assert result["offset_rad"] == pytest.approx(.37, abs=1e-12)
    assert result["amplitude_wb"] == pytest.approx(.06, abs=1e-12)
    with pytest.raises(ValueError):
        ref.fit_frame(angle, flux[:, [0, 2, 1]])
