"""Independent bilinear arithmetic, bounds and transactional thermal application."""
import numpy as np
import pytest

from oeal.speed_loss_map import SpeedCopperLossMap
from oeal.stator_feedback import StatorCopperFeedback


def packet():
    resistance = np.array([.3, .36, .42])
    speed = np.array([10., 20., 40.])
    power = np.array([[[a+2*r+.03*v+.1*r*v for r in resistance] for v in speed]
                      for a in (.1, .2)])
    return dict(format_version=1, resistance_ohm=resistance, speed_abs_rad_s=speed,
                mean_copper_w=power, reference_abs_a=.5)


def test_bilinear_interior_and_boundary_values():
    model = SpeedCopperLossMap(packet())
    assert model.mean_power(.33, omega_rad_s=15., iq_reference_a=.5) == pytest.approx(1.805)
    assert model.mean_power(.33, omega_rad_s=-15., iq_reference_a=-.5) == pytest.approx(1.705)
    assert model.mean_power(.42, omega_rad_s=40., iq_reference_a=.5) == pytest.approx(3.92)


@pytest.mark.parametrize("r,v,i", [(.299, 20., .5), (.421, 20., .5), (.33, 9., .5),
    (.33, 41., .5), (.33, -20., .5), (.33, 20., .4), (float("nan"), 20., .5),
    (.33, float("inf"), .5), (True, 20., .5)])
def test_no_extrapolation_or_invalid_input(r, v, i):
    with pytest.raises(ValueError):
        SpeedCopperLossMap(packet()).mean_power(r, omega_rad_s=v, iq_reference_a=i)


@pytest.mark.parametrize("key,value", [("format_version", True),
    ("speed_abs_rad_s", [10., 10., 40.]), ("resistance_ohm", [.3, .2, .42]),
    ("mean_copper_w", np.ones((2, 2, 2))), ("reference_abs_a", float("nan"))])
def test_bad_packet_rejected(key, value):
    data = packet()
    data[key] = value
    with pytest.raises(ValueError):
        SpeedCopperLossMap(data)


def test_thermal_energy_hand_calculation_and_rejection_keeps_state():
    data = dict(format_version=1, mass=[[2., 0.], [0., 3.]],
                bulk=[[1., -1.], [-1., 1.]], convection=[[0., 0.], [0., 1.]],
                forcing=[1., 0.], observations=[[1., 0.], [0., 1.], [2., 3.], [0., 1.]],
                h_bounds=[5., 80.], power_bounds_w=[0., 2.], ambient_c=25.)
    feedback = StatorCopperFeedback(data, h_w_m2_k=5., drive_dt_s=.1,
                                    ticks_per_window=10, ambient_c=25.)
    model = SpeedCopperLossMap(packet())
    output = model.advance_thermal_window(feedback, 10, omega_rad_s=10., iq_reference_a=.5)
    np.testing.assert_allclose(output, [25+1.4*9/26, 25+1.4/26, 1.4*21/26, 1.4*5/26],
                               atol=1e-14)
    before = feedback.state
    with pytest.raises(ValueError):
        model.advance_thermal_window(feedback, 20, omega_rad_s=41., iq_reference_a=.5)
    np.testing.assert_array_equal(feedback.state, before)
    assert feedback.windows == 1
