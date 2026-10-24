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
    transition_resolved: bool = False


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


def path_average(delta, speed, period_s, stiffness=500.0, damping=1.0, backlash=0.0):
    """Integrate the original force and heat laws on a predicted straight path."""
    displacement = period_s * speed
    if abs(displacement) < 1e-16:
        force, _, heat = transmission(delta, speed, stiffness, damping, backlash)
        return force, heat, False
    boundaries = [-backlash, backlash]
    if speed < 0:
        boundaries.append(backlash - damping * speed / stiffness)
    elif speed > 0:
        boundaries.append(-backlash - damping * speed / stiffness)
    points = [0.0, 1.0]
    for boundary in boundaries:
        fraction = (boundary - delta) / displacement
        if 0 < fraction < 1:
            points.append(fraction)
    points = sorted(set(points))
    force = heat = 0.0
    for left, right in zip(points[:-1], points[1:], strict=True):
        center, radius = (left + right) / 2, (right - left) / 2
        for node in (center - radius / math.sqrt(3), center + radius / math.sqrt(3)):
            value, _, power = transmission(
                delta + node * displacement, speed, stiffness, damping, backlash
            )
            force += radius * value
            heat += radius * power
    return force, heat, len(points) > 2


def path_midpoint_exchange(delta, speed, free_acceleration, inverse_inertia, period_s,
                           stiffness=500.0, damping=1.0, backlash=0.0):
    """Resolve force-law transitions without assigning an energy residual to heat."""
    point = midpoint_exchange(delta, speed, free_acceleration, inverse_inertia, period_s,
                              stiffness, damping, backlash)

    def evaluate(torque):
        v_mid = speed + period_s / 2 * (free_acceleration - inverse_inertia * torque)
        d_mid = delta + period_s / 2 * v_mid
        force, heat, resolved = path_average(
            delta, v_mid, period_s, stiffness, damping, backlash
        )
        return Exchange(torque, d_mid, v_mid, heat, torque - force, False, resolved)

    for candidate in (point.torque_nm, 0.0):
        value = evaluate(candidate)
        if abs(value.law_residual_nm) <= 1e-12 * (1 + abs(candidate)):
            return value
    bound = max(1.0, abs(point.torque_nm), stiffness * abs(delta)
                + damping * (abs(speed) + abs(period_s * free_acceleration)))
    for _ in range(40):
        left, right = evaluate(-bound), evaluate(bound)
        if left.law_residual_nm <= 0 <= right.law_residual_nm:
            break
        bound *= 2
    else:
        left = right = None
    if left is not None and right is not None:
        for _ in range(80):
            value = evaluate((left.torque_nm + right.torque_nm) / 2)
            if abs(value.law_residual_nm) <= 1e-12 * (1 + abs(value.torque_nm)):
                return value
            if value.law_residual_nm < 0:
                left = value
            else:
                right = value
    torque, _, heat = transmission(delta, speed, stiffness, damping, backlash)
    predicted = evaluate(torque)
    return Exchange(torque, predicted.delta_mid_rad, predicted.speed_mid_rad_s,
                    heat, predicted.law_residual_nm, True, False)


class TorqueHistory:
    """Causal extrapolation of completed-window electromagnetic torque means."""

    def __init__(self):
        self.last_time = self.last_impulse = self.last_mean = None

    def observe(self, time_s, impulse_nms, instantaneous_nm):
        if not all(math.isfinite(x) for x in (time_s, impulse_nms, instantaneous_nm)):
            raise ValueError("finite torque history required")
        if self.last_time is None:
            self.last_time, self.last_impulse = time_s, impulse_nms
            return instantaneous_nm, instantaneous_nm, 0
        dt = time_s - self.last_time
        if dt <= 0:
            raise ValueError("torque-history time must strictly increase")
        mean = (impulse_nms - self.last_impulse) / dt
        windows = 1 if self.last_mean is None else 2
        forecast = mean if self.last_mean is None else 2 * mean - self.last_mean
        self.last_time, self.last_impulse, self.last_mean = time_s, impulse_nms, mean
        return mean, forecast, windows
