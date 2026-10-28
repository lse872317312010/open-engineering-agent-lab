"""Independent one-node integral-row construction frozen before the network fitter."""
import numpy as np

EDGES = ((0,1),(1,2),(2,4),(3,4),(4,5))


def integral_row(node, delta_temperature, temperature_integrals, power_energy,
                 ambient, duration, sink_boundary_energy=0.):
    row = np.zeros(12)
    row[node] = delta_temperature[node]
    for k, (a, b) in enumerate(EDGES):
        value = temperature_integrals[a]-temperature_integrals[b]
        if node == a:
            row[6+k] = value
        elif node == b:
            row[6+k] = -value
    if node == 2:
        row[11] = temperature_integrals[2]-ambient*duration
    right = power_energy[node]-(sink_boundary_energy if node == 5 else 0.)
    return row, right


def stored_energy(temperature, initial, capacities):
    return float((np.asarray(temperature)-initial) @ capacities)
