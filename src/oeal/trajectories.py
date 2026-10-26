"""Declared joint references; the protected verifier uses separate vector equations."""

import math


def joint_reference(t, initial_angle, settings):
    amplitude = settings.get("position_step_rad", .08)
    start = settings.get("position_start_s", .02)
    period = settings.get("position_cycle_period_s")
    if period is not None:
        if not math.isfinite(period) or period <= 0:
            raise ValueError("cycle period must be finite and positive")
        elapsed = max(t - start, 0)
        return initial_angle + amplitude / 2 * (1 - math.cos(2 * math.pi * elapsed / period))
    ramp = settings.get("position_ramp_s", .12)
    return initial_angle + amplitude * min(max((t - start) / ramp, 0), 1)
