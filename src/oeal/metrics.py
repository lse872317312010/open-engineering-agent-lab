"""Independent acceptance metrics calculated from sampled arrays."""

import math

import numpy as np


def current_step_metrics(samples, step_time_s, target_a, voltage_limit_v):
    data = np.asarray(samples, dtype=float)
    if data.ndim != 2 or data.shape[1] != 13 or not np.all(np.isfinite(data)):
        raise ValueError("expected finite FOC trace with 13 columns")
    if len(data) < 2 or np.any(np.diff(data[:, 0]) <= 0):
        raise ValueError("time samples must strictly increase")
    if not all(math.isfinite(x) for x in (step_time_s, target_a, voltage_limit_v)):
        raise ValueError("metric parameters must be finite")
    if target_a <= 0 or voltage_limit_v <= 0:
        raise ValueError("positive target and voltage limit required")
    active = data[data[:, 0] >= step_time_s - 1e-14]
    if len(active) < 2:
        raise ValueError("step has insufficient samples")
    tail = active[-max(2, len(active) // 10):]
    error = np.abs(active[:, 2] - target_a)
    bad = np.flatnonzero(error > 0.02 * target_a)
    settled_index = int(bad[-1] + 1) if bad.size else 0
    settling = (
        float(active[settled_index, 0] - step_time_s)
        if settled_index < len(active) else None
    )
    # Last sample is the state endpoint, not a new control action.
    intervals = np.diff(data[:, 0])
    return {
        "steady_error_a": float(abs(tail[:, 2].mean() - target_a)),
        "overshoot_a": float(max(0, active[:, 2].max() - target_a)),
        "settling_time_s": settling,
        "peak_abs_id_a": float(np.abs(active[:, 1]).max()),
        "voltage_violation_count": int(np.count_nonzero(
            np.hypot(data[:-1, 5], data[:-1, 6]) > voltage_limit_v + 1e-10
        )),
        "saturation_duration_s": float(np.sum(intervals * data[:-1, 12])),
    }


def b1_passes(metrics):
    return (
        metrics["steady_error_a"] <= 0.05
        and metrics["overshoot_a"] <= 0.5
        and metrics["settling_time_s"] is not None
        and metrics["settling_time_s"] <= 0.005
        and metrics["voltage_violation_count"] == 0
    )
