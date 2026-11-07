"""Copper-window input contract, independent of FEM data."""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def replay(monkeypatch):
    for package in ("gmsh", "meshio", "skfem", "scipy", "matplotlib"):
        pytest.importorskip(package)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "benchmarks"))
    return importlib.import_module("p7_electric_thermal_replay")


def sample():
    return [dict(case="forward-base", window=i, start_s=i*.0025, end_s=(i+1)*.0025,
                 copper_j=.00025, deposited_j=.00025, error_j=0) for i in range(20)]


def test_copper_windows_preserve_integrated_energy(replay):
    power = replay.window_power(sample(), "forward-base", 1.)
    assert sum(power)*.0025 == pytest.approx(.005)


def test_power_plot_covers_every_actual_interval_and_preserves_energy(replay):
    import matplotlib.pyplot as plt
    import numpy as np

    power = np.linspace(.1, .3, 20)
    fig, axis = plt.subplots()
    try:
        patch = replay.plot_window_power(axis, power)
        data = patch.get_data()
        np.testing.assert_allclose(data.edges, np.arange(21)*2.5)
        np.testing.assert_array_equal(data.values, power)
        assert sum(data.values*np.diff(data.edges)/1000) == pytest.approx(.01)
        vertices = patch.get_path().vertices
        for i, value in enumerate(power):
            for edge in (i*2.5, (i+1)*2.5):
                assert np.any(np.all(np.isclose(vertices, [edge, value]), axis=1))
    finally:
        plt.close(fig)


@pytest.mark.parametrize("fault", ["missing", "out_of_order", "nan", "over_power"])
def test_copper_windows_reject_invalid_input(replay, fault):
    rows = sample()
    if fault == "missing":
        rows.pop()
    elif fault == "out_of_order":
        rows[0], rows[1] = rows[1], rows[0]
    elif fault == "nan":
        rows[0]["copper_j"] = float("nan")
    else:
        rows[0]["copper_j"] = rows[0]["deposited_j"] = .1
    with pytest.raises(ValueError):
        replay.window_power(rows, "forward-base", 1.)
