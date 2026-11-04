"""Independent sinusoidal derivative limit for the newly frozen 24-point cycle."""
import importlib.util
import math
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location(
    "angle_ref", Path(__file__).resolve().parents[1] / "benchmarks/p7_angle_reference.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)


def test_24_point_sinusoidal_derivative():
    errors = []
    for count in (12, 24):
        angle = np.arange(count)*2*math.pi/count
        flux = np.column_stack([np.sin(angle), np.cos(angle), -np.sin(angle)])
        exact = -4*np.column_stack([np.cos(angle), -np.sin(angle), -np.cos(angle)])
        value = ref.periodic_back_emf(flux, 1.)
        errors.append(float(np.max(abs(value-exact))/4))
    assert errors[0] < .046
    assert errors[1] < .0115
    assert errors[1] < errors[0]
