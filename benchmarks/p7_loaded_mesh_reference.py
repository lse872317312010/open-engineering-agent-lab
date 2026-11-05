"""Frozen three-mesh budgets; non-monotone differences remain visible."""
import numpy as np


def compare(flux, torque, nodes):
    flux = np.asarray(flux, dtype=float)
    torque = np.asarray(torque, dtype=float)
    nodes = np.asarray(nodes, dtype=float)
    if (flux.shape != (3, 2) or torque.shape != (3,) or nodes.shape != (3,)
            or not all(np.isfinite(x).all() for x in (flux, torque, nodes))
            or np.any(nodes <= 0)):
        raise ValueError("three finite mesh results and positive node counts required")
    df = np.linalg.norm(np.diff(flux, axis=0), axis=1)/.05
    dt = np.abs(np.diff(torque))
    return dict(flux_diff=df.tolist(), torque_diff_nm=dt.tolist(),
                nodes_increasing=bool(nodes[0] < nodes[1] < nodes[2]),
                flux_monotone=bool(df[1] <= df[0]), torque_monotone=bool(dt[1] <= dt[0]),
                passed=bool(nodes[0] < nodes[1] < nodes[2] and df[1] <= .03 and dt[1] <= .05))
