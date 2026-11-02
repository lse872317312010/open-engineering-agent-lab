"""Analytic diagonal CN reference and transactional domain rejection."""
import numpy as np
import pytest

from oeal.thermal_rom import AffineThermalROM


def bundle():
    return dict(format_version=np.array(1), mass=np.diag([2., 3.]),
                bulk_stiffness=np.diag([1., 2.]), contact_stiffness=np.diag([4., 5.]),
                forcing=np.diag([2., 3.]), observations=np.ones((6, 2)),
                rc_bounds=np.array([.01, 1.]), reference_rc=np.array(.1),
                ambient_c=np.array(25.))


@pytest.mark.parametrize("rc", [.01, .03, .1, 1.])
def test_affine_cn_against_diagonal_scalar_reference(rc):
    data = bundle()
    dt = .025
    model = AffineThermalROM(data, rc=rc, dt_s=dt)
    rates = (np.array([1., 2.])+.1/rc*np.array([4., 5.]))/np.array([2., 3.])
    expected = dt*.5/(1+dt*rates/2)
    output = model.step([1., 1.])
    np.testing.assert_allclose(model.state, expected, atol=1e-14)
    np.testing.assert_allclose(output[:4], 25+expected.sum(), atol=1e-14)
    assert output[4] == pytest.approx(expected.sum()*.1/rc)
    assert output[5] == pytest.approx(expected.sum())


@pytest.mark.parametrize("rc", [.005, 2., 0., -1., np.nan, np.inf, True])
def test_unsupported_contact_is_rejected_before_stepping(rc):
    with pytest.raises((ValueError, TypeError)):
        AffineThermalROM(bundle(), rc=rc, dt_s=.025)


@pytest.mark.parametrize("value", [[np.nan, 0.], [-1., 0.], [3., 0.], [1.]])
def test_bad_input_leaves_state_unchanged(value):
    model = AffineThermalROM(bundle(), rc=.1, dt_s=.025)
    model.step([1., .5])
    previous = model.state
    with pytest.raises((ValueError, TypeError)):
        model.step(value)
    np.testing.assert_array_equal(model.state, previous)
