"""Verify domain rejection before evaluating an upstream magnetic map."""
import importlib.util
import unittest
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location(
    "guarded_magnetic_map", Path(__file__).parents[1] / "benchmarks/guarded_magnetic_map.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GuardedMapTest(unittest.TestCase):
    def test_in_domain_values_are_passed_unchanged(self):
        calls = []
        def upstream(x):
            calls.append(x)
            return np.asarray(x) * 2
        guard = module.GuardedMagneticMap(upstream, lambda x: np.abs(x) <= 1)
        np.testing.assert_array_equal(guard(np.array([0j, 1j])), [0j, 2j])
        self.assertEqual(guard.evaluations, 1)
        self.assertEqual(len(calls), 1)

    def test_rejects_all_inputs_when_any_point_is_outside(self):
        calls = []
        guard = module.GuardedMagneticMap(lambda x: calls.append(x), lambda x: np.abs(x) <= 1)
        with self.assertRaises(module.MagneticDomainError):
            guard(np.array([0j, 1.1j]))
        with self.assertRaises(module.MagneticDomainError):
            guard(complex(float("nan"), 0))
        self.assertEqual(calls, [])
        self.assertEqual(guard.rejected, 2)

    def test_rejects_bad_domain_shape_and_nonfinite_outputs(self):
        bad_shape = module.GuardedMagneticMap(lambda x: x, lambda x: True)
        with self.assertRaises(ValueError):
            bad_shape(np.array([0j, 1j]))
        bad_result = module.GuardedMagneticMap(lambda x: complex(float("inf"), 0), lambda x: True)
        with self.assertRaises(ValueError):
            bad_result(0j)
