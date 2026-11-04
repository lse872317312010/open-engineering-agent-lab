"""Open-circuit frame fitting using existing amplitude-invariant transforms."""
import math

import numpy as np

from oeal.transforms import clarke


def fit_frame(angles, flux):
    angles = np.asarray(angles, dtype=float)
    flux = np.asarray(flux, dtype=float)
    if (angles.ndim != 1 or len(angles) < 3 or flux.shape != (len(angles), 3)
            or not np.isfinite(angles).all() or not np.isfinite(flux).all()):
        raise ValueError("finite mechanical angles and Nx3 flux required")
    ab = np.array([clarke(*row) for row in flux])
    z = ab[:, 0] + 1j*ab[:, 1]
    forward = complex(np.mean(z*np.exp(-4j*angles)))
    reverse = complex(np.mean(z*np.exp(4j*angles)))
    if abs(forward) <= .01 or abs(forward) < 5*abs(reverse):
        raise ValueError("positive four-pole-pair fundamental not supported")
    return dict(pole_pairs=4, offset_rad=math.atan2(forward.imag, forward.real),
                amplitude_wb=abs(forward), reverse_amplitude_wb=abs(reverse))
