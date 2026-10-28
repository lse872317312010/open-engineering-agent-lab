"""Positive finite synthetic six-node RC parameters, normalized before FMU loading."""
import numpy as np
from msl_cooling_drive_parameters import real

CAPACITY = (60.,70.,200.,.5,25.,100.)
RESISTANCE = (.6,.4,2.,.8,1.2)


def vector(values, default, count, low, high, name):
    values = default if values is None else values
    array = np.asarray(values, dtype=object)
    if array.shape != (count,):
        raise ValueError(name+" has an invalid dimension")
    result = tuple(real(x, name) for x in array)
    if not all(low <= x <= high for x in result):
        raise ValueError(name+" outside declared positive range")
    return result


def rc_parameters(capacities_j_per_k=None, link_resistances_k_per_w=None,
                  case_resistance_k_per_w=2.):
    capacities = vector(capacities_j_per_k, CAPACITY, 6, .05, 1000., "capacities")
    links = vector(link_resistances_k_per_w, RESISTANCE, 5, .05, 20., "resistances")
    case = real(case_resistance_k_per_w, "case resistance")
    if not .05 <= case <= 20:
        raise ValueError("case resistance outside declared positive range")
    return capacities, links, case
