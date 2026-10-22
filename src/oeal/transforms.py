"""Scalar amplitude-invariant transforms, including the zero-sequence component."""

import math


def _require_finite(*values: float) -> None:
    if not all(math.isfinite(value) for value in values):
        raise ValueError("transform inputs must be finite")


def clarke(a: float, b: float, c: float) -> tuple[float, float, float]:
    """Return alpha, beta, zero in the same units as the abc input."""
    _require_finite(a, b, c)
    return (2.0 * a - b - c) / 3.0, (b - c) / math.sqrt(3.0), (a + b + c) / 3.0


def inverse_clarke(alpha: float, beta: float, zero: float = 0.0) -> tuple[float, float, float]:
    """Return abc; zero defaults to the balanced three-wire case."""
    _require_finite(alpha, beta, zero)
    return (
        alpha + zero,
        -0.5 * alpha + math.sqrt(3.0) * 0.5 * beta + zero,
        -0.5 * alpha - math.sqrt(3.0) * 0.5 * beta + zero,
    )


def park(alpha: float, beta: float, electrical_angle_rad: float) -> tuple[float, float]:
    """Rotate alpha/beta into rotor dq using electrical angle in radians."""
    _require_finite(alpha, beta, electrical_angle_rad)
    cosine = math.cos(electrical_angle_rad)
    sine = math.sin(electrical_angle_rad)
    return alpha * cosine + beta * sine, -alpha * sine + beta * cosine


def inverse_park(d: float, q: float, electrical_angle_rad: float) -> tuple[float, float]:
    """Rotate rotor dq back into stationary alpha/beta."""
    _require_finite(d, q, electrical_angle_rad)
    cosine = math.cos(electrical_angle_rad)
    sine = math.sin(electrical_angle_rad)
    return d * cosine - q * sine, d * sine + q * cosine
