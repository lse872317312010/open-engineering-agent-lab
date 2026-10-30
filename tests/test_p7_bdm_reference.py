"""Independent affine-span and normal-trace integration references for BDM1."""
import numpy as np
import pytest


def test_real_bdm_basis_spans_directional_affine_flux_rt0_cannot_span():
    skfem = pytest.importorskip("skfem")
    element = skfem.ElementTriBDM1()
    vertices = np.array([[0.,1.,0.],[0.,0.,1.]])

    def exact(x):
        return np.array([2.+3*x[0],-1.+4*x[1]])

    matrix = np.column_stack([element.lbasis(vertices,i)[0].ravel() for i in range(6)])
    coefficients = np.linalg.solve(matrix,exact(vertices).ravel())
    points = np.array([[.1,.2,.4],[.1,.5,.2]])
    actual = sum(coefficients[i]*element.lbasis(points,i)[0] for i in range(6))
    np.testing.assert_allclose(actual,exact(points),atol=1e-12)
    # RT0 derivative tensor b*I cannot simultaneously have diagonal entries3 and4.
    assert 3. != 4.


def test_reference_edge_linear_trace_and_its_integral_use_actual_bdm_basis():
    skfem = pytest.importorskip("skfem")
    element = skfem.ElementTriBDM1()
    points = np.array([[.5-np.sqrt(3)/6,.5+np.sqrt(3)/6],[0.,0.]])
    target = 7.+3*points[0]
    normal_basis = np.column_stack([-element.lbasis(points,i)[0][1] for i in (0,1)])
    coefficients = np.linalg.solve(normal_basis,target)
    np.testing.assert_allclose(normal_basis @ coefficients,target,atol=1e-12)
    assert abs(np.mean(normal_basis @ coefficients)-8.5) < 1e-12
