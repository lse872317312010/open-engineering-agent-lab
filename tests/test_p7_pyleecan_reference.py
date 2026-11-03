"""Hand geometry, units and corruption limits independent of PYLEECAN/FEMM."""
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "slotted_reference", ROOT / "benchmarks/p7_pyleecan_reference.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)


def test_hand_sector_and_polygon():
    assert ref.sector_area(1, 2, math.pi/2) == pytest.approx(3*math.pi/4)
    assert ref.polygon_area([[0, 0], [2, 0], [2, 3], [0, 3]]) == 6
    assert ref.polygon_area([[0, 3], [2, 3], [2, 0], [0, 0]]) == 6


def test_fixed_reference_identity_and_winding_count():
    raw = json.loads((ROOT / "benchmarks/assets/pyleecan-spmsm001.json").read_text())
    a = ref.reference(raw)
    assert a["gap_m"] == pytest.approx(.001)
    assert a["slot_m2"] == pytest.approx(.00022220760056461245)
    assert a["magnet_m2"] == pytest.approx(.00005972953032637592)
    assert raw["stator"]["slot"]["Zs"] == 12
    assert raw["rotor"]["slot"]["Zs"] == 8
    assert raw["stator"]["winding"]["p"] == 4
    assert 12*2*34/3 == 272
    # The phase's series turns count both sides once, not twice.
    assert 272/2 == 136


def test_axial_scaling_hand_vector_and_faults():
    np.testing.assert_allclose(ref.physical_depth([.2, 2], .05, 1), [.01, .1])
    np.testing.assert_allclose(ref.physical_depth([.2, 2], .1, 1), [.02, .2])
    assert abs(.2-.01)/.05 > .02
    assert ref.sector_area(1000, 2000, math.pi/2)/ref.sector_area(1, 2, math.pi/2) == 1e6


@pytest.mark.parametrize("args", [(2, 1, 1), (0, 1, 0), (0, 1, math.inf)])
def test_invalid_geometry(args):
    with pytest.raises(ValueError):
        ref.sector_area(*args)


def test_invalid_depth_and_nonfinite():
    for value, length, native in ((1, 0, 1), (1, .05, 0), (np.nan, .05, 1)):
        with pytest.raises(ValueError):
            ref.physical_depth(value, length, native)
