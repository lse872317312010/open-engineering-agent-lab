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
