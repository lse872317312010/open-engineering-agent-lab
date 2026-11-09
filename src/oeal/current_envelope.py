"""Prescribed constant dq current within each thermal window; no current-loop solver."""
import numpy as np

from oeal.stator_feedback import StatorCopperFeedback
from oeal.stator_rom import _scalar


def copper_power(id_a, iq_a, resistance_ohm):
    direct, quadrature, resistance = (_scalar(value, name) for value, name in (
        (id_a, "direct current"), (iq_a, "quadrature current"), (resistance_ohm, "resistance")))
    if abs(direct)+abs(quadrature) > 2 or resistance <= 0:
        raise ValueError("current must satisfy abs(id)+abs(iq)<=2 with positive resistance")
    power = 1.5*resistance*(direct*direct+quadrature*quadrature)
    if not np.isfinite(power):
        raise ValueError("finite copper power required")
    return power


def advance_current_window(feedback, end_tick, *, id_a, iq_a):
    if not isinstance(feedback, StatorCopperFeedback):
        raise ValueError("StatorCopperFeedback required")
    power = copper_power(id_a, iq_a, feedback.resistance_ohm)
    energy = feedback.copper_j+feedback.window_s*power
    return feedback.advance_window(end_tick, energy)
