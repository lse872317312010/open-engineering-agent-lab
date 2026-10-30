"""Independent pulse/modal limits, before transient FE implementation."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))


def test_raised_cosine_integral_and_off_phase():
    pytest.importorskip("scipy")
    from p7_transient_reference import pulse, pulse_integral

    np.testing.assert_allclose(pulse([0, 4, 8, 12]), [0, 1, 0, 0], atol=1e-15)
    np.testing.assert_allclose(pulse_integral([0, 4, 8, 12]), [0, 2, 4, 4], atol=1e-15)


def test_scalar_modal_against_independent_quadrature():
    pytest.importorskip("scipy")
    from p7_transient_reference import modal_response, pulse
    from scipy.integrate import quad

    for rate in (.2, 2., 20.):
        times = np.array([0., .1, 2., 8., 12., 16.])
        actual = modal_response([rate], [3.], times)[:, 0]
        expected = [quad(lambda s:3*np.exp(-rate*(t-s))*float(pulse(s)),
                         0, min(t, 8), epsabs=1e-12)[0] for t in times]
        np.testing.assert_allclose(actual, expected, rtol=1e-9, atol=1e-12)


def test_nonpositive_modal_rate_rejected():
    pytest.importorskip("scipy")
    from p7_transient_reference import modal_response

    with pytest.raises(ValueError, match="positive"):
        modal_response([0.], [1.], [0., 1.])
