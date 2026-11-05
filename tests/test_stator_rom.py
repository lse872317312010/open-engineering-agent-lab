"""Independent two-node backward-Euler hand calculation and rejection semantics."""
import subprocess
import sys

import numpy as np
import pytest

from oeal.stator_rom import StatorThermalROM


def bundle():
    return dict(format_version=1, mass=[[2., 0.], [0., 3.]],
                bulk=[[1., -1.], [-1., 1.]], convection=[[0., 0.], [0., 1.]],
                forcing=[1., 0.], observations=[[1., 0.], [0., 1.], [2., 3.], [0., 1.]],
                h_bounds=[5., 80.], power_bounds_w=[0., 2.], ambient_c=25.)


def test_two_node_closed_form_and_exact_global_energy():
    motor = StatorThermalROM(bundle(), h_w_m2_k=5., dt_s=1.)
    result = motor.step_average(1.)
    np.testing.assert_allclose(result, [25+9/26, 25+1/26, 21/26, 5/26], atol=1e-14)
    assert result[2]+result[3] == pytest.approx(1., abs=1e-14)


@pytest.mark.parametrize("power", [-1., 2.1, float("nan"), float("inf"), True, 1j, [1.]])
def test_invalid_power_rejected_without_state_change(power):
    motor = StatorThermalROM(bundle(), h_w_m2_k=5., dt_s=.0025)
    motor.step_average(.5)
    before = motor.state
    with pytest.raises(ValueError):
        motor.step_average(power)
    np.testing.assert_array_equal(motor.state, before)


@pytest.mark.parametrize("h,dt", [(2., 1.), (100., 1.), (5., 0.),
                                  (True, .1), (5., float("inf"))])
def test_invalid_domain_and_clock(h, dt):
    with pytest.raises(ValueError):
        StatorThermalROM(bundle(), h_w_m2_k=h, dt_s=dt)


@pytest.mark.parametrize("key,value", [("mass", [[-1., 0.], [0., 1.]]),
                                      ("format_version", True),
                                      ("convection", [[-.01, 0.], [0., 1.]]),
                                      ("forcing", [1j, 0.]),
                                      ("observations", [[1., 0.]]),
                                      ("bulk", [[float("nan"), 0.], [0., 1.]])])
def test_malformed_model_rejected(key, value):
    data = bundle()
    data[key] = value
    with pytest.raises(ValueError):
        StatorThermalROM(data, h_w_m2_k=5., dt_s=1.)


def test_inference_bundle_runs_without_field_or_scipy_dependencies(tmp_path):
    path = tmp_path / "inference.npz"
    np.savez(path, **bundle())
    code = """
import importlib.abc
import sys
class BlockFields(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'scipy', 'gmsh', 'skfem', 'meshio'}:
            raise ImportError('field dependency forbidden for inference')
sys.meta_path.insert(0, BlockFields())
from oeal.stator_rom import StatorThermalROM
model = StatorThermalROM.from_npz(sys.argv[1], h_w_m2_k=5., dt_s=1.)
values = model.step_average(1.)
assert abs(values[2] - 21/26) < 1e-14
"""
    result = subprocess.run([sys.executable, "-c", code, str(path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
