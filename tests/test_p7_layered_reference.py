"""Independent balance, Robin, interface and resistance limits."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from p7_layered_reference import (  # noqa: E402
    CASES,
    HEIGHT,
    PATCH,
    THICKNESS,
    A,
    L,
    constants,
    gradient_x,
    powers,
    temperature,
)


def test_piecewise_reference_satisfies_mixed_boundaries_and_energy():
    for case in CASES:
        p = powers(case)
        assert abs(float(temperature(0.,case))-case["left_c"]) < 1e-12
        right = case["h"]*(temperature(L,case)-case["ambient_c"])*HEIGHT*THICKNESS
        assert abs(right-p["right_out_w"]) < 1e-12
        assert abs(p["left_out_w"]+p["right_out_w"]-p["source_w"]) < 1e-12
        assert abs(temperature(A-1e-10,case)-temperature(A+1e-10,case)) < 1e-6
        left_flux = -case["k1"]*gradient_x(A-1e-10,case)
        right_flux = -case["k2"]*gradient_x(A+1e-10,case)
        assert abs(left_flux-right_flux) < 1e-5


def test_zero_source_reduces_to_series_conduction_and_convection():
    resistance = .04/2.+.06/.2+1/10.
    expected_flux = (50.-25.)/resistance
    f0,_ = constants(PATCH)
    assert abs(f0-expected_flux) < 1e-12
    assert powers(CASES[2])["right_out_w"] < 0.
    assert powers(CASES[2])["left_out_w"] > 0.


def test_independent_second_difference_matches_piecewise_source():
    for case in CASES:
        for x,k,source in ((.02,case["k1"],case["s1"]),(.07,case["k2"],case["s2"])):
            h = 1e-5
            second = (temperature(x+h,case)-2*temperature(x,case)+temperature(x-h,case))/h**2
            np.testing.assert_allclose(-k*second,source,rtol=2e-5)
