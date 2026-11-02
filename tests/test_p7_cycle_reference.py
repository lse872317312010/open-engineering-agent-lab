"""Frozen cycle boundaries and zero-source cooling analytic limit."""
import sys
from pathlib import Path

import numpy as np
import pytest

from oeal.thermal_rom import AffineThermalROM

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from p7_cycle_reference import cycle_command  # noqa: E402


@pytest.mark.parametrize("tick,phase,iq,load", [
    (0, 0, 0., 0.), (222, 0, 0., 0.), (223, 1, .2, .015),
    (8002, 1, .2, .015), (8003, 2, .28, .035), (15999, 2, .28, .035),
    (16000, 3, 0., 0.), (40000, 3, 0., 0.),
])
def test_frozen_cycle_boundaries(tick, phase, iq, load):
    c = cycle_command(tick)
    assert (c["phase"], c["iq_a"], c["load_nm"]) == (phase, iq, load)
    assert c["brake_nms"] == (.04 if phase == 3 else 1e-5)


def test_zero_heat_window_still_advances_cooling():
    data = dict(format_version=np.array(1), mass=np.eye(1),
                bulk_stiffness=np.array([[2.]]), contact_stiffness=np.zeros((1, 1)),
                forcing=np.array([[1., 0.]]), observations=np.ones((6, 1)),
                rc_bounds=np.array([.01, 1.]), reference_rc=np.array(.1),
                ambient_c=np.array(25.))
    model = AffineThermalROM(data, rc=.1, dt_s=.0025)
    model.step_average([1., 0.])
    warm = model.state[0]
    model.step_average([0., 0.])
    assert 0 < model.state[0] < warm
    assert model.state[0] == pytest.approx(warm*(1-.0025)/(1+.0025), abs=1e-15)
