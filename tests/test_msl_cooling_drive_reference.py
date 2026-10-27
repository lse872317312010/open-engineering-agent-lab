"""Analytic hot-start and variable-cooling checks before integration code."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from msl_cooling_drive_reference import gc_at, rates  # noqa: E402
from msl_cooling_reference import SIGMA  # noqa: E402


def test_uniform_hot_start_three_signed_branches_and_storage():
    r = rates([80.]*6, [0.]*6, 1/3, .02)[0]
    q = .02*SIGMA*(353.15**4-298.15**4)
    np.testing.assert_allclose(r[8:], [27.5, 55/3, q], atol=1e-12)
    np.testing.assert_allclose(r[:6], [0, 0, -27.5/200, 0, 0, -(55/3+q)/100])
    assert q > 1 and abs(r[:6] @ [60,70,200,.5,25,100]+r[7]) < 1e-12


def test_linear_limit_and_smooth_gc_extrema():
    assert rates([80.]*6, [0.]*6, 0, 0)[0, 10] == 0
    np.testing.assert_allclose([gc_at(t, True) for t in (0,.025,.075,.1)],
                               [1/3, 1/3+.25, 1/3-.25, 1/3], atol=1e-14)
