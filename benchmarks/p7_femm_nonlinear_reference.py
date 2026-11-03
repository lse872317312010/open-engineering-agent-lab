"""Independent material-node reference and bounded bilinear flux map."""
import numpy as np

BH = np.array([[0, 0], [.25, 200], [.5, 400], [.75, 600], [1, 800],
               [1.1, 1000], [1.2, 1600], [1.3, 3000], [1.4, 6000],
               [1.5, 12000], [1.6, 24000], [1.8, 80000], [2, 200000],
               [2.5, 600000], [3, 1000000]], dtype=float)


def material_node(b):
    """Only tabulated nodes have an independently declared exact H here."""
    idx = np.flatnonzero(np.isclose(BH[:, 0], abs(b), rtol=0, atol=1e-12))
    if len(idx) != 1:
        raise ValueError("reference only defined at explicit BH nodes")
    return np.copysign(BH[idx[0], 1], b)


def interpolate(axis, values, d, q):
    """Bounded bilinear interpolation; final axes are (d,q,components)."""
    axis, values = np.asarray(axis, dtype=float), np.asarray(values, dtype=float)
    if (axis.ndim != 1 or len(axis) < 2 or not np.all(np.isfinite(axis))
            or np.any(np.diff(axis) <= 0) or values.shape != (len(axis), len(axis), 2)
            or not np.all(np.isfinite(values)) or not np.isfinite(d) or not np.isfinite(q)
            or min(d, q) < axis[0] or max(d, q) > axis[-1]):
        raise ValueError("invalid or out-of-domain flux map request")
    i = min(int(np.searchsorted(axis, d, side="right"))-1, len(axis)-2)
    j = min(int(np.searchsorted(axis, q, side="right"))-1, len(axis)-2)
    u, v = (d-axis[i])/(axis[i+1]-axis[i]), (q-axis[j])/(axis[j+1]-axis[j])
    return ((1-u)*(1-v)*values[i, j]+u*(1-v)*values[i+1, j]
            +(1-u)*v*values[i, j+1]+u*v*values[i+1, j+1])
