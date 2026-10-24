"""SI energy identities and independent raw-stream balances.

This module imports no optional simulator and never derives source power from
the balance identity. Integrator-produced port works and physical storage states
are its inputs.
"""

import math

import numpy as np

from oeal.refined_thermal import CAPACITIES

ABS_TOL_J = 2e-5
REL_TOL = 2e-4
INTEGRALS = (
    "source_j", "source_abs_j", "bridge_j", "ac_j", "copper_j", "conduction_j",
    "auxiliary_device_j", "rotor_friction_j", "load_work_j", "shaft_heat_import_j",
    "ambient_j",
)
TEMPERATURES = ("winding_c", "core_c", "case_c", "junction_c", "board_c", "sink_c")
ENERGY_COLUMNS = [
    "time_s", *INTEGRALS, "magnetic_j", "kinetic_j", "bus_j", "thermal_j",
    "local_residual_j", "thermal_residual_j", *TEMPERATURES,
    "source_w", "copper_w", "conduction_w", "auxiliary_device_w",
    "rotor_friction_w", "load_w", "shaft_heat_import_w", "ambient_w",
]


def auxiliary_device_power(current, period_s, enabled):
    """Equivalent DC-shunt research loss; threshold drop is accounted separately."""
    if not math.isfinite(period_s) or period_s <= 0:
        raise ValueError("positive finite control period required")
    magnitude = np.abs(np.asarray(current))
    return 1.5 * 0.02 * magnitude ** 2 + 6 * 20e-6 / period_s * magnitude * enabled


def linear_magnetic_energy(flux_dq, ld_h, lq_h, pm_flux_wb):
    """Field energy from flux states, excluding constant permanent-magnet energy."""
    if not all(math.isfinite(x) and x > 0 for x in (ld_h, lq_h)):
        raise ValueError("positive finite inductances required")
    flux = np.asarray(flux_dq)
    return 0.75 * ((flux.real - pm_flux_wb) ** 2 / ld_h + flux.imag ** 2 / lq_h)


def thermal_energy(temperatures, ambient_c):
    return np.asarray(temperatures) @ CAPACITIES - ambient_c * CAPACITIES.sum()


def recompute_balances(columns, samples):
    data = np.asarray(samples, dtype=float)
    if data.ndim != 2 or not len(data) or not np.all(np.isfinite(data)):
        raise ValueError("finite nonempty energy stream required")
    if data.shape[1] != len(columns) or len(set(columns)) != len(columns):
        raise ValueError("energy stream columns do not match samples")

    def get(name):
        return data[:, columns.index(name)]

    storage = sum(get(name) - get(name)[0]
                  for name in ("magnetic_j", "kinetic_j", "bus_j", "thermal_j"))
    local = get("source_j") + get("shaft_heat_import_j") - get("load_work_j")
    local = local - storage - get("ambient_j")
    heat = sum(get(name) for name in (
        "copper_j", "conduction_j", "auxiliary_device_j", "rotor_friction_j",
        "shaft_heat_import_j",
    ))
    thermal = heat - (get("thermal_j") - get("thermal_j")[0]) - get("ambient_j")
    scale = float(np.max(get("source_abs_j")))
    if np.any(np.diff(get("source_abs_j")) < -1e-10):
        raise ValueError("absolute source-energy integral must not decrease")
    limit = ABS_TOL_J + REL_TOL * scale
    metrics = {
        "energy_balance_abs_j": float(np.max(np.abs(local))),
        "thermal_balance_abs_j": float(np.max(np.abs(thermal))),
        "energy_balance_limit_j": limit,
        "source_energy_j": float(get("source_j")[-1]),
        "source_abs_energy_j": scale,
    }
    return local, thermal, metrics
