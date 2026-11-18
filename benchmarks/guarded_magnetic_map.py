"""Reject out-of-domain evaluations of an upstream dq magnetic map."""
import numpy as np


class MagneticDomainError(ValueError):
    """A requested map evaluation is outside its explicitly supplied domain."""


class GuardedMagneticMap:
    """Wrap a callable map and a domain predicate without changing their algorithms.

    The predicate accepts a complex scalar or array and must return a boolean scalar
    or an identically shaped boolean array. It must represent the source model's
    declared valid domain; a convex hull alone does not certify physical validity.
    A guard only covers calls routed through this wrapper.
    """

    def __init__(self, magnetic_map, domain):
        if not callable(magnetic_map) or not callable(domain):
            raise TypeError("magnetic_map and domain must be callable")
        self.magnetic_map = magnetic_map
        self.domain = domain
        self.evaluations = 0
        self.rejected = 0
        self.jacobian_evaluations = 0

    def _check_input(self, dq):
        values = np.asarray(dq)
        if not np.issubdtype(values.dtype, np.number) or not np.isfinite(values).all():
            self.rejected += 1
            raise MagneticDomainError("map input must be finite numeric dq")
        allowed = np.asarray(self.domain(dq))
        if allowed.dtype != np.bool_ or allowed.shape != values.shape:
            raise ValueError("domain predicate must return matching boolean shape")
        if not allowed.all():
            self.rejected += 1
            raise MagneticDomainError("map input is outside the declared domain")
        return values

    def __call__(self, dq):
        values = self._check_input(dq)
        self.evaluations += 1
        output = self.magnetic_map(dq)
        result = np.asarray(output)
        if result.shape != values.shape or not np.issubdtype(result.dtype, np.number):
            raise ValueError("magnetic map output must be numeric and match input shape")
        if not np.isfinite(result).all():
            raise ValueError("magnetic map returned nonfinite values")
        return output

    def __getattr__(self, name):
        # Only expose a Jacobian when the wrapped upstream map actually supplies one.
        if name != "jacobian":
            raise AttributeError(name)
        upstream = getattr(self.magnetic_map, "jacobian")
        if not callable(upstream):
            raise AttributeError(name)

        def checked_jacobian(dq):
            values = self._check_input(dq)
            self.jacobian_evaluations += 1
            result = np.asarray(upstream(dq))
            if result.shape != values.shape + (2, 2) or not np.isfinite(result).all():
                raise ValueError("magnetic map Jacobian must be finite and have shape (..., 2, 2)")
            return result

        return checked_jacobian
