"""NumPy-only fixed-convection stator ROM; interval-mean power, backward Euler."""
from numbers import Real

import numpy as np


def _scalar(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real scalar")
    value = float(value)
    if not np.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


class StatorThermalROM:
    KEYS = ("format_version", "mass", "bulk", "convection", "forcing", "observations",
            "h_bounds", "power_bounds_w", "ambient_c")

    def __init__(self, data, *, h_w_m2_k, dt_s):
        h, dt = _scalar(h_w_m2_k, "h"), _scalar(dt_s, "dt")
        version = np.asarray(data["format_version"]).item()
        if type(version) is not int or version != 1 or not 0 < dt <= 1:
            raise ValueError("unsupported format or timestep")
        arrays = {}
        for key in self.KEYS[1:]:
            raw = np.asarray(data[key])
            if np.iscomplexobj(raw):
                raise ValueError("real inference arrays required")
            arrays[key] = np.array(raw, dtype=float, copy=True)
            if not np.isfinite(arrays[key]).all():
                raise ValueError("finite inference arrays required")
        hb, pb = arrays["h_bounds"], arrays["power_bounds_w"]
        if (hb.shape != (2,) or pb.shape != (2,) or not 0 < hb[0] <= hb[1]
                or pb[0] != 0 or pb[1] <= 0 or not hb[0] <= h <= hb[1]):
            raise ValueError("convection or power outside frozen domain")
        mass, bulk, convection = (arrays[k] for k in ("mass", "bulk", "convection"))
        if mass.ndim != 2 or mass.shape[0] == 0 or mass.shape[0] != mass.shape[1]:
            raise ValueError("nonempty square mass required")
        n = len(mass)
        if (bulk.shape != (n, n) or convection.shape != (n, n)
                or arrays["forcing"].shape != (n,) or arrays["observations"].shape != (4, n)
                or arrays["ambient_c"].shape != ()):
            raise ValueError("invalid inference matrix dimensions")
        stiffness = bulk+h*convection
        for matrix in (bulk, convection):
            if (not np.allclose(matrix, matrix.T, atol=1e-12, rtol=1e-10)
                    or np.min(np.linalg.eigvalsh(matrix)) < -1e-12):
                raise ValueError("passive symmetric conductance operators required")
        for matrix in (mass, stiffness):
            if (not np.allclose(matrix, matrix.T, atol=1e-12, rtol=1e-10)
                    or np.min(np.linalg.eigvalsh(matrix)) <= 0):
                raise ValueError("symmetric positive definite mass and stiffness required")
        lhs = mass+dt*stiffness
        self._advance = np.linalg.solve(lhs, mass)
        self._forcing = np.linalg.solve(lhs, dt*arrays["forcing"])
        self._observations = arrays["observations"]
        self._observations[3] *= h
        self._ambient = float(arrays["ambient_c"])
        self._power_max = float(pb[1])
        self._state = np.zeros(n)
        self._h, self._dt = h, dt
        for matrix in (self._advance, self._forcing, self._observations):
            matrix.setflags(write=False)

    @classmethod
    def from_npz(cls, path, *, h_w_m2_k, dt_s):
        with np.load(path, allow_pickle=False) as data:
            return cls({key: data[key] for key in cls.KEYS}, h_w_m2_k=h_w_m2_k, dt_s=dt_s)

    @property
    def state(self):
        return self._state.copy()

    def step_average(self, power_w):
        power = _scalar(power_w, "mean power")
        if not 0 <= power <= self._power_max:
            raise ValueError("mean power outside frozen source domain")
        state = self._advance@self._state+self._forcing*power
        outputs = self._observations@state
        outputs[:2] += self._ambient
        if not np.isfinite(state).all() or not np.isfinite(outputs).all():
            raise ValueError("nonfinite inference result")
        self._state = state
        return outputs
