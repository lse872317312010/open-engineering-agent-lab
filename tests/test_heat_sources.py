"""Independent geometry, power and failure references for spatial heat sources."""
import numpy as np
import pytest

from oeal.heat_sources import loss_windows, polygon_area_m2, uniform_volume_source


def test_windows_use_integrals_and_remove_initial_ledger_offset():
    times = np.arange(101)*50e-6
    endpoints, energy = loss_windows(times, 2.+times**2/2)
    np.testing.assert_allclose(endpoints, [0., .0025, .005], atol=1e-18)
    np.testing.assert_allclose(energy, [3.125e-6, 9.375e-6], atol=1e-15)


@pytest.mark.parametrize("fault", ["missing", "time", "decreased", "partial"])
def test_invalid_ledger_is_rejected(fault):
    times, energy = np.arange(101)*50e-6, np.arange(101)*1e-6
    if fault == "missing":
        times, energy = np.delete(times, 20), np.delete(energy, 20)
    elif fault == "time":
        times[20] += 1e-6
    elif fault == "decreased":
        energy[20] = 0
    else:
        times, energy = times[:-1], energy[:-1]
    with pytest.raises(ValueError):
        loss_windows(times, energy)


def test_rectangle_area_orientation_translation_and_power_integral():
    rectangle = np.array([[0., 0.], [2., 0.], [2., 3.], [0., 3.]])
    assert polygon_area_m2(rectangle) == pytest.approx(6.)
    assert polygon_area_m2(rectangle[::-1]+[4., -7.]) == pytest.approx(6.)
    density, watts = uniform_volume_source(["small", "large"], [.02, .06], 8.)
    assert density == pytest.approx(100.)
    np.testing.assert_allclose(watts, [2., 6.])
    assert sum(watts)*.0025 == pytest.approx(.02)
    density, watts = uniform_volume_source(["cooling"], [.02], 0.)
    assert density == 0 and watts[0] == 0


@pytest.mark.parametrize("labels,volumes,power", [
    (["a", "a"], [1., 1.], 1.), (["a"], [0.], 1.),
    (["a"], [-1.], 1.), (["a"], [float("nan")], 1.),
    (["a"], [1.], -1.), (["a"], [1.], float("inf")),
    (["a"], [1.], [1.]), (["a"], [1j], 1.), ([], [], 1.),
])
def test_invalid_region_or_power_is_rejected(labels, volumes, power):
    with pytest.raises(ValueError):
        uniform_volume_source(labels, volumes, power)


@pytest.mark.parametrize("points", [[], [[0, 0], [1, 1]],
                                   [[0, 0], [1, 1], [2, 2]],
                                   [[0, 0], [1, 0], [0, float("nan")]]])
def test_invalid_polygon_is_rejected(points):
    with pytest.raises(ValueError):
        polygon_area_m2(points)
