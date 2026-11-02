"""External POD column layout and mass inner product, before ROM implementation."""
import numpy as np
import pytest


def test_pymor_mass_pod_column_layout_and_full_rank_projection():
    pytest.importorskip("pymor")
    from pymor.algorithms.pod import pod
    from pymor.operators.numpy import NumpyMatrixOperator
    from pymor.vectorarrays.numpy import NumpyVectorSpace

    mass = np.diag([2., 3., 5.])
    snapshots = np.array([[1., 0., 0., 1.], [0., 2., 0., 2.], [0., 0., 3., 3.]])
    space = NumpyVectorSpace(3)
    vectors = space.from_numpy(snapshots)
    np.testing.assert_array_equal(vectors.to_numpy(), snapshots)
    modes, singular = pod(vectors, product=NumpyMatrixOperator(mass), modes=3, rtol=1e-12)
    basis = modes.to_numpy()
    assert basis.shape == (3, 3) and len(singular) == 3
    np.testing.assert_allclose(basis.T@mass@basis, np.eye(3), atol=1e-10)
    np.testing.assert_allclose(basis@(basis.T@mass@snapshots), snapshots, atol=1e-10)


def test_pymor_region_test_vectors_survive_orthogonalization():
    pytest.importorskip("pymor")
    from pymor.algorithms.gram_schmidt import gram_schmidt
    from pymor.operators.numpy import NumpyMatrixOperator
    from pymor.vectorarrays.numpy import NumpyVectorSpace

    mass = np.diag([2., 3., 5.])
    vectors = np.array([[1., 0., 1.], [1., 0., -1.], [0., 1., 1.]])
    basis = gram_schmidt(NumpyVectorSpace(3).from_numpy(vectors),
                         product=NumpyMatrixOperator(mass)).to_numpy()
    for indicator in vectors[:, :2].T:
        np.testing.assert_allclose(basis@(basis.T@mass@indicator), indicator, atol=1e-12)
