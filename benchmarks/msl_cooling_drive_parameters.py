"""Validated trusted-Python cooling configuration; no JSON asset selection."""
from numbers import Real

import numpy as np


def real(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(name+" must be a finite real number")
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(name+" must be finite")
    return result


def configuration(ambient_c=25., area_m2=.02, initial_temperatures_c=None):
    ambient = real(ambient_c, "ambient_c")
    area = real(area_m2, "area_m2")
    if not -10 <= ambient <= 60 or not 0 <= area <= .1:
        raise ValueError("ambient_c or area_m2 outside declared configuration range")
    initial = [80.]*6 if initial_temperatures_c is None else initial_temperatures_c
    values = np.asarray(initial, dtype=object)
    if values.shape != (6,):
        raise ValueError("initial_temperatures_c must contain six values")
    temperatures = tuple(real(v, "initial temperature") for v in values)
    if not all(-10 <= v <= 120 for v in temperatures):
        raise ValueError("initial temperatures outside -10..120 degC")
    return ambient, area, temperatures
