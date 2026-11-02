"""Check Ampere sign, energy and winding conventions independently of FE."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from p7_magnetic_reference import (  # noqa: E402
    CASES,
    DEPTH,
    HEIGHT,
    LENGTH,
    SPLIT,
    exact,
    inductance,
)


@pytest.mark.parametrize("case", CASES)
def test_analytic_ampere_and_energy(case):
    # Separate Gauss integration in each material avoids crossing the interface.
    gauss, weight = np.polynomial.legendre.leggauss(12)
    energy, linkage = 0., 0.
    for start, width, mu, sign in (
        (0., SPLIT, case["mu_left"], 1.),
        (SPLIT, LENGTH-SPLIT, case["mu_right"], -1.),
    ):
        x = start+width*(gauss+1)/2
        az, bx, by, hy = exact(x, case)
        density = sign*case["current_a"]/(width*HEIGHT)
        assert np.max(abs(bx)) == 0
        assert np.allclose(np.diff(hy)/np.diff(x), density, rtol=1e-12)
        energy += DEPTH*HEIGHT*width/4*np.dot(weight, by**2/mu)
        linkage += DEPTH*sign*width/2/width*np.dot(weight, az)
    expected = inductance(case)
    assert np.isclose(2*energy/case["current_a"]**2, expected, rtol=1e-12, atol=0)
    assert np.isclose(linkage/case["current_a"], expected, rtol=1e-12, atol=0)
    assert np.max(abs(exact(np.array([0., SPLIT, LENGTH]), case)[0])) < 1e-20


def test_interface_tangential_h_and_reversal():
    c = CASES[1]
    eps = 1e-12
    hl = exact(SPLIT-eps, c)[3]
    hr = exact(SPLIT+eps, c)[3]
    assert abs(hl-hr) < 1e-8
    x = np.linspace(0, LENGTH, 101)
    assert np.allclose(exact(x, c)[0], -exact(x, CASES[2])[0], atol=1e-25)
    assert inductance(c) == inductance(CASES[2])
