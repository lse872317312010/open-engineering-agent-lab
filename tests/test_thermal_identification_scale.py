"""Independent absolute-scale ambiguity, frozen before stress-run implementation."""
import numpy as np


def isolated_rates(capacity, conductance, temperature, heat):
    # Independent two-node conservation equation, not the fitted design matrix.
    transfer = conductance*(temperature[0]-temperature[1])
    return (np.asarray(heat)+[-transfer, transfer])/np.asarray(capacity)


def test_unknown_heat_scale_cannot_identify_absolute_c_and_g_from_temperature():
    capacity = np.array([70., 250.])
    conductance = .8
    heat = np.array([11., 4.])
    temperature = np.array([62., 35.])
    expected = isolated_rates(capacity, conductance, temperature, heat)
    for scale in (.2, .5, 2., 5.):
        np.testing.assert_allclose(
            isolated_rates(capacity*scale, conductance*scale, temperature, heat*scale),
            expected, rtol=1e-14, atol=1e-14)
    assert abs(capacity @ expected-heat.sum()) < 1e-12
