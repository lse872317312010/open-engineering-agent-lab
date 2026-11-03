"""Independent annular-sector geometry and axial scaling references (SI)."""
import math

import numpy as np


def sector_area(inner_m, outer_m, angle_rad):
    if (not all(math.isfinite(x) for x in (inner_m, outer_m, angle_rad))
            or not 0 <= inner_m < outer_m or not 0 < angle_rad <= 2*math.pi):
        raise ValueError("invalid SI annular sector")
    return angle_rad*(outer_m**2-inner_m**2)/2


def reference(raw):
    s, r = raw["stator"], raw["rotor"]
    slot = s["slot"]
    assert slot["H0"] == 0 and slot["W0"] == slot["W2"]
    slot_area = sector_area(s["Rint"], s["Rint"]+slot["H2"], slot["W2"])
    mag_area = sector_area(r["Rext"], r["Rext"]+r["slot"]["H0"],
                           2*math.pi/r["slot"]["Zs"])
    return dict(slot_m2=slot_area, magnet_m2=mag_area,
                winding_m2=slot_area*slot["Zs"], magnets_m2=mag_area*r["slot"]["Zs"],
                stator_core_m2=math.pi*(s["Rext"]**2-s["Rint"]**2)-slot_area*slot["Zs"],
                rotor_core_m2=math.pi*(r["Rext"]**2-r["Rint"]**2),
                gap_m=s["Rint"]-r["Rext"]-r["slot"]["H0"])


def physical_depth(value, length_m, native_depth_m):
    if (not math.isfinite(length_m) or not math.isfinite(native_depth_m)
            or min(length_m, native_depth_m) <= 0):
        raise ValueError("positive finite lengths required")
    a = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(a)):
        raise ValueError("nonfinite field quantity")
    return a*length_m/native_depth_m


def polygon_area(points):
    p = np.asarray(points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < 3 or not np.all(np.isfinite(p)):
        raise ValueError("invalid polygon")
    return abs(float(p[:, 0] @ np.roll(p[:, 1], -1)
                     -p[:, 1] @ np.roll(p[:, 0], -1)))/2
