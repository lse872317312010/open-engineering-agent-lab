"""Guard the held-out scenario design and protected original acceptance goals."""

import unittest

from benchmarks.validate_robot_endurance import build_cases


class RobotEndurancePlanTests(unittest.TestCase):
    def test_holdouts_preserve_goals_gains_and_budget(self):
        cases = build_cases()
        self.assertEqual(len(cases), 9)
        self.assertEqual(len({c["id"] for c in cases}), 9)
        for case in cases:
            self.assertEqual(case["acceptance"], {
                "position_tail_error_rad": {"value": 0.03, "unit": "rad"},
                "current_peak_a": {"value": 20, "unit": "A"},
                "shaft_torque_peak_nm": {"value": 100, "unit": "N*m"},
            })
            self.assertEqual(case["settings"]["outer_kp_nm_per_rad"]["value"],
                             779.266681952671)
            self.assertEqual(case["settings"]["outer_kd_nms_per_rad"]["value"],
                             56.608067569927684)
        coarse, fine = cases[1], cases[-1]
        self.assertEqual(coarse["settings"] | {"macro_step_s": fine["settings"][
            "macro_step_s"]}, fine["settings"])


if __name__ == "__main__":
    unittest.main()
