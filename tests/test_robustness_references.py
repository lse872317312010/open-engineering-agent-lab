"""Hand-computed nonuniform trajectories, not a copy of production metrics."""

import unittest

import numpy as np

from oeal.robustness import aligned_difference, tracking_metrics


class TrackingReferences(unittest.TestCase):
    def test_nonuniform_hand_quadrature(self):
        # Absolute error has areas .25 and .75; squared error integral is 2.
        result = tracking_metrics([0, .25, 1], [0, 2, 0], [0, 0, 0], duration_s=1)
        self.assertAlmostEqual(result["position_iae_rad_s"], 1)
        self.assertAlmostEqual(result["position_rmse_rad"], 2 ** .5)
        self.assertAlmostEqual(result["hold_max_error_rad"], 4 / 3)

    def test_missing_endpoint_nonfinite_and_reversed_time(self):
        for times, q in (([0, .9], [0, 0]), ([0, 1], [0, np.nan]),
                         ([0, .8, .7, 1], [0, 0, 0, 0])):
            with self.assertRaises(ValueError):
                tracking_metrics(times, q, np.zeros(len(q)), duration_s=1)

    def test_common_time_comparison(self):
        coarse = [[0, 0], [.5, 1], [1, 2]]
        fine = [[0, .001], [.25, .501], [.5, 1.001], [.75, 1.501], [1, 2.001]]
        self.assertAlmostEqual(aligned_difference(coarse, fine), .001)


if __name__ == "__main__":
    unittest.main()
