"""Independent two-control-volume balance and small-interface normalization limits."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from p7_layered_reference import CASES, powers  # noqa: E402


def test_interface_integral_is_fixed_by_region_balance_not_by_accuracy_of_every_facet():
    for case in CASES:
        p = powers(case)
        source_left,source_right = .04,.12
        interface = p["right_out_w"]-source_right
        left = source_left-interface
        np.testing.assert_allclose(interface,p["interface_right_w"],atol=1e-14)
        np.testing.assert_allclose(left,p["left_out_w"],atol=1e-14)
    # Exact integral does not rule out equal-and-opposite local errors.
    exact = np.array([2.,2.])
    perturbed = np.array([3.,1.])
    assert exact.sum() == perturbed.sum()
    assert np.sqrt(np.mean((perturbed-exact)**2)) == 1.


def test_global_power_normalization_does_not_bound_small_local_relative_error():
    jump,global_power,local_power = .002507881936934986,.16,.010952380952380956
    assert jump/global_power < .02
    assert jump/local_power > .22
