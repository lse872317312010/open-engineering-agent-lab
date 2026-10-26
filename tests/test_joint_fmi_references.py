"""Independent mathematical limits committed before the C FMU implementation."""

import runpy
from pathlib import Path

import numpy as np

REF = runpy.run_path(str(Path(__file__).parents[1] / "benchmarks/joint_fmi_reference.py"))


def test_fmi_joint_equilibrium_and_ports():
    y = REF["initial"]()
    np.testing.assert_array_equal(REF["rhs"](0, y, [0, 0, 0, 0]), np.zeros(12))
    out = REF["rhs"](0, y, [1, 2, 0, 25])
    assert out[0] == 1250 and out[1] == 2500
    assert out[8] == 1 and out[9] == 25
    assert REF["stored"](y) == 0


def test_fmi_joint_independent_power_identity():
    y = np.array([1., 2., .1, 3., .002, -.4, 35., 28., 30., 0., 0., 0.])
    delta = y[2]/10-y[4]
    gradient = np.array([.0012*y[0], .0012*y[1], 8*delta, 5e-5*y[3],
                         -80*delta, .02*y[5], 60, 200, 25])
    dy = REF["rhs"](0, y, [.5, -1., .3, 20.])
    assert abs(gradient @ dy[:9] - dy[9] + dy[10] + dy[11]) < 1e-12


def test_fmi_joint_predeclared_schedules():
    for name in ("no-load", "loaded-heating", "reversal", "variable-clock"):
        rows = REF["schedule"](name)
        assert len(rows) == 1600
        assert abs(rows[-1][0]+rows[-1][1]-.08) < 1e-12
        assert all(0 < h <= .001 for _, h, _ in rows)
