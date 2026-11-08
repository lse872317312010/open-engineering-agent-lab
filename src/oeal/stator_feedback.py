"""Causal copper-energy windows and synthetic winding-temperature resistance feedback."""
import copy
from dataclasses import dataclass
from numbers import Integral

import numpy as np

from oeal.stator_rom import StatorThermalROM, _scalar


@dataclass(frozen=True)
class CopperResistanceLaw:
    reference_ohm: float = .3
    reference_c: float = 25.
    coefficient_per_k: float = .004
    minimum_c: float = 0.
    maximum_c: float = 125.

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _scalar(getattr(self, name), name))
        if (self.reference_ohm <= 0 or self.coefficient_per_k < 0
                or not self.minimum_c <= self.reference_c <= self.maximum_c
                or self.minimum_c >= self.maximum_c
                or 1+self.coefficient_per_k*(self.minimum_c-self.reference_c) <= 0):
            raise ValueError("positive resistance over a valid temperature domain required")

    def resistance(self, temperature_c):
        temperature = _scalar(temperature_c, "winding temperature")
        if not self.minimum_c <= temperature <= self.maximum_c:
            raise ValueError("winding temperature outside resistance domain")
        value = self.reference_ohm*(1+self.coefficient_per_k*(temperature-self.reference_c))
        if not np.isfinite(value) or value <= 0:
            raise ValueError("finite positive resistance required")
        return value


class StatorCopperFeedback:
    """Advance exactly one completed window; its new R belongs to the next window."""

    def __init__(self, bundle, *, h_w_m2_k, drive_dt_s, ticks_per_window, ambient_c,
                 law=None):
        drive_dt = _scalar(drive_dt_s, "drive timestep")
        if (isinstance(ticks_per_window, (bool, np.bool_))
                or not isinstance(ticks_per_window, Integral) or ticks_per_window <= 0
                or drive_dt <= 0):
            raise ValueError("positive timestep and integer window ticks required")
        if law is not None and not isinstance(law, CopperResistanceLaw):
            raise ValueError("CopperResistanceLaw required")
        self._law = CopperResistanceLaw() if law is None else law
        self._ambient = _scalar(ambient_c, "ambient temperature")
        self._resistance = self._law.resistance(self._ambient)
        self._bundle_ambient = _scalar(np.asarray(bundle["ambient_c"]).item(), "bundle ambient")
        self._dt = drive_dt*int(ticks_per_window)
        self._model = StatorThermalROM(bundle, h_w_m2_k=h_w_m2_k, dt_s=self._dt)
        self._ticks = int(ticks_per_window)
        self._window = 0
        self._copper_j = self._boundary_j = 0.
        self._outputs = np.array([self._ambient, self._ambient, 0., 0.])

    @classmethod
    def from_npz(cls, path, **kwargs):
        with np.load(path, allow_pickle=False) as data:
            return cls({key: data[key] for key in StatorThermalROM.KEYS}, **kwargs)

    @property
    def resistance_ohm(self):
        return self._resistance

    @property
    def state(self):
        return self._model.state

    @property
    def outputs(self):
        return self._outputs.copy()

    @property
    def windows(self):
        return self._window

    @property
    def copper_j(self):
        return self._copper_j

    @property
    def boundary_j(self):
        return self._boundary_j

    @property
    def balance_j(self):
        return self._copper_j-self._boundary_j-self._outputs[2]

    def advance_window(self, end_drive_tick, cumulative_copper_j):
        if (isinstance(end_drive_tick, (bool, np.bool_))
                or not isinstance(end_drive_tick, Integral)
                or end_drive_tick != (self._window+1)*self._ticks):
            raise ValueError("exact next completed window tick required")
        energy = _scalar(cumulative_copper_j, "cumulative copper energy")
        if energy < self._copper_j:
            raise ValueError("copper energy must not decrease")
        power = (energy-self._copper_j)/self._dt
        # step_average replaces its state only; a shallow candidate shares read-only operators.
        candidate = copy.copy(self._model)
        outputs = candidate.step_average(power)
        outputs[:2] += self._ambient-self._bundle_ambient
        resistance = self._law.resistance(float(outputs[0]))
        boundary = self._boundary_j+self._dt*outputs[3]
        if not np.isfinite(boundary):
            raise ValueError("finite cumulative boundary energy required")
        self._model, self._outputs = candidate, outputs
        self._resistance = resistance
        self._copper_j, self._boundary_j = energy, boundary
        self._window += 1
        return outputs.copy()
