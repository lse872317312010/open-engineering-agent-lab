"""Hand-calculated independent constitutive/interpolation limits."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "nonlinear_reference", Path(__file__).resolve().parents[1]
    / "benchmarks/p7_femm_nonlinear_reference.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)


def test_material_monotonic_nodes_and_direction():
    assert np.all(np.diff(ref.BH, axis=0) > 0)
    assert ref.material_node(1.5) == 12000
    assert ref.material_node(-1.5) == -12000
    with pytest.raises(ValueError):
        ref.material_node(1.55)


def test_bilinear_hand_value_edges_and_vector_components():
    values = np.array([[[0, 2], [4, 6]], [[2, 4], [10, 12]]], dtype=float)
    np.testing.assert_allclose(ref.interpolate([0, 2], values, 1, 1), [4, 6])
    np.testing.assert_allclose(ref.interpolate([0, 2], values, 2, 2), [10, 12])
    np.testing.assert_allclose(ref.interpolate([0, 2], values, 0, 1), [2, 4])


@pytest.mark.parametrize("d,q", [(-.001, 0), (2.001, 0), (0, np.nan), (np.inf, 0)])
def test_map_rejects_extrapolation_and_nonfinite(d, q):
    with pytest.raises(ValueError):
        ref.interpolate([0, 2], np.zeros((2, 2, 2)), d, q)


def test_map_rejects_invalid_grid_and_corrupt_values():
    for axis, data in (([0, 0], np.zeros((2, 2, 2))),
                       ([0, 2], np.zeros((2, 3, 2))),
                       ([0, 2], np.full((2, 2, 2), np.nan))):
        with pytest.raises(ValueError):
            ref.interpolate(axis, data, 0, 0)
