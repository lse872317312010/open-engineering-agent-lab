"""Independent quantile and noise-only references for observation amplitude screening."""
import numpy as np
import pytest

from oeal.thermal_observation import assess_temperature_observations


def test_uniform_quantile_span_and_declared_noise_threshold():
    temperature = np.repeat(np.linspace(20., 30., 1001)[:, None], 6, axis=1)
    result = assess_temperature_observations(temperature, .1)
    np.testing.assert_allclose(result["span_k"], 9., atol=1e-12)
    assert result["status"] == "amplitude_supported"
    np.testing.assert_allclose(result["threshold_k"], .6)


def test_noise_alone_is_insufficient_even_when_matrix_could_be_full_rank():
    noise = np.array([.02,.1,.5,.03,.2,.05])
    temperature = 25.+np.random.default_rng(20261029).normal(size=(24001,6))*noise
    result = assess_temperature_observations(temperature, noise)
    assert result["status"] == "insufficient"
    assert result["insufficient_channels"] == list(range(6))


def test_cooling_needs_no_power_and_bias_cannot_be_detected_by_span():
    cooling = 25.+np.exp(-np.linspace(0., 5., 1001))[:, None]*np.arange(1.,7.)
    result = assess_temperature_observations(cooling, .02)
    shifted = assess_temperature_observations(cooling+2., .02)
    assert result["status"] == shifted["status"] == "amplitude_supported"
    np.testing.assert_allclose(result["span_k"], shifted["span_k"], atol=1e-12)


def test_unknown_noise_is_not_silently_zero_and_zero_noise_has_a_floor():
    packet = np.full((1000,6), 25.)
    assert assess_temperature_observations(packet)["status"] == "unknown"
    result = assess_temperature_observations(packet, 0.)
    assert result["status"] == "insufficient"
    assert result["threshold_k"] == [.05]*6


@pytest.mark.parametrize("noise", [-1., float("nan"), [0.]*5, [0.,0.,0.,0.,0.,-1.]])
def test_invalid_noise_rejected(noise):
    with pytest.raises(ValueError):
        assess_temperature_observations(np.full((1000,6), 25.), noise)


def test_missing_sensor_and_short_record_rejected():
    packet = np.full((1000,6), 25.)
    packet[3,2] = np.nan
    with pytest.raises(ValueError):
        assess_temperature_observations(packet, .02)
    with pytest.raises(ValueError):
        assess_temperature_observations(np.full((99,6), 25.), .02)
