"""Analytic configuration examples frozen before implementation."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from msl_cooling_configuration_reference import boundary, initial_storage  # noqa: E402


def test_configured_boundary_equilibrium_and_signed_heat_import():
    np.testing.assert_array_equal(boundary([60.]*6, 60., 1/3, .02), [0.]*3)
    assert np.all(boundary([25.]*6, 60., 1/3, .02) < 0)
    assert np.all(boundary([25.]*6, -10., 1/3, .02) > 0)


def test_nonuniform_initial_storage_uses_all_six_capacities():
    t = [80.,70.,60.,100.,65.,50.]
    expected = 55*60+45*70+35*200+75*.5+40*25+25*100
    assert initial_storage(t) == expected
    assert initial_storage([25.]*6) == 0
