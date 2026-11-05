"""Hand affine flux/potential and invalid model/domain inputs."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "local_flux", Path(__file__).resolve().parents[1] / "benchmarks/p7_local_flux_model.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_hand_flux_and_potential_gradient():
    model = module.LocalFluxModel([.06, .001], [[.002, .0001], [.0001, .003]])
    np.testing.assert_allclose(model.flux([1, -.5]), [.06195, -.0004])
    assert model.coenergy_increment([1, -.5]) == pytest.approx(.060825)
    for q in range(2):
        current = np.array([.5, -.25])
        delta = np.eye(2)[q]*1e-5
        slope = (model.coenergy_increment(current+delta)
                 - model.coenergy_increment(current-delta))/(2e-5)
        assert slope == pytest.approx(model.flux(current)[q], abs=1e-10)


@pytest.mark.parametrize("matrix", [[[0, 0], [0, 1]], [[1, 1], [0, 1]]])
def test_invalid_matrix(matrix):
    with pytest.raises(ValueError):
        module.LocalFluxModel([0, 0], matrix)


@pytest.mark.parametrize("current", [[2, 1], [np.nan, 0], [1, 2, 3]])
def test_invalid_current(current):
    model = module.LocalFluxModel([.06, 0], [[.002, 0], [0, .003]])
    with pytest.raises(ValueError):
        model.flux(current)
