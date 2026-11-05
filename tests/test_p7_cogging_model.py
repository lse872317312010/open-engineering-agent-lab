"""Analytic Fourier and coupled electromechanical coenergy references."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "cogging_model", Path(__file__).resolve().parents[1] / "benchmarks/p7_cogging_model.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def setup_motor():
    theta = np.arange(16)*mod.PERIOD/16
    psi = mod.FourierSeries.fit(np.column_stack((.06+.001*np.cos(8*theta),
                                                 .002*np.sin(8*theta))))
    cog = mod.FourierSeries.fit((2*np.sin(24*theta))[:, None], zero_mean=True)
    return mod.CoggingMotor(psi, cog, [[.002, .0001], [.0001, .003]])


def test_fourier_projection_derivative_and_closed_integral():
    model = setup_motor()
    for angle in (.01, .12, .31):
        assert model.cog.value(angle)[0] == pytest.approx(2*np.sin(24*angle), abs=1e-12)
        assert model.cog.derivative(angle)[0] == pytest.approx(48*np.cos(24*angle), abs=1e-10)
        assert model.cog.integral(angle)[0] == pytest.approx((1-np.cos(24*angle))/12, abs=1e-12)
    assert model.cog.integral(mod.PERIOD)[0] == pytest.approx(0, abs=1e-14)
    np.testing.assert_allclose(model.psi.value(0), model.psi.value(mod.PERIOD))


def test_fixed_stator_current_coenergy_gradient():
    model = setup_motor()
    theta, current, step = .1, np.array([.3, -.2]), 1e-6

    def coenergy(at):
        delta = -4*(at-theta)
        rot = np.array([[np.cos(delta), -np.sin(delta)],
                        [np.sin(delta), np.cos(delta)]])
        i = rot@current
        return (float(model.cog.integral(at)[0])
                +1.5*(model.psi.value(at)@i+.5*i@model.inductance@i))

    numerical = (coenergy(theta+step)-coenergy(theta-step))/(2*step)
    assert model.torque(theta, current)[0] == pytest.approx(numerical, abs=1e-8)


def test_electromechanical_power_identity():
    model = setup_motor()
    theta, omega, current, voltage, load = .15, 3., np.array([.2, -.3]), np.array([1., 2.]), .1
    derivative, _, acceleration = model.rhs(theta, omega, current, voltage, load)
    powers = model.powers(theta, omega, current, voltage, load)
    storage_rate = 1.5*current@model.inductance@derivative-model.cog.value(theta)[0]*omega
    kinetic_rate = model.inertia*omega*acceleration
    assert powers[0]-sum(powers[1:]) == pytest.approx(storage_rate+kinetic_rate, abs=1e-12)


def test_zero_current_mechanical_limit_and_invalid_inputs():
    model = setup_motor()
    di, angle_dot, omega_dot = model.rhs(.1, 0, [0, 0], [0, 0], 0)
    np.testing.assert_allclose(di, [0, 0])
    assert angle_dot == 0
    assert omega_dot == pytest.approx(model.cog.value(.1)[0]/model.inertia)
    with pytest.raises(ValueError):
        model.flux(0, [1.1, 1.1])
    with pytest.raises(ValueError):
        mod.CoggingMotor(model.psi, model.cog, [[.002, 0], [0, .003]], inertia=0)
