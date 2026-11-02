"""NumPy-only inference for frozen affine contact thermal ROM bundles."""
from numbers import Real
from pathlib import Path

import numpy as np


def _real(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    value = float(value)
    if not np.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


class AffineThermalROM:
    """Fixed-Rc CN state machine; no FE/pyMOR import or runtime parameter switching."""

    KEYS = ("format_version", "mass", "bulk_stiffness", "contact_stiffness", "forcing",
            "observations", "rc_bounds", "reference_rc", "ambient_c")

    def __init__(self, data, *, rc, dt_s):
        rc, dt_s = _real(rc, "Rc"), _real(dt_s, "dt_s")
        version = np.asarray(data["format_version"]).item()
        if type(version) is not int or version != 1:
            raise ValueError("unsupported ROM format")
        bounds = np.array(data["rc_bounds"], dtype=float, copy=True)
        if (bounds.shape != (2,) or not np.all(np.isfinite(bounds))
                or not 0 < bounds[0] <= bounds[1]):
            raise ValueError("invalid Rc bounds")
        if not bounds[0] <= rc <= bounds[1]:
            raise ValueError("Rc outside frozen parameter domain")
        if not 0 < dt_s <= .1:
            raise ValueError("dt_s outside (0, 0.1]")
        reference = _real(np.asarray(data["reference_rc"]).item(), "reference_rc")
        ambient = _real(np.asarray(data["ambient_c"]).item(), "ambient_c")
        if not bounds[0] <= reference <= bounds[1]:
            raise ValueError("reference Rc outside bounds")
        arrays = {}
        for key in self.KEYS[1:6]:
            raw = np.asarray(data[key])
            if np.iscomplexobj(raw):
                raise ValueError("real ROM matrices required")
            matrix = np.array(raw, dtype=float, copy=True)
            if matrix.ndim != 2 or not np.all(np.isfinite(matrix)):
                raise ValueError(f"invalid matrix: {key}")
            matrix.setflags(write=False)
            arrays[key] = matrix
        mass = arrays["mass"]
        if mass.shape[0] == 0 or mass.shape[0] != mass.shape[1]:
            raise ValueError("mass must be nonempty square")
        n = mass.shape[0]
        for key in ("bulk_stiffness", "contact_stiffness"):
            if arrays[key].shape != (n, n):
                raise ValueError("stiffness shape mismatch")
        if arrays["forcing"].shape != (n, 2) or arrays["observations"].shape != (6, n):
            raise ValueError("input/output shape mismatch")
        stiffness = arrays["bulk_stiffness"]+reference/rc*arrays["contact_stiffness"]
        for matrix in (mass, stiffness):
            if (not np.allclose(matrix, matrix.T, atol=1e-9, rtol=1e-10)
                    or np.min(np.linalg.eigvalsh(matrix)) <= 0):
                raise ValueError("symmetric positive definite matrices required")
        lhs = mass+dt_s/2*stiffness
        self._advance = np.linalg.solve(lhs, mass-dt_s/2*stiffness)
        self._input = np.linalg.solve(lhs, dt_s*arrays["forcing"])
        self._observations = arrays["observations"].copy()
        self._observations[4] *= reference/rc
        for matrix in (self._advance, self._input, self._observations):
            matrix.setflags(write=False)
        self._ambient = ambient
        self._state = np.zeros(n)
        self._previous = np.zeros(2)
        self._rc, self._dt_s = rc, dt_s

    @classmethod
    def from_npz(cls, path: str | Path, *, rc, dt_s):
        """Read only numeric inference keys; no pickle, basis or FE fields required."""
        with np.load(path, allow_pickle=False) as data:
            return cls({k:data[k] for k in cls.KEYS}, rc=rc, dt_s=dt_s)

    @property
    def state(self):
        return self._state.copy()

    @property
    def rc(self):
        return self._rc

    @property
    def dt_s(self):
        return self._dt_s

    def step(self, current_source_factors):
        """Advance one step and return four absolute temperatures and two signed powers."""
        raw = np.asarray(current_source_factors)
        if np.iscomplexobj(raw):
            raise ValueError("real source factors required")
        factors = np.asarray(raw, dtype=float)
        if (factors.shape != (2,) or not np.all(np.isfinite(factors))
                or np.any(factors < 0) or np.any(factors > 2)):
            raise ValueError("two finite source factors in [0, 2] required")
        next_state = self._advance@self._state+self._input@((self._previous+factors)/2)
        outputs = self._observations@next_state
        outputs[:4] += self._ambient
        self._state = next_state
        self._previous = factors.copy()
        return outputs
