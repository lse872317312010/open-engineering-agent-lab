"""Independent small-matrix steady feedback and discrete stability check."""
import importlib
import math
from pathlib import Path

import numpy as np
import pytest

from oeal.stator_feedback import CopperResistanceLaw


@pytest.fixture
def study(monkeypatch):
    for package in ("gmsh", "meshio", "skfem", "scipy", "matplotlib"):
        pytest.importorskip(package)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "benchmarks"))
    return importlib.import_module("p7_feedback_endurance")


def two_node():
    from scipy.sparse import csr_matrix

    mass = np.diag([2., 3.])
    bulk = np.array([[1., -1.], [-1., 1.]])
    convection = np.diag([0., 1.])
    source = np.array([1., 0.])
    observation = np.array([[1., 0.], [0., 1.], [2., 3.], [0., 1.]])
    fom = dict(mass=np.diag(mass), bulk=csr_matrix(bulk), convection=csr_matrix(convection),
               forcing=source, observations=observation)
    bundle = dict(mass=mass, bulk=bulk, convection=convection, forcing=source,
                  observations=observation, power_bounds_w=[0., 2.])
    return fom, bundle


def test_steady_formula_matches_direct_solve_and_independent_spectrum(study):
    fom, bundle = two_node()
    law = CopperResistanceLaw(reference_ohm=1.)
    metrics, arrays = study.steady_case(fom, bundle, np.eye(2), 5., 25.,
                                       law=law, iq=math.sqrt(2/3))
    stiffness = np.array([[1., -1.], [-1., 6.]])
    correction = np.array([[.004, 0.], [0., 0.]])
    expected = np.linalg.solve(stiffness-correction, [1., 0.])
    np.testing.assert_allclose(arrays["full_field"], expected, atol=1e-14)
    np.testing.assert_allclose(arrays["rom_field"], expected, atol=1e-14)
    assert metrics["full_loop_gain"] == pytest.approx(.0048)
    assert metrics["full_stability_margin"] == pytest.approx(.9952)
    advance = np.linalg.solve(bundle["mass"]+stiffness, bundle["mass"]+correction)
    assert max(abs(np.linalg.eigvals(advance))) < 1 and metrics["passed"]


def test_unstable_thermal_feedback_is_rejected(study):
    fom, bundle = two_node()
    law = CopperResistanceLaw(reference_ohm=1., coefficient_per_k=1., minimum_c=25.)
    with pytest.raises(ValueError, match="unstable"):
        study.steady_case(fom, bundle, np.eye(2), 5., 25., law=law, iq=math.sqrt(2/3))


def test_envelope_switches_at_exact_left_endpoints(study):
    for dt in (1., .5, .0025):
        boundary = round(600/dt)
        assert study.envelope("C", boundary-1, dt) == .5
        assert study.envelope("C", boundary, dt) == 0.
        assert study.envelope("C", 2*boundary, dt) == .5
