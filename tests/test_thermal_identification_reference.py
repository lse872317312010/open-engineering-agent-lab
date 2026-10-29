"""Hand integral signs, node order and heat storage before the implementation."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from thermal_identification_reference import integral_row, stored_energy  # noqa: E402


def test_internal_link_rows_are_equal_and_opposite():
    q = np.array([40.,30.,20.,50.,10.,0.])
    a, _ = integral_row(0, [1.]*6, q, [0.]*6, 25., 2.)
    b, _ = integral_row(1, [1.]*6, q, [0.]*6, 25., 2.)
    assert a[6] == 10. and b[6] == -10.
    assert b[7] == 10. and a[0] == b[1] == 1.


def test_case_ground_and_known_sink_heat_are_on_correct_sides():
    a, y = integral_row(2, [0.]*6, [0.,0.,70.,0.,0.,0.], [5.]*6, 25., 2.)
    assert a[11] == 20. and y == 5.
    b, z = integral_row(5, [0.]*6, [0.]*6, [5.]*6, 25., 2., 3.)
    assert b[11] == 0. and z == 2.
    assert stored_energy([30.]*6, np.array([25.]*6), [1,2,3,4,5,6]) == 105.
