"""Independent limits and boundary identities, before the FE implementation."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from p7_contact_reference import (  # noqa: E402
    CASES,
    HEIGHT,
    PATCH,
    THICKNESS,
    LENGTH,
    SPLIT,
    constants,
    powers,
    temperature,
)


def test_zero_source_series_resistance():
    c = PATCH
    flux = (c["left_c"]-c["ambient_c"])/(
        SPLIT/c["k1"]+c["rc"]+(LENGTH-SPLIT)/c["k2"]+1/c["h"])
    assert powers(c)["interface_right_w"] == pytest.approx(flux*HEIGHT*THICKNESS)
    assert powers(c)["jump_k"] == pytest.approx(flux*c["rc"])


@pytest.mark.parametrize("case", CASES)
def test_contact_jump_robin_and_global_energy(case):
    q0, tl, tr = constants(case)
    qi = q0+case["s1"]*SPLIT
    assert tl-tr == pytest.approx(case["rc"]*qi)
    assert temperature(SPLIT, case, 10) == pytest.approx(tl)
    assert temperature(SPLIT, case, 20) == pytest.approx(tr)
    right_flux = qi+case["s2"]*(LENGTH-SPLIT)
    assert case["h"]*(temperature(LENGTH, case, 20)-case["ambient_c"]) == pytest.approx(
        right_flux)
    p = powers(case)
    assert p["left_out_w"]+p["right_out_w"] == pytest.approx(p["source_w"])


def test_ideal_contact_limit_matches_previous_reference():
    from p7_layered_reference import temperature as previous

    c = dict(CASES[0], rc=0.)
    for region, xs in ((10, np.linspace(0, SPLIT, 7)), (20, np.linspace(SPLIT, LENGTH, 7))):
        np.testing.assert_allclose(temperature(xs, c, region), previous(xs, c), atol=1e-12)
