"""Analytic manufactured steady-conduction reference, frozen before FE integration."""
import numpy as np

LENGTH_M = .1
THICKNESS_M = .01
CONDUCTIVITY_W_PER_M_K = 2.
AMPLITUDE_K = 10.
AMBIENT_C = 25.


def rise(x, y):
    return AMPLITUDE_K*np.sin(np.pi*x/LENGTH_M)*np.sin(np.pi*y/LENGTH_M)


def gradient(x, y):
    a = np.pi/LENGTH_M
    return np.array([AMPLITUDE_K*a*np.cos(a*x)*np.sin(a*y),
                     AMPLITUDE_K*a*np.sin(a*x)*np.cos(a*y)])


def source_w_per_m3(x, y):
    return 2*CONDUCTIVITY_W_PER_M_K*(np.pi/LENGTH_M)**2*rise(x, y)


def exact_total_power_w():
    return 8*CONDUCTIVITY_W_PER_M_K*AMPLITUDE_K*THICKNESS_M


def exact_norms():
    return AMPLITUDE_K*LENGTH_M/2, AMPLITUDE_K*np.pi/np.sqrt(2)
