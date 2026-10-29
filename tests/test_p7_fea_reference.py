"""Independent point limits, finite-difference PDE and analytic total power."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from p7_fea_reference import (  # noqa: E402
    exact_total_power_w,
    gradient,
    rise,
    source_w_per_m3,
)


def test_manufactured_limits_gradient_and_total_heat():
    assert abs(rise(.05, .05)-10.) < 1e-12
    assert abs(rise(0., .025)) < 1e-12
    np.testing.assert_allclose(gradient(.05, .05), 0., atol=1e-12)
    # Four sides each carry 2*k*A*thickness = 0.4 W.
    assert abs(exact_total_power_w()-4*.4) < 1e-14


def test_independent_finite_difference_matches_volumetric_source():
    x, y, h = .037, .062, 1e-6
    laplacian = (rise(x+h, y)+rise(x-h, y)+rise(x, y+h)+rise(x, y-h)
                 -4*rise(x, y))/h**2
    assert abs((-2*laplacian)/source_w_per_m3(x, y)-1) < 2e-6
