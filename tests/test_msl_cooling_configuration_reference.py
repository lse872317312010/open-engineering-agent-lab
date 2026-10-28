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


def test_configuration_rejects_types_dimensions_ranges_and_nonfinite_values():
    import pytest
    from msl_cooling_drive_parameters import configuration

    for invalid in (True, "25", float("nan"), float("inf"), -11, 61):
        with pytest.raises(ValueError):
            configuration(ambient_c=invalid)
    for invalid in (True, "0.02", float("nan"), -.01, .11):
        with pytest.raises(ValueError):
            configuration(area_m2=invalid)
    for invalid in ([25.]*5, [[25.]*6], [25.]*5+[True], ["25"]*6,
                    [25.]*5+[float("nan")], [25.]*5+[-11], [25.]*5+[121]):
        with pytest.raises(ValueError):
            configuration(initial_temperatures_c=invalid)


def test_configuration_keeps_default_and_normalizes_valid_six_node_input():
    from msl_cooling_drive_parameters import configuration

    assert configuration() == (25., .02, (80.,)*6)
    assert configuration(-10, 0, np.arange(6)) == (-10., 0., (0.,1.,2.,3.,4.,5.))


def test_reference_changes_real_environment_in_all_three_branches():
    from msl_cooling_drive_reference import rates

    t = [80.,70.,60.,100.,65.,50.]
    for ambient in (-10.,25.,60.):
        actual = rates(t, [0.]*6, 1/3, .02, ambient)[0]
        expected = boundary(t, ambient, 1/3, .02)
        np.testing.assert_allclose(actual[8:], expected, atol=1e-12, rtol=0)
        assert abs(actual[:6] @ [60,70,200,.5,25,100]+sum(expected)) < 1e-12
