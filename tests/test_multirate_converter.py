"""Actual upstream voltage-drop passivity counterexample before adapting direction refresh."""
import numpy as np
import pytest


def test_upstream_latched_direction_counterexample_and_refreshed_passivity():
    pytest.importorskip("motulator")
    from motulator.common.model import VoltageSourceConverter

    converter = VoltageSourceConverter(u_dc=48., u_th=.1,
                                       sign=lambda i:2/np.pi*np.arctan(i/.02))
    gates, blanking = np.full(3, .5), np.zeros(3)
    converter.inp.i_c_ab = .01+0j
    converter.set_gate_signals(gates, blanking)
    converter.inp.i_c_ab = -.001+0j
    converter.set_outputs(0.)
    dc = 48.*converter.compute_internal_dc_current(converter.inp)
    ac = 1.5*float((converter.out.u_c_ab*np.conj(converter.inp.i_c_ab)).real)
    assert dc-ac < -1e-6
    for current in (-.01+0j, -.001+0j, 0j, .001+.002j, .02-.01j):
        converter.inp.i_c_ab = current
        converter.set_gate_signals(gates, blanking)
        converter.set_outputs(0.)
        dc = 48.*converter.compute_internal_dc_current(converter.inp)
        ac = 1.5*float((converter.out.u_c_ab*np.conj(current)).real)
        assert dc-ac >= -1e-15
