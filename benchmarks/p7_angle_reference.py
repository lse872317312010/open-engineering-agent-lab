"""Periodic central-difference back EMF from uniformly sampled mechanical angles."""
import math

import numpy as np


def periodic_back_emf(flux_wb, speed_rad_s, period_rad=math.pi / 2):
    """Return -omega*d(lambda)/d(theta) for a uniform, endpoint-excluded cycle."""
    flux = np.asarray(flux_wb, dtype=float)
    speed = float(speed_rad_s)
    period = float(period_rad)
    if (flux.ndim != 2 or flux.shape[0] < 3 or flux.shape[1] != 3
            or not np.isfinite(flux).all() or not math.isfinite(speed)
            or not math.isfinite(period) or period <= 0):
        raise ValueError("expected finite Nx3 flux, finite speed and positive period")
    h = period / flux.shape[0]
    return -speed * (np.roll(flux, -1, axis=0) - np.roll(flux, 1, axis=0)) / (2 * h)
