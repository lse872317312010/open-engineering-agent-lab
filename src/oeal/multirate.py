"""Integer control ticks and loss-integral thermal windows; NumPy-only."""
import numpy as np


class ThermalWindowClock:
    def __init__(self, sink, *, source_powers_w, control_period_ns=50_000,
                 thermal_period_ns=2_500_000):
        for value in (control_period_ns, thermal_period_ns):
            if type(value) is not int or value <= 0:
                raise ValueError("periods must be positive integer nanoseconds")
        if thermal_period_ns % control_period_ns:
            raise ValueError("thermal period must contain whole control periods")
        scales = np.array(source_powers_w, dtype=float, copy=True)
        if scales.shape != (2,) or not np.all(np.isfinite(scales)) or np.any(scales <= 0):
            raise ValueError("two finite positive source scales required")
        if abs(sink.dt_s-thermal_period_ns*1e-9) > 1e-15:
            raise ValueError("sink step does not match thermal clock")
        scales.setflags(write=False)
        self.sink, self.scales = sink, scales
        self.control_period_ns, self.thermal_period_ns = control_period_ns, thermal_period_ns
        self.ratio = thermal_period_ns//control_period_ns
        self.next_tick = 0
        self._seen = None
        self._start = None

    def sample(self, tick, cumulative_energy_j):
        if type(tick) is not int or tick != self.next_tick:
            raise ValueError("duplicate, missing or noninteger control tick")
        raw = np.asarray(cumulative_energy_j)
        if np.iscomplexobj(raw):
            raise ValueError("real cumulative energy required")
        energy = np.array(raw, dtype=float, copy=True)
        if energy.shape != (2,) or not np.all(np.isfinite(energy)) or np.any(energy < 0):
            raise ValueError("two finite nonnegative cumulative energies required")
        if self._seen is not None and np.any(energy < self._seen):
            raise ValueError("loss ledger must not decrease")
        packet = None
        if tick == 0:
            self._start = energy.copy()
        elif tick % self.ratio == 0:
            delta = energy-self._start
            mean = delta/(self.thermal_period_ns*1e-9)
            factors = mean/self.scales
            if np.any(factors < 0) or np.any(factors > 2):
                raise ValueError("window mean source outside model input domain")
            outputs = np.array(self.sink.step_average(factors), dtype=float, copy=True)
            packet = dict(start_tick=tick-self.ratio, end_tick=tick,
                          control_count=self.ratio, energy_j=delta.copy(),
                          mean_power_w=mean.copy(), source_factors=factors.copy(), outputs=outputs)
            self._start = energy.copy()
        self._seen = energy.copy()
        self.next_tick += 1
        return packet
