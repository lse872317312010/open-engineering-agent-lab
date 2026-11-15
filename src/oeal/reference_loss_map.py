"""Quadratic current-reference copper loss with bilinear speed/resistance coefficients."""
import math

import numpy as np

from oeal.reference_validity import ReferenceSettlingGuard
from oeal.stator_feedback import StatorCopperFeedback
from oeal.stator_rom import _scalar


class ReferenceCopperLossMap:
    KEYS = ("format_version", "resistance_ohm", "speed_abs_rad_s", "copper_coefficients",
            "reference_max_a")

    def __init__(self, data):
        version = np.asarray(data["format_version"]).item()
        if type(version) is not int or version != 1:
            raise ValueError("unsupported reference-loss-map format")
        arrays = {}
        for key in self.KEYS[1:4]:
            raw = np.asarray(data[key])
            if np.iscomplexobj(raw) or raw.dtype.kind not in "fiu":
                raise ValueError("real numeric coefficient arrays required")
            arrays[key] = np.array(raw, dtype=float, copy=True)
            if not np.isfinite(arrays[key]).all():
                raise ValueError("finite coefficient arrays required")
        for key in ("resistance_ohm", "speed_abs_rad_s"):
            grid = arrays[key]
            if grid.ndim != 1 or len(grid) < 2 or grid[0] <= 0 or np.any(np.diff(grid) <= 0):
                raise ValueError("positive increasing map axes required")
        resistance, speed = arrays["resistance_ohm"], arrays["speed_abs_rad_s"]
        coefficients = arrays["copper_coefficients"]
        if coefficients.shape != (2, len(speed), len(resistance), 3):
            raise ValueError("two speed-by-resistance grids of three coefficients required")
        gram = np.zeros(coefficients.shape[:-1]+(2, 2))
        gram[..., 0, 0], gram[..., 1, 1] = coefficients[..., 0], coefficients[..., 2]
        gram[..., 0, 1] = gram[..., 1, 0] = coefficients[..., 1]/2
        if np.min(np.linalg.eigvalsh(gram)) < -1e-12:
            raise ValueError("nonnegative quadratic copper-loss form required")
        maximum = _scalar(np.asarray(data["reference_max_a"]).item(), "maximum reference")
        if not 0 < maximum <= 2:
            raise ValueError("positive current-reference bound required")
        self._resistance, self._speed, self._coefficients = resistance, speed, coefficients
        self._maximum = maximum
        for array in arrays.values():
            array.setflags(write=False)

    @classmethod
    def from_npz(cls, path):
        with np.load(path, allow_pickle=False) as data:
            return cls({key: data[key] for key in cls.KEYS})

    def mean_power(self, resistance_ohm, *, omega_rad_s, iq_reference_a):
        resistance = _scalar(resistance_ohm, "resistance")
        omega = _scalar(omega_rad_s, "speed")
        reference = _scalar(iq_reference_a, "reference")
        direction = 1 if omega > 0 else -1
        speed, amplitude = abs(omega), direction*reference
        if (not self._resistance[0] <= resistance <= self._resistance[-1]
                or not self._speed[0] <= speed <= self._speed[-1]
                or not 0 <= amplitude <= self._maximum):
            raise ValueError("operating point outside frozen reference-loss-map domain")
        upper = min(max(int(np.searchsorted(self._speed, speed, side="right")), 1),
                    len(self._speed)-1)
        lower = upper-1
        weight = (speed-self._speed[lower])/(self._speed[upper]-self._speed[lower])
        grid = self._coefficients[1 if direction > 0 else 0]
        left = np.array([np.interp(resistance, self._resistance, grid[lower, :, j])
                         for j in range(3)])
        right = np.array([np.interp(resistance, self._resistance, grid[upper, :, j])
                          for j in range(3)])
        a, b, c = (1-weight)*left+weight*right
        power = float((a*amplitude+b)*amplitude+c)
        if not np.isfinite(power) or power < 0:
            raise ValueError("finite nonnegative copper power required")
        return power

    def advance_thermal_window(self, feedback, end_tick, *, omega_rad_s, iq_reference_a,
                               guard, control_start_tick, control_end_tick):
        if (not isinstance(feedback, StatorCopperFeedback)
                or not isinstance(guard, ReferenceSettlingGuard)):
            raise ValueError("thermal feedback and reference guard required")
        guard.require_constant_window(control_start_tick, control_end_tick, iq_reference_a)
        start = control_start_tick*guard.period_s
        width = (control_end_tick-control_start_tick)*guard.period_s
        if (not math.isclose(start, feedback.windows*feedback.window_s, rel_tol=0, abs_tol=1e-10)
                or not math.isclose(width, feedback.window_s, rel_tol=0, abs_tol=1e-12)):
            raise ValueError("thermal and observed control windows must align")
        power = self.mean_power(feedback.resistance_ohm, omega_rad_s=omega_rad_s,
                                iq_reference_a=iq_reference_a)
        return feedback.advance_window(end_tick, feedback.copper_j+feedback.window_s*power)
