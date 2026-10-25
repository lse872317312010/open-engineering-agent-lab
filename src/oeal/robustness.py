"""Independent time-domain summaries for fixed joint campaigns."""

import numpy as np


def tracking_metrics(times, actual, reference, *, duration_s, hold_start_s=0.5):
    """Piecewise-linear quadrature; reject incomplete or invalid time domains."""
    t, q, ref = (np.asarray(x, dtype=float) for x in (times, actual, reference))
    if (t.ndim != 1 or len(t) < 2 or q.shape != t.shape or ref.shape != t.shape
            or not all(np.all(np.isfinite(x)) for x in (t, q, ref))
            or np.any(np.diff(t) <= 0) or abs(t[0]) > 1e-12
            or abs(t[-1] - duration_s) > 1e-12
            or not 0 <= hold_start_s < duration_s):
        raise ValueError("invalid, nonfinite or incomplete joint trajectory")
    error = q - ref
    dt = np.diff(t)
    absolute = np.abs(error)
    iae = float(np.sum(dt * (absolute[:-1] + absolute[1:]) / 2))
    square = error ** 2
    rmse = float(np.sqrt(np.sum(dt * (square[:-1] + square[1:]) / 2) / duration_s))
    # Include the interpolated boundary even if it is not a sampling instant.
    hold = np.r_[np.interp(hold_start_s, t, absolute), absolute[t >= hold_start_s]]
    return dict(position_iae_rad_s=iae, position_rmse_rad=rmse,
                hold_max_error_rad=float(hold.max()))


def aligned_difference(left, right):
    """Compare common physical instants; neither input is designated truth."""
    lt, lq = np.asarray(left, dtype=float).T
    rt, rq = np.asarray(right, dtype=float).T
    for t, q in ((lt, lq), (rt, rq)):
        tracking_metrics(t, q, q, duration_s=1.0)
    return float(np.max(np.abs(lq - np.interp(lt, rt, rq))))
