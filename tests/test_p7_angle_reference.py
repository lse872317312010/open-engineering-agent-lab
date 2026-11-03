"""Independent sinusoidal limits and invalid inputs for the angle derivative."""
import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "angle_reference", Path(__file__).resolve().parents[1] / "benchmarks/p7_angle_reference.py")
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)
periodic_back_emf = reference.periodic_back_emf


@pytest.mark.parametrize(("count", "limit"), [(12, .046), (6, .174)])
def test_analytic_periodic_sinusoid(count, limit):
    angle = np.arange(count) * (math.pi / 2) / count
    phase = 4 * angle
    flux = np.column_stack([np.sin(phase), np.cos(phase), -np.sin(phase)])
    speed = 600 * 2 * math.pi / 60
    exact = -speed * 4 * np.column_stack(
        [np.cos(phase), -np.sin(phase), -np.cos(phase)])
    result = periodic_back_emf(flux, speed)
    assert np.max(np.abs(result - exact)) / (4 * speed) < limit
    assert np.array_equal(periodic_back_emf(flux, -speed), -result)
    assert np.array_equal(periodic_back_emf(flux, 2 * speed), 2 * result)
    assert np.array_equal(periodic_back_emf(flux, 0), np.zeros_like(flux))


@pytest.mark.parametrize("flux", [np.ones((2, 3)), np.ones((4, 2)),
                                   np.array([[np.nan, 0, 0]] * 4)])
def test_reject_invalid_flux(flux):
    with pytest.raises(ValueError):
        periodic_back_emf(flux, 1)


@pytest.mark.parametrize(("speed", "period"), [(float("nan"), 1), (1, 0), (1, float("inf"))])
def test_reject_invalid_speed_or_period(speed, period):
    with pytest.raises(ValueError):
        periodic_back_emf(np.ones((4, 3)), speed, period)
