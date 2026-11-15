"""Current-reference endpoint runner; parent fixed-reference implementation is unchanged."""
import math

import numpy as np
import p7_cogging_model as cogging
from p7_cogging_simulation import OFFSET, TS
from p7_locked_electrical import (
    BURN,
    DT,
    OMEGA,
    PERIOD_S,
    SCORE,
    augmented,
    dop_replay,
    generator_and_work,
    quadratic_flow,
)

from oeal.current_control import CurrentPIParameters, CurrentPIState, current_control_step
from oeal.foc import average_svpwm
from oeal.transforms import inverse_park, park


def simulate_reference(motor, direction, theta0, *, reference_abs_a=0., replay=False,
                       omega_abs_rad_s=OMEGA, repeat_s=PERIOD_S,
                       burn_cycles=BURN, score_cycles=SCORE):
    per_cycle = round(repeat_s/TS)
    periods = omega_abs_rad_s*repeat_s/cogging.PERIOD
    if (direction not in (-1., 1.) or not math.isfinite(theta0)
            or not math.isfinite(omega_abs_rad_s) or omega_abs_rad_s <= 0
            or not math.isclose(per_cycle*TS, repeat_s, rel_tol=0, abs_tol=1e-12)
            or periods < 1 or not math.isclose(periods, round(periods), abs_tol=1e-10)
            or type(burn_cycles) is not int or burn_cycles < 1
            or type(score_cycles) is not int or score_cycles < 2
            or not math.isfinite(reference_abs_a) or not 0 <= reference_abs_a <= .5):
        raise ValueError("aligned repeat period, positive speed and integer cycle counts required")
    omega = direction*omega_abs_rad_s
    generator, work, magnetic, identity = generator_and_work(motor, omega)
    advance, integrals = quadratic_flow(generator, work, DT)
    per_control = round(TS/DT)
    count = (burn_cycles+score_cycles)*per_cycle
    matrix = motor.inductance
    parameters = CurrentPIParameters(matrix[0, 0]*1000, .3*1000,
                                     matrix[1, 1]*1000, .3*1000,
                                     48/math.sqrt(3), 1., 1000.)
    pi = CurrentPIState()
    current = np.zeros(2)
    energy = np.zeros(3)
    initial = motor.stored(theta0, current)
    rows, commands, cycles = [], [], []
    cycle_start = energy.copy()
    max_balance = max_domain = max_storage = 0.
    limited = 0
    voltage = np.zeros(2)
    for tick in range(count):
        theta = theta0+omega*tick*TS
        feedforward = omega*(motor.psi.derivative(theta)+4*cogging.JROT@motor.flux(theta, current))
        command = current_control_step(
            parameters, pi, reference_d_a=0., reference_q_a=direction*reference_abs_a,
            measured_d_a=float(current[0]), measured_q_a=float(current[1]), period_s=TS,
            feedforward_d_v=float(feedforward[0]), feedforward_q_v=float(feedforward[1]))
        pi = command.next_state
        stationary = inverse_park(command.vd_v, command.vq_v, OFFSET+4*theta)
        alpha, beta, _ = average_svpwm(*stationary, 48.)
        stationary = np.array([alpha, beta])
        voltage = np.array(park(*stationary, OFFSET+4*theta))
        limited += int(command.voltage_limited or command.current_reference_limited)
        values = augmented(current, voltage, theta)
        balance = energy[0]-energy[1]-energy[2]-motor.stored(theta, current)+initial
        rows.append(np.r_[tick*TS, theta, current, voltage, energy, balance])
        commands.append(stationary)
        for _ in range(per_control):
            energy += np.einsum("i,kij,j->k", values, integrals, values)
            values = advance@values
            domain = float(sum(abs(values[:2])))
            if not np.isfinite(values).all() or domain > 2:
                raise ValueError("fixed-speed electrical current outside validated domain")
            max_domain = max(max_domain, domain)
            stored = float(values@magnetic@values)
            max_balance = max(max_balance, abs(float(energy[0]-energy[1]-energy[2]-stored+initial)))
        current = values[:2].copy()
        end_theta = theta0+omega*(tick+1)*TS
        max_storage = max(max_storage, abs(float(values@magnetic@values)
                                           -motor.stored(end_theta, current)))
        if (tick+1) % per_cycle == 0:
            cycles.append(energy-cycle_start)
            cycle_start = energy.copy()
    theta = theta0+omega*count*TS
    voltage = np.array(park(*commands[-1], OFFSET+4*theta))
    balance = energy[0]-energy[1]-energy[2]-motor.stored(theta, current)+initial
    rows.append(np.r_[count*TS, theta, current, voltage, energy, balance])
    trace, cycles = np.array(rows), np.array(cycles)
    first = (burn_cycles+score_cycles-1)*per_cycle
    periodic = float(np.max(abs(trace[first:first+per_cycle+1, 2:4]
                                -trace[first-per_cycle:first+1, 2:4])))
    cycle_power = cycles[-score_cycles:, 1]/repeat_s
    mean = float(np.mean(cycle_power))
    spread = float(np.ptp(cycle_power)/mean)
    reference_errors = np.zeros(4)
    reference_trace = np.empty((0, 5))
    if replay:
        reference_errors, reference_trace = dop_replay(
            motor, omega, theta0, trace, commands, start_control=burn_cycles*per_cycle)
    metrics = dict(reference_abs_a=reference_abs_a, direction=direction,
                   resistance_ohm=motor.resistance, theta0_rad=theta0,
                   omega_rad_s=omega, burn_cycles=burn_cycles, score_cycles=score_cycles,
                   repeat_s=repeat_s, mechanical_periods_per_repeat=round(periods),
                   mean_copper_w=mean, ideal_copper_w=1.5*motor.resistance*reference_abs_a**2,
                   ideal_relative_bias=1.5*motor.resistance*reference_abs_a**2/mean-1,
                   periodic_current_difference_a=periodic, cycle_power_relative_spread=spread,
                   max_balance_j=max_balance, max_storage_crosscheck_j=max_storage,
                   work_identity_error=identity, max_l1_current_a=max_domain,
                   limited_commands=limited, dop_performed=replay,
                   dop_current_error_a=float(reference_errors[0]),
                   dop_energy_error_j=reference_errors[1:].tolist(),
                   passed=bool(limited == 0 and periodic <= 1e-5 and spread <= 1e-4
                               and max_balance <= 1e-8 and max_storage <= 1e-10
                               and reference_errors[0] <= 1e-6
                               and max(reference_errors[1:]) <= 1e-8))
    arrays = dict(control=trace, stationary_commands=np.array(commands), cycle_energy_j=cycles,
                  cycle_mean_copper_w=cycles[:, 1]/repeat_s, dop_trace=reference_trace)
    return metrics, arrays


def quadratic_moments(gram, zero_states, full_states, reference_max, duration_s):
    """Copper Gram moments of the affine current response, coefficient order a,b,c."""
    difference = (full_states-zero_states)/reference_max
    a = np.einsum("ni,ij,nj->", difference, gram, difference)/duration_s
    b = 2*np.einsum("ni,ij,nj->", zero_states, gram, difference)/duration_s
    c = np.einsum("ni,ij,nj->", zero_states, gram, zero_states)/duration_s
    return np.array([a, b, c])


def control_states(trace):
    return np.array([augmented(row[2:4], row[4:6], row[1]) for row in trace])


