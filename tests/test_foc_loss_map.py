"""Independent interpolation arithmetic and strict operating-domain rejection."""
import numpy as np
import pytest

from oeal.foc_loss_map import FixedSpeedCopperLossMap
from oeal.stator_feedback import StatorCopperFeedback


def data():
    return dict(format_version=1, resistance_ohm=[.3, .36, .42],
                mean_copper_w=[[.1, .2, .3], [.11, .22, .33]],
                omega_abs_rad_s=10., reference_abs_a=.5)


def test_direction_rows_interpolate_and_preserve_anchors():
    model = FixedSpeedCopperLossMap(data())
    assert model.mean_power(.33, omega_rad_s=-10., iq_reference_a=-.5) == pytest.approx(.15)
    assert model.mean_power(.33, omega_rad_s=10., iq_reference_a=.5) == pytest.approx(.165)
    assert model.mean_power(.42, omega_rad_s=10., iq_reference_a=.5) == pytest.approx(.33)


@pytest.mark.parametrize("resistance,speed,current", [(.299, 10., .5), (.421, 10., .5),
    (.3, 9., .5), (.3, 10., -.5), (.3, 0., .5), (.3, 10., .6),
    (float("nan"), 10., .5), (True, 10., .5), (.3, float("inf"), .5)])
def test_unsupported_point_is_rejected(resistance, speed, current):
    model = FixedSpeedCopperLossMap(data())
    with pytest.raises(ValueError):
        model.mean_power(resistance, omega_rad_s=speed, iq_reference_a=current)


@pytest.mark.parametrize("key,value", [("format_version", True),
    ("resistance_ohm", [.3, .3, .42]), ("mean_copper_w", [[.1, .2, float("nan")]]),
    ("mean_copper_w", [[.1j, .2, .3], [.1, .2, .3]]), ("omega_abs_rad_s", -1.)])
def test_bad_packet_is_rejected(key, value):
    values = data()
    values[key] = value
    with pytest.raises(ValueError):
        FixedSpeedCopperLossMap(values)


def test_input_arrays_are_copied():
    values = data()
    values["mean_copper_w"] = np.array(values["mean_copper_w"])
    model = FixedSpeedCopperLossMap(values)
    values["mean_copper_w"][:] = 99
    assert model.mean_power(.3, omega_rad_s=-10., iq_reference_a=-.5) == pytest.approx(.1)


def test_mapped_window_matches_two_node_heat_solution_and_rejects_without_advancing():
    packet = dict(format_version=1, mass=[[2., 0.], [0., 3.]],
                  bulk=[[1., -1.], [-1., 1.]], convection=[[0., 0.], [0., 1.]],
                  forcing=[1., 0.], observations=[[1., 0.], [0., 1.], [2., 3.], [0., 1.]],
                  h_bounds=[5., 80.], power_bounds_w=[0., 2.], ambient_c=25.)
    thermal = StatorCopperFeedback(packet, h_w_m2_k=5., drive_dt_s=.1,
                                   ticks_per_window=10, ambient_c=25.)
    model = FixedSpeedCopperLossMap(data())
    output = model.advance_thermal_window(thermal, 10, omega_rad_s=10., iq_reference_a=.5)
    np.testing.assert_allclose(output, [25+.11*9/26, 25+.11/26, .11*21/26, .11*5/26],
                               atol=1e-14)
    before = thermal.state
    with pytest.raises(ValueError):
        model.advance_thermal_window(thermal, 20, omega_rad_s=11., iq_reference_a=.5)
    np.testing.assert_array_equal(thermal.state, before)
    assert thermal.windows == 1 and thermal.copper_j == pytest.approx(.11)
