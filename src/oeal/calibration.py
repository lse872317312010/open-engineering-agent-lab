"""Single-node thermal RC identification with explicit train/holdout separation."""

import math

import numpy as np


def simulate_rc(power_w, step_s, resistance_k_per_w, capacity_j_per_k, ambient_c=25.0):
    power = np.asarray(power_w, dtype=float)
    if power.ndim != 1 or len(power) < 2 or not np.all(np.isfinite(power)):
        raise ValueError("finite 1D power sequence required")
    if not all(math.isfinite(v) and v > 0 for v in (
        step_s, resistance_k_per_w, capacity_j_per_k
    )) or not math.isfinite(ambient_c):
        raise ValueError("invalid RC parameters")
    pole = math.exp(-step_s / (resistance_k_per_w * capacity_j_per_k))
    temperatures = np.empty(len(power) + 1)
    temperatures[0] = ambient_c
    for index, value in enumerate(power):
        temperatures[index + 1] = (
            ambient_c + pole * (temperatures[index] - ambient_c)
            + resistance_k_per_w * (1 - pole) * value
        )
    return temperatures


def fit_rc(temperature_c, power_w, step_s, ambient_c=25.0):
    temperature = np.asarray(temperature_c, dtype=float)
    power = np.asarray(power_w, dtype=float)
    if (temperature.ndim != 1 or power.ndim != 1 or len(temperature) != len(power) + 1
            or len(power) < 10 or not np.all(np.isfinite(temperature))
            or not np.all(np.isfinite(power))):
        raise ValueError("aligned finite samples required")
    if not math.isfinite(step_s) or step_s <= 0 or not math.isfinite(ambient_c):
        raise ValueError("invalid sampling or ambient")
    design = np.column_stack((temperature[:-1] - ambient_c, power))
    if np.linalg.matrix_rank(design) < 2:
        raise ValueError("insufficient excitation to identify R and C")
    pole, gain = np.linalg.lstsq(design, temperature[1:] - ambient_c, rcond=None)[0]
    if not 0 < pole < 1 or gain <= 0:
        raise ValueError("identified dynamics not passive/stable")
    resistance = gain / (1 - pole)
    capacity = -step_s / (resistance * math.log(pole))
    return {"resistance_k_per_w": float(resistance), "capacity_j_per_k": float(capacity),
            "discrete_pole": float(pole), "sample_count": len(power)}
