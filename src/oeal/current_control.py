"""Discrete dq current PI with radial reference/voltage limits and back-calculation."""

import math
from dataclasses import dataclass


def _finite(**values: float) -> None:
    for name, value in values.items():
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")


def radial_limit(d: float, q: float, limit: float) -> tuple[float, float]:
    """Preserve vector direction and limit its Euclidean magnitude."""
    _finite(d=d, q=q, limit=limit)
    if limit <= 0:
        raise ValueError("limit must be greater than zero")
    # Normalize first to avoid overflow in hypot for large finite components.
    scale = max(abs(d), abs(q))
    if scale == 0:
        return d, q
    nd, nq = d / scale, q / scale
    norm = math.hypot(nd, nq)
    if scale <= limit / norm:
        return d, q
    return (nd / norm) * limit, (nq / norm) * limit


@dataclass(frozen=True)
class CurrentPIParameters:
    kp_d_v_per_a: float
    ki_d_v_per_as: float
    kp_q_v_per_a: float
    ki_q_v_per_as: float
    voltage_limit_v: float
    current_limit_a: float
    tracking_rate_per_s: float

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            _finite(**{name: value})
            if name.startswith(("kp_", "ki_")):
                if value < 0:
                    raise ValueError(f"{name} must be non-negative")
            elif value <= 0:
                raise ValueError(f"{name} must be greater than zero")


@dataclass(frozen=True)
class CurrentPIState:
    integral_d_v: float = 0.0
    integral_q_v: float = 0.0

    def __post_init__(self) -> None:
        _finite(integral_d_v=self.integral_d_v, integral_q_v=self.integral_q_v)


@dataclass(frozen=True)
class CurrentPIOutput:
    vd_v: float
    vq_v: float
    reference_d_a: float
    reference_q_a: float
    voltage_limited: bool
    current_reference_limited: bool
    next_state: CurrentPIState


def current_control_step(
    parameters: CurrentPIParameters,
    state: CurrentPIState,
    *,
    reference_d_a: float,
    reference_q_a: float,
    measured_d_a: float,
    measured_q_a: float,
    period_s: float,
    feedforward_d_v: float = 0.0,
    feedforward_q_v: float = 0.0,
) -> CurrentPIOutput:
    """Sample, integrate, limit total voltage, and return the next immutable state."""
    _finite(
        reference_d_a=reference_d_a, reference_q_a=reference_q_a,
        measured_d_a=measured_d_a, measured_q_a=measured_q_a,
        period_s=period_s, feedforward_d_v=feedforward_d_v,
        feedforward_q_v=feedforward_q_v,
    )
    if period_s <= 0:
        raise ValueError("period_s must be greater than zero")
    p = parameters
    if (p.ki_d_v_per_as == 0 and state.integral_d_v != 0
            or p.ki_q_v_per_as == 0 and state.integral_q_v != 0):
        raise ValueError("integral must be zero for an axis with zero Ki")
    rd, rq = radial_limit(reference_d_a, reference_q_a, p.current_limit_a)
    ed, eq = rd - measured_d_a, rq - measured_q_a
    _finite(error_d=ed, error_q=eq)
    zd = state.integral_d_v + p.ki_d_v_per_as * period_s * ed
    zq = state.integral_q_v + p.ki_q_v_per_as * period_s * eq
    ud = p.kp_d_v_per_a * ed + zd + feedforward_d_v
    uq = p.kp_q_v_per_a * eq + zq + feedforward_q_v
    _finite(trial_d=zd, trial_q=zq, raw_d=ud, raw_q=uq)
    vd, vq = radial_limit(ud, uq, p.voltage_limit_v)
    beta = -math.expm1(-p.tracking_rate_per_s * period_s)
    next_state = CurrentPIState(
        zd + beta * (vd - ud) if p.ki_d_v_per_as > 0 else 0.0,
        zq + beta * (vq - uq) if p.ki_q_v_per_as > 0 else 0.0,
    )
    return CurrentPIOutput(
        vd, vq, rd, rq, (vd, vq) != (ud, uq),
        (rd, rq) != (reference_d_a, reference_q_a), next_state,
    )
