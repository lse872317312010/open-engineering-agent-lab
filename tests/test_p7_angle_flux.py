"""Independent constant-flux limits and energy identity."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "angle_flux", Path(__file__).resolve().parents[1] / "benchmarks/p7_angle_flux.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_constant_flux_recovers_rotating_affine_equation():
    model = module.AngleFlux([[.06, 0]]*5, [[.002, 0], [0, .003]])
    i = np.array([.2, -.1])
    v = np.array([1., 2.])
    omega = 3.
    rhs = model.rhs(.1, omega, v, i)
    lam = np.array([.0604, -.0003])
    np.testing.assert_allclose(rhs, (v-.3*i-12*np.array([-lam[1], lam[0]]))
                               /np.array([.002, .003]))


def test_piecewise_energy_balance_and_closure():
    model = module.AngleFlux([[.06, 0], [.061, .001], [.062, 0], [.061, -.001],
                              [.0602, 0]], [[.002, .0001], [.0001, .003]])
    assert model.closure_error[0] == pytest.approx(.0002)
    i = np.array([.3, -.2])
    voltage = np.array([.8, 1.])
    derivative = model.rhs(.1, 2., voltage, i)
    p = model.power(.1, 2., voltage, i)
    assert p[0]-p[1]-p[2] == pytest.approx(1.5*i@model.inductance@derivative)
    np.testing.assert_allclose(model.flux(0, i), model.flux(model.period, i))


def test_zero_speed_rl_and_domain_rejection():
    model = module.AngleFlux([[.06, 0]]*5, [[.002, 0], [0, .003]])
    np.testing.assert_allclose(model.rhs(0, 0, [1, 0], [0, 0]), [500, 0])
    with pytest.raises(ValueError):
        model.flux(0, [1.1, 1.1])
    with pytest.raises(ValueError):
        model.rhs(float("nan"), 0, [0, 0], [0, 0])


def test_zero_resistance_no_voltage_preserves_isotropic_energy():
    model = module.AngleFlux([[0, 0]]*5, [[.002, 0], [0, .002]], resistance=0)
    i = np.array([.3, -.2])
    derivative = model.rhs(0, 7., [0, 0], i)
    assert np.dot(i, derivative) == pytest.approx(0, abs=1e-12)


def test_last_segment_uses_continuous_periodic_endpoint():
    model = module.AngleFlux([[.06, 0], [.061, 0], [.062, 0], [.061, 0], [.06, 0]],
                             [[.002, 0], [0, .003]])
    left_psi, _ = model.coefficients(model.period, segment=3)
    np.testing.assert_allclose(left_psi, model.psi[0], atol=1e-15)


def test_mechanical_torque_is_coenergy_gradient_at_fixed_stationary_current():
    model = module.AngleFlux([[.06, 0], [.061, .001], [.062, 0], [.061, -.001],
                              [.06, 0]], [[.002, .0001], [.0001, .003]])
    theta, current, step = .1, np.array([.3, -.2]), 1e-6

    def coenergy(at):
        delta = -4*(at-theta)
        rotation = np.array([[np.cos(delta), -np.sin(delta)],
                             [np.sin(delta), np.cos(delta)]])
        i = rotation@current
        psi, _ = model.coefficients(at)
        return 1.5*(psi@i+.5*i@model.inductance@i)

    numerical = (coenergy(theta+step)-coenergy(theta-step))/(2*step)
    torque = model.power(theta, 1., [0, 0], current)[2]
    assert torque == pytest.approx(numerical, abs=1e-9)
