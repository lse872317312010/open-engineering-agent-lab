"""Truth-free amplitude screening; it does not establish parameter identifiability."""
import numpy as np


def assess_temperature_observations(temperature_c, noise_sigma_k=None):
    """Compare six observed quantile spans with an explicitly supplied noise prior.

    No fit, truth, powers or heldout data are used. Missing noise information
    returns unknown; supported amplitude does not certify a model or sensor.
    """
    temperature = np.asarray(temperature_c, dtype=float)
    if (temperature.ndim != 2 or temperature.shape[1] != 6 or len(temperature) < 100
            or not np.all(np.isfinite(temperature)) or np.min(temperature) <= -273.15):
        raise ValueError("at least 100 finite six-node absolute-temperature samples required")
    quantiles = np.quantile(temperature, [.05, .95], axis=0)
    span = quantiles[1]-quantiles[0]
    result = dict(status="unknown", span_k=span.tolist(), sample_count=len(temperature),
                  noise_source="not_supplied", noise_sigma_k=None, threshold_k=None,
                  insufficient_channels=[], certifies_identifiability=False,
                  policy="P95-P05 > max(6*sigma, 0.05 K), all six channels")
    if noise_sigma_k is None:
        return result
    noise = np.asarray(noise_sigma_k, dtype=float)
    if noise.ndim == 0:
        noise = np.full(6, float(noise))
    if noise.shape != (6,) or not np.all(np.isfinite(noise)) or np.any(noise < 0):
        raise ValueError("noise sigma must be a finite nonnegative scalar or six-vector")
    threshold = np.maximum(6*noise, .05)
    insufficient = np.flatnonzero(span <= threshold).tolist()
    result.update(status="insufficient" if insufficient else "amplitude_supported",
                  noise_source="caller_supplied", noise_sigma_k=noise.tolist(),
                  threshold_k=threshold.tolist(), insufficient_channels=insufficient)
    return result
