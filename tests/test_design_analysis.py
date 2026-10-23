"""Independent analytic limits for optional control and sensitivity libraries."""

import importlib.util
import unittest

OPTIONAL = importlib.util.find_spec("control") and importlib.util.find_spec("SALib")


@unittest.skipUnless(OPTIONAL, "optional design-analysis dependencies")
class DesignAnalysisTests(unittest.TestCase):
    def test_external_libraries_match_independent_analytic_limits(self):
        from oeal.design_analysis import independent_checks

        result = independent_checks()
        self.assertTrue(result["passed"])
        self.assertLess(result["step_reference_error"], 1e-8)
        self.assertLess(result["morris_reference_error"], 1e-9)

    def test_stable_position_loop_has_unit_static_gain(self):
        import control

        from oeal.design_analysis import joint_system

        _, closed = joint_system(load_inertia=2.0, kp=150, kd=5)
        self.assertLess(max(control.poles(closed).real), 0)
        self.assertAlmostEqual(float(control.dcgain(closed)), 1.0, places=9)
