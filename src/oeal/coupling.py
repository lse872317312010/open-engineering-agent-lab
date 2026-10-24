"""Frozen-acceleration mechanical midpoint predictor; no simulator dependency."""

import math
from dataclasses import dataclass


def transmission(delta, relative_speed, stiffness=500.0, damping=1.0, backlash=0.0):
    """Unilateral Kelvin-Voigt contact on either side of a symmetric backlash gap."""
    penetration = max(abs(delta) - backlash, 0.0)
    if penetration == 0:
        return 0.0, 0.0, 0.0
    side = math.copysign(1.0, delta)
    elastic = stiffness * penetration
    magnitude = max(elastic + side * damping * relative_speed, 0.0)
    torque = side * magnitude
    energy = 0.5 * stiffness * penetration ** 2
    # Includes unloading dissipation when the unilateral force clips to zero.
    dissipated = (torque - side * elastic) * relative_speed
    return torque, energy, max(float(dissipated), 0.0)



@dataclass(frozen=True)
class Exchange:
    torque_nm: float
    delta_mid_rad: float
    speed_mid_rad_s: float
    damping_power_w: float
    law_residual_nm: float
    fallback: bool


def midpoint_exchange(delta, speed, free_acceleration, inverse_inertia, period_s,
                      stiffness=500.0, damping=1.0, backlash=0.0):
    """Solve the original force law on each frozen midpoint branch.

    This predicts one constant torque. It does not roll back or implicitly solve
    the nonlinear electrical/robot subsystems, nor infer heat from an energy error.
    """
    inputs = (delta, speed, free_acceleration, inverse_inertia, period_s,
              stiffness, damping, backlash)
    if not all(math.isfinite(v) for v in inputs):
        raise ValueError("finite coupling quantities required")
    if min(inverse_inertia, period_s, stiffness) <= 0 or min(damping, backlash) < 0:
        raise ValueError("positive inertia/period/stiffness and nonnegative damping/gap required")
    h = period_s
    denominator = 1 + inverse_inertia * (stiffness * h * h / 4 + damping * h / 2)
    position = delta + h * speed / 2 + h * h * free_acceleration / 4
    velocity = speed + h * free_acceleration / 2
    candidates = (
        (stiffness * (position - backlash) + damping * velocity) / denominator,
        (stiffness * (position + backlash) + damping * velocity) / denominator,
        0.0,
    )

    def prediction(torque):
        v = speed + h / 2 * (free_acceleration - inverse_inertia * torque)
        return delta + h / 2 * v, v

    for torque in candidates:
        d_mid, v_mid = prediction(torque)
        if not all(math.isfinite(v) for v in (torque, d_mid, v_mid)):
            continue
        force, _, heat = transmission(d_mid, v_mid, stiffness, damping, backlash)
        residual = torque - force
        d_end = 2 * d_mid - delta
        crosses = delta * d_end < 0 or (
            backlash > 0 and (abs(delta) - backlash) * (abs(d_end) - backlash) < 0
        )
        if abs(residual) <= 1e-10 * (1 + abs(torque)) and not crosses:
            return Exchange(torque, d_mid, v_mid, heat, residual, False)
    torque, _, heat = transmission(delta, speed, stiffness, damping, backlash)
    d_mid, v_mid = prediction(torque)
    residual = torque - transmission(d_mid, v_mid, stiffness, damping, backlash)[0]
    return Exchange(torque, d_mid, v_mid, heat, residual, True)
