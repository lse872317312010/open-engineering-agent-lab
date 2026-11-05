"""Numerical mesh gate retains failures and accepts non-monotone differences."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "mesh_ref", Path(__file__).resolve().parents[1] / "benchmarks/p7_loaded_mesh_reference.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)


def test_nonmonotone_is_not_hidden():
    r = ref.compare([[0, 0], [.0001, 0], [.0006, 0]], [0, .01, .04], [10, 20, 30])
    assert r["passed"] and not r["flux_monotone"] and not r["torque_monotone"]
    assert r["flux_diff"] == pytest.approx([.002, .01])
    assert r["torque_diff_nm"] == pytest.approx([.01, .03])


def test_fixed_budgets_and_node_order_reject():
    r = ref.compare([[0, 0], [0, 0], [.002, 0]], [0, 0, .06], [10, 20, 15])
    assert not r["passed"] and not r["nodes_increasing"]
    assert r["flux_diff"][1] == pytest.approx(.04)


def test_nonfinite_rejected():
    with pytest.raises(ValueError):
        ref.compare([[0, 0], [0, 0], [float("nan"), 0]], [0, 0, 0], [1, 2, 3])
