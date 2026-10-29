"""Physical integral identities, exact recovery and insufficient-excitation rejection."""
import sys
from pathlib import Path

import numpy as np
import pytest

from oeal.thermal_identification import design_matrix, fit_network

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from thermal_identification_reference import EDGES, integral_row  # noqa: E402


def linear_packet():
    time = np.arange(801)*.05
    slope = np.array([.06,.04,.02,.08,.05,.03])
    capacity = np.array([80.,95.,220.,.7,30.,150.])
    resistance = np.array([.7,.55,2.2,.95,1.4])
    case_r = 2.6
    temp = 25.+time[:, None]*slope
    midpoint = (temp[1:]+temp[:-1])/2
    power = np.tile(capacity*slope, (len(midpoint), 1))
    for (a, b), r in zip(EDGES, resistance, strict=True):
        flow = (midpoint[:, a]-midpoint[:, b])/r
        power[:, a] += flow
        power[:, b] -= flow
    power[:, 2] += (midpoint[:, 2]-25.)/case_r
    power[:, 5] += (midpoint[:, 5]-25.)/3
    return time, temp, power, capacity, resistance, case_r


def test_design_matches_independent_hand_row_and_signed_incidence():
    time, temp, power, capacity, resistance, case_r = linear_packet()
    design, right, nodes = design_matrix(time, temp, power, 25., 0.)
    theta = np.r_[capacity, 1/resistance, 1/case_r]
    np.testing.assert_allclose(design @ theta, right, atol=1e-9, rtol=0)
    integral = 25.*20+(temp[400]-25.)*10
    expected, energy = integral_row(0, temp[400]-temp[0], integral,
                                    power[:400].sum(axis=0)*.05, 25., 20.)
    np.testing.assert_allclose(design[0], expected, atol=1e-10)
    assert abs(right[0]-energy) < 1e-9 and nodes[0] == 0


def test_bounded_solver_recovers_twelve_known_parameters_without_truth_arguments():
    pytest.importorskip("scipy")
    time, temp, power, capacity, resistance, case_r = linear_packet()
    before = temp.copy()
    fit = fit_network(time, temp, power, 25., 0.)
    np.testing.assert_allclose(fit["capacities_j_per_k"], capacity, rtol=1e-6)
    np.testing.assert_allclose(fit["link_resistances_k_per_w"], resistance, rtol=1e-6)
    assert abs(fit["case_resistance_k_per_w"]/case_r-1) < 1e-6
    assert fit["normalized_rank"] == 12 and not any(fit["active_bounds"])
    np.testing.assert_array_equal(temp, before)


def test_zero_excitation_and_invalid_sampling_cannot_produce_a_fit():
    pytest.importorskip("scipy")
    t = np.arange(801)*.05
    with pytest.raises(ValueError, match="excitation"):
        fit_network(t, np.full((len(t), 6), 25.), np.zeros((len(t)-1, 6)), 25.)
    with pytest.raises(ValueError, match="uniform"):
        design_matrix(t**1.01, np.full((len(t), 6), 25.), np.zeros((len(t)-1, 6)), 25.)
    with pytest.raises(ValueError, match="even"):
        design_matrix(np.arange(401)*.1, np.full((401, 6), 25.), np.zeros((400, 6)), 25.)
