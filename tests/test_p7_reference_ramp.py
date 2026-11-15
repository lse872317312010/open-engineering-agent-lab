"""Reference profile slew and exact guard-window accounting around steps."""
import importlib
from pathlib import Path

import numpy as np
import pytest

from oeal.reference_validity import ReferenceSettlingGuard


@pytest.fixture
def driver(monkeypatch):
    for package in ("scipy", "gmsh", "meshio", "skfem", "matplotlib"):
        pytest.importorskip(package)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "benchmarks"))
    return importlib.import_module("p7_reference_ramp")


def test_smooth_reference_endpoints_and_slew(driver):
    ticks = np.arange(12001)
    values = driver.reference_values(ticks, "smooth")
    np.testing.assert_allclose(values[[0, 4000, 8000, 12000]], [.125, .125, .45, .125], atol=1e-14)
    assert np.max(abs(np.diff(values)))/driver.TS == pytest.approx(1.625, abs=1e-10)


def test_step_guard_marks_exactly_sixteen_scoring_windows_unready(driver):
    guard = ReferenceSettlingGuard(period_s=driver.TS)
    unsupported = []
    for tick in range(12000):
        guard.observe(tick, float(driver.reference_values(tick, "step")))
        if (tick+1) % 50 == 0 and tick+1 > 4000:
            if not guard.window_ready(tick+1-50, tick+1):
                unsupported.append(tick+1-50)
    assert unsupported == list(range(4000, 4400, 50))+list(range(8000, 8400, 50))
