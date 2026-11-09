"""NumPy bilinear copper-loss interpolation for fixed-reference motoring operation."""
import math

import numpy as np

from oeal.stator_feedback import StatorCopperFeedback
from oeal.stator_rom import _scalar


class SpeedCopperLossMap:
    KEYS = ("format_version", "resistance_ohm", "speed_abs_rad_s", "mean_copper_w",
            "reference_abs_a")

    def __init__(self, data):
        version = np.asarray(data["format_version"]).item()
        if type(version) is not int or version != 1:
            raise ValueError("unsupported speed-loss-map format")
        arrays = {}
        for key in self.KEYS[1:4]:
            raw = np.asarray(data[key])
            if np.iscomplexobj(raw) or raw.dtype.kind not in "fiu":
                raise ValueError("real numeric loss-map arrays required")
            arrays[key] = np.array(raw, dtype=float, copy=True)
            if not np.isfinite(arrays[key]).all():
                raise ValueError("finite loss-map arrays required")
        for key in ("resistance_ohm", "speed_abs_rad_s"):
            grid = arrays[key]
            if grid.ndim != 1 or len(grid) < 2 or grid[0] <= 0 or np.any(np.diff(grid) <= 0):
                raise ValueError("positive increasing map axes required")
        resistance, speed = arrays["resistance_ohm"], arrays["speed_abs_rad_s"]
        power = arrays["mean_copper_w"]
        if power.shape != (2, len(speed), len(resistance)) or np.any(power <= 0):
            raise ValueError("two positive speed-by-resistance power grids required")
        reference = _scalar(np.asarray(data["reference_abs_a"]).item(), "map reference")
        if not 0 < reference <= 2:
            raise ValueError("positive current reference required")
        self._resistance, self._speed, self._power = resistance, speed, power
        self._reference = reference
        for array in arrays.values():
            array.setflags(write=False)

    @classmethod
    def from_npz(cls, path):
        with np.load(path, allow_pickle=False) as data:
            return cls({key: data[key] for key in cls.KEYS})

    def mean_power(self, resistance_ohm, *, omega_rad_s, iq_reference_a):
        resistance = _scalar(resistance_ohm, "resistance")
        omega = _scalar(omega_rad_s, "speed")
        reference = _scalar(iq_reference_a, "current reference")
        direction = 1 if omega > 0 else -1
        speed = abs(omega)
        if (not self._resistance[0] <= resistance <= self._resistance[-1]
                or not self._speed[0] <= speed <= self._speed[-1]
                or not math.isclose(reference, direction*self._reference,
                                    rel_tol=0, abs_tol=1e-12)):
            raise ValueError("operating point outside frozen speed-loss-map domain")
        upper = min(max(int(np.searchsorted(self._speed, speed, side="right")), 1),
                    len(self._speed)-1)
        lower = upper-1
        weight = (speed-self._speed[lower])/(self._speed[upper]-self._speed[lower])
        power = self._power[1 if direction > 0 else 0]
        left = np.interp(resistance, self._resistance, power[lower])
        right = np.interp(resistance, self._resistance, power[upper])
        return float((1-weight)*left+weight*right)

    def advance_thermal_window(self, feedback, end_tick, *, omega_rad_s, iq_reference_a):
        if not isinstance(feedback, StatorCopperFeedback):
            raise ValueError("StatorCopperFeedback required")
        power = self.mean_power(feedback.resistance_ohm, omega_rad_s=omega_rad_s,
                                iq_reference_a=iq_reference_a)
        return feedback.advance_window(end_tick, feedback.copper_j+feedback.window_s*power)
