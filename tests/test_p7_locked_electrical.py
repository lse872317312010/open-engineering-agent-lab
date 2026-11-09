"""RL closed-form current/energy reference for the augmented quadratic propagator."""
import importlib
import math
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def flow(monkeypatch):
    pytest.importorskip("scipy")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "benchmarks"))
    return importlib.import_module("p7_locked_electrical")


def test_rl_current_and_source_loss_energy_match_closed_form(flow):
    resistance, inductance, voltage, initial, dt = 2., 3., 4., .2, .1
    generator = np.array([[-resistance/inductance, 1/inductance], [0., 0.]])
    source = np.array([[0., .5], [.5, 0.]])
    copper = np.diag([resistance, 0.])
    advance, integrals = flow.quadratic_flow(generator, [source, copper], dt)
    state = np.array([initial, voltage])
    final = advance@state
    rate, steady = resistance/inductance, voltage/resistance
    delta = initial-steady
    expected_current = steady+delta*math.exp(-rate*dt)
    square_integral = (steady**2*dt+2*steady*delta*(1-math.exp(-rate*dt))/rate
                       +delta**2*(1-math.exp(-2*rate*dt))/(2*rate))
    work = np.array([state@form@state for form in integrals])
    assert final[0] == pytest.approx(expected_current, abs=1e-14)
    assert work[1] == pytest.approx(resistance*square_integral, abs=1e-14)
    assert work[0]-work[1] == pytest.approx(.5*inductance*(expected_current**2-initial**2),
                                           abs=1e-14)


def test_repeat_period_must_match_model_and_control_clocks(flow):
    with pytest.raises(ValueError, match="aligned repeat"):
        flow.simulate_locked(None, 1., 0., repeat_s=.021)
