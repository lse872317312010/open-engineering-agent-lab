"""Analytic field boundary, normal-B/tangential-H and power-invariant peak mapping."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from p7_femm_reference import abc_from_dq, dq_from_abc, magnet_field  # noqa: E402


def test_cylinder_boundary_and_interface():
    theta = np.linspace(0, 2*np.pi, 101)
    az, _, _ = magnet_field(.04*np.cos(theta), .04*np.sin(theta))
    assert max(abs(az)) < 1e-17
    inner = magnet_field(.02*(1-1e-8)*np.cos(theta), .02*(1-1e-8)*np.sin(theta))
    outer = magnet_field(.02*(1+1e-8)*np.cos(theta), .02*(1+1e-8)*np.sin(theta))
    bn_inner = inner[1]*np.cos(theta)+inner[2]*np.sin(theta)
    bn_outer = outer[1]*np.cos(theta)+outer[2]*np.sin(theta)
    assert max(abs(bn_inner-bn_outer)) < 3e-8
    assert max(abs(inner[0]-outer[0])) < 1e-8


@pytest.mark.parametrize("angle", [0., .3, 1.8, 4.7])
def test_peak_dq_mapping_and_power(angle):
    current = abc_from_dq(.4, -.7, angle)
    voltage = abc_from_dq(2., 3., angle)
    assert abs(current.sum()) < 1e-15
    assert np.allclose(dq_from_abc(current, angle), [.4, -.7], atol=1e-14)
    assert np.isclose(voltage @ current, 1.5*(2*.4-3*.7), atol=1e-14)
