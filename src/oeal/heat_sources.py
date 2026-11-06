"""Power-preserving uniform deposition on explicitly supplied region volumes."""
import numpy as np


def loss_windows(times_s, cumulative_j, *, period_s=50e-6, ratio=50):
    """Return endpoint times and integral differences for complete thermal windows."""
    t, e = np.asarray(times_s), np.asarray(cumulative_j)
    if np.iscomplexobj(t) or np.iscomplexobj(e):
        raise ValueError("real times and cumulative energy required")
    t, e = np.asarray(t, dtype=float), np.asarray(e, dtype=float)
    if (type(ratio) is not int or ratio <= 0 or not np.isfinite(period_s) or period_s <= 0
            or t.ndim != 1 or len(t) < 2 or e.shape != t.shape
            or not np.isfinite(t).all() or not np.isfinite(e).all()
            or np.any(e < 0) or np.any(np.diff(e) < 0) or (len(t)-1) % ratio
            or not np.allclose(t, np.arange(len(t))*period_s, rtol=0, atol=1e-12)):
        raise ValueError("complete contiguous clock and nondecreasing loss ledger required")
    return t[::ratio].copy(), np.diff(e[::ratio])


def polygon_area_m2(points):
    raw = np.asarray(points)
    if np.iscomplexobj(raw):
        raise ValueError("real polygon coordinates required")
    p = np.asarray(raw, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < 3 or not np.isfinite(p).all():
        raise ValueError("finite polygon with at least three vertices required")
    area = abs(float(p[:, 0]@np.roll(p[:, 1], -1)-p[:, 1]@np.roll(p[:, 0], -1)))/2
    if area <= 0:
        raise ValueError("positive polygon area required")
    return area


def uniform_volume_source(labels, volumes_m3, power_w):
    """Return W/m³ and per-region W; volumes describe gross heated regions."""
    labels = tuple(labels)
    raw = np.asarray(volumes_m3)
    if np.iscomplexobj(raw) or np.iscomplexobj(power_w):
        raise ValueError("real volumes and power required")
    volumes = np.asarray(raw, dtype=float)
    power = np.asarray(power_w, dtype=float)
    if (not labels or any(not isinstance(s, str) or not s for s in labels)
            or len(set(labels)) != len(labels) or volumes.shape != (len(labels),)
            or not np.isfinite(volumes).all() or np.any(volumes <= 0)
            or power.shape != () or not np.isfinite(power) or power < 0):
        raise ValueError("unique labels, positive finite volumes and nonnegative scalar W required")
    total = float(np.sum(volumes))
    if not np.isfinite(total):
        raise ValueError("finite total volume required")
    density = float(power)/total
    watts = density*volumes
    if not np.isfinite(density) or not np.isfinite(watts).all():
        raise ValueError("finite source density required")
    return density, watts
