"""NumPy-only mean copper-loss interpolation for one fixed-speed FOC operating line."""
import math

import numpy as np

from oeal.stator_feedback import StatorCopperFeedback
from oeal.stator_rom import _scalar


class FixedSpeedCopperLossMap:
    KEYS = ("format_version", "resistance_ohm", "mean_copper_w", "omega_abs_rad_s",
            "reference_abs_a")

    def __init__(self, data):
        version = np.asarray(data["format_version"]).item()
        if type(version) is not int or version != 1:
            raise ValueError("unsupported loss-map format")
        arrays = {}
        for key in ("resistance_ohm", "mean_copper_w"):
            raw = np.asarray(data[key])
            if np.iscomplexobj(raw) or raw.dtype.kind not in "fiu":
                raise ValueError("real numeric loss-map arrays required")
            arrays[key] = np.array(raw, dtype=float, copy=True)
            if not np.isfinite(arrays[key]).all():
                raise ValueError("finite loss-map arrays required")
        resistance, power = arrays["resistance_ohm"], arrays["mean_copper_w"]
        if (resistance.ndim != 1 or len(resistance) < 2 or resistance[0] <= 0
                or np.any(np.diff(resistance) <= 0) or power.shape != (2, len(resistance))
                or np.any(power <= 0)):
            raise ValueError("increasing resistance grid and two positive direction rows required")
        speed = _scalar(np.asarray(data["omega_abs_rad_s"]).item(), "map speed")
        reference = _scalar(np.asarray(data["reference_abs_a"]).item(), "map reference")
        if speed <= 0 or not 0 < reference <= 2:
            raise ValueError("positive fixed speed and current reference required")
        self._resistance, self._power = resistance, power
        self._speed, self._reference = speed, reference
        resistance.setflags(write=False)
        power.setflags(write=False)

    @classmethod
    def from_npz(cls, path):
        with np.load(path, allow_pickle=False) as data:
            return cls({key: data[key] for key in cls.KEYS})

    def mean_power(self, resistance_ohm, *, omega_rad_s, iq_reference_a):
        resistance = _scalar(resistance_ohm, "resistance")
        omega = _scalar(omega_rad_s, "speed")
        reference = _scalar(iq_reference_a, "current reference")
        direction = 1 if omega > 0 else -1
        if (not math.isclose(abs(omega), self._speed, rel_tol=0, abs_tol=1e-10)
                or not math.isclose(reference, direction*self._reference, rel_tol=0, abs_tol=1e-12)
                or not self._resistance[0] <= resistance <= self._resistance[-1]):
            raise ValueError("operating point outside frozen loss-map domain")
        row = self._power[1 if direction > 0 else 0]
        return float(np.interp(resistance, self._resistance, row))

    def advance_thermal_window(self, feedback, end_tick, *, omega_rad_s, iq_reference_a):
        if not isinstance(feedback, StatorCopperFeedback):
            raise ValueError("StatorCopperFeedback required")
        power = self.mean_power(feedback.resistance_ohm, omega_rad_s=omega_rad_s,
                                iq_reference_a=iq_reference_a)
        return feedback.advance_window(end_tick, feedback.copper_j+feedback.window_s*power)
