"""Consecutive reference observations and conservative settling-window eligibility."""
import math
from numbers import Integral

from oeal.stator_rom import _scalar


class ReferenceSettlingGuard:
    def __init__(self, *, period_s, settling_s=.02, maximum_slew_a_s=2., maximum_abs_a=.5):
        self._period = _scalar(period_s, "control period")
        settling = _scalar(settling_s, "settling time")
        self._slew = _scalar(maximum_slew_a_s, "maximum reference slew")
        self._maximum = _scalar(maximum_abs_a, "maximum reference")
        if min(self._period, settling, self._slew, self._maximum) <= 0:
            raise ValueError("positive validity parameters required")
        self._settling = math.ceil(settling/self._period)
        self._tick, self._reference = -1, None
        self._ready_after, self._last_change = self._settling, 0

    @property
    def period_s(self):
        return self._period

    @property
    def last_tick(self):
        return self._tick

    @property
    def reference_a(self):
        return self._reference

    @property
    def ready_after_tick(self):
        return self._ready_after

    def observe(self, control_tick, reference_a):
        reference = _scalar(reference_a, "current reference")
        if (isinstance(control_tick, bool) or not isinstance(control_tick, Integral)
                or control_tick != self._tick+1 or abs(reference) > self._maximum):
            raise ValueError("consecutive integer control tick and supported reference required")
        ready, changed = self._ready_after, self._last_change
        if self._reference is None:
            ready, changed = control_tick+self._settling, control_tick
        else:
            difference = abs(reference-self._reference)
            if difference > 1e-12:
                changed = control_tick
            if difference > self._slew*self._period+1e-12:
                ready = control_tick+self._settling
        self._tick, self._reference = int(control_tick), reference
        self._ready_after, self._last_change = int(ready), int(changed)
        return control_tick >= self._ready_after

    def window_ready(self, start_tick, end_tick):
        if (isinstance(start_tick, bool) or isinstance(end_tick, bool)
                or not isinstance(start_tick, Integral) or not isinstance(end_tick, Integral)
                or start_tick < 0 or end_tick <= start_tick or end_tick != self._tick+1):
            raise ValueError("complete current observation window required")
        return start_tick >= self._ready_after

    def require_constant_window(self, start_tick, end_tick, reference_a):
        reference = _scalar(reference_a, "window reference")
        if (not self.window_ready(start_tick, end_tick) or start_tick < self._last_change
                or abs(reference-self._reference) > 1e-12):
            raise ValueError("unsettled or varying reference cannot use a constant periodic source")
