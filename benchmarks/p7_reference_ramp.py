"""Reference slew/step FOC holdouts; unready periodic estimates remain in the evidence."""
import math

import numpy as np
import p7_cogging_model as cogging
from p7_cogging_simulation import OFFSET, TS
from p7_locked_electrical import OMEGA
from p7_speed_ramp import BURN, TOTAL, ramp_replay
from p7_speed_ramp import CONTROL_COLUMNS as BASE_CONTROL_COLUMNS
from p7_speed_ramp import THERMAL_COLUMNS as BASE_THERMAL_COLUMNS
from p7_speed_ramp import motion as base_motion
from p7_stator_fast_rom import OUT as ROM
from p7_temperature_feedback import load_motor

from oeal.current_control import CurrentPIParameters, CurrentPIState, current_control_step
from oeal.foc import average_svpwm
from oeal.reference_validity import ReferenceSettlingGuard
from oeal.stator_feedback import StatorCopperFeedback
from oeal.transforms import inverse_park, park

CONTROL_COLUMNS = BASE_CONTROL_COLUMNS+("reference_q_a", "reference_ready")
THERMAL_COLUMNS = BASE_THERMAL_COLUMNS+("reference_window_ready",)


def reference_values(control_tick, profile):
    ticks = np.asarray(control_tick)
    if profile == "step":
        return np.where(ticks < 4000, .25, np.where(ticks < 8000, .5, .125))
    if profile == "smooth":
        return np.where(ticks <= 4000, .125,
            np.where(ticks <= 8000, .125+.325*(ticks-4000)/4000,
                     .45-.325*(ticks-8000)/4000))
    raise ValueError("unknown current-reference profile")


def kinematics(at, direction, profile):
    if profile == "smooth":
        return base_motion(at, direction)
    if profile == "step":
        values = np.asarray(at)
        return .23+direction*OMEGA*values, np.full_like(values, direction*OMEGA, dtype=float)
    raise ValueError("unknown current-reference profile")


def reference_case(loss_map, direction, ambient, profile="smooth", *, dt=5e-6, replay=False):
    if replay and profile != "smooth":
        raise ValueError("DOP replay is defined for the smooth-motion profile")
    controls, per_control = round(TOTAL/TS), round(TS/dt)
    count = controls*per_control
    times = np.linspace(0., TOTAL, 2*count+1)
    theta, omega = kinematics(times, direction, profile)
    # Exact prescribed anchors avoid roundoff moving an endpoint outside the map rectangle.
    if profile == "smooth":
        for at, ratio in ((0., .5), (.2, .5), (.4, 2.), (.6, .5)):
            omega[round(at/(dt/2))] = direction*OMEGA*ratio
    thermal = StatorCopperFeedback.from_npz(ROM / "inference.npz", h_w_m2_k=20.,
        drive_dt_s=dt, ticks_per_window=round(.0025/dt), ambient_c=ambient)
    motor = load_motor(thermal.resistance_ohm)
    harmonic = np.arange(7)*8
    cosines, sines = np.cos(theta[:, None]*harmonic), np.sin(theta[:, None]*harmonic)
    psi = cosines@motor.psi.a+sines@motor.psi.b
    psi_derivative = (-sines*harmonic)@motor.psi.a+(cosines*harmonic)@motor.psi.b
    port = psi_derivative+4*psi@cogging.JROT.T
    cog = (cosines@motor.cog.a+sines@motor.cog.b).ravel()
    cosine, sine = np.cos(OFFSET+4*theta), np.sin(OFFSET+4*theta)
    inverse = np.linalg.inv(motor.inductance)
    rotational = 4*cogging.JROT@motor.inductance
    matrix = motor.inductance
    controller = CurrentPIParameters(matrix[0, 0]*1000, 300., matrix[1, 1]*1000, 300.,
                                     48/math.sqrt(3), 1., 1000.)
    pi = CurrentPIState()
    state = np.zeros(5)
    initial = motor.stored(.23, state[:2])
    rows, commands, resistances, references = [], [], [], []
    guard = ReferenceSettlingGuard(period_s=TS)
    initial_r = thermal.resistance_ohm
    thermal_rows = [np.r_[0., thermal.outputs, initial_r, initial_r, np.zeros(6)]]
    previous_copper = predicted = score_actual = score_predicted = 0.
    max_balance = max_heat_balance = max_domain = max_window_error = 0.
    limited, start_window = 0, 0
    unready, max_unready, all_actual, all_predicted = 0, 0., 0., 0.
    eligible_windows = 0
    resistance = initial_r
    voltage = np.zeros(2)

    def rhs(index, values, stationary, resistance_ohm):
        current = values[:2]
        if not np.isfinite(values).all() or sum(abs(current)) > 2:
            raise ValueError("ramp RK stage outside current domain")
        voltage = np.array([stationary[0]*cosine[index]+stationary[1]*sine[index],
                            -stationary[0]*sine[index]+stationary[1]*cosine[index]])
        work_port = port[index]+rotational@current
        di = inverse@(voltage-resistance_ohm*current-omega[index]*work_port)
        powers = (1.5*np.dot(voltage, current), 1.5*resistance_ohm*np.dot(current, current),
                  omega[index]*(1.5*np.dot(current, work_port)+cog[index]))
        return np.r_[di, powers]

    for tick in range(controls):
        index = 2*tick*per_control
        resistance = thermal.resistance_ohm
        motor.resistance = resistance
        feedforward = omega[index]*(port[index]+rotational@state[:2])
        reference = direction*float(reference_values(tick, profile))
        ready = guard.observe(tick, reference)
        references.append(reference)
        command = current_control_step(controller, pi, reference_d_a=0.,
            reference_q_a=reference, measured_d_a=float(state[0]), measured_q_a=float(state[1]),
            period_s=TS, feedforward_d_v=float(feedforward[0]),
            feedforward_q_v=float(feedforward[1]))
        pi = command.next_state
        stationary = inverse_park(command.vd_v, command.vq_v, OFFSET+4*theta[index])
        alpha, beta, _ = average_svpwm(*stationary, 48.)
        stationary = np.array([alpha, beta])
        voltage = np.array(park(*stationary, OFFSET+4*theta[index]))
        limited += int(command.voltage_limited or command.current_reference_limited)
        balance = state[2]-state[3]-state[4]-motor.stored(theta[index], state[:2])+initial
        rows.append(np.r_[tick*TS, theta[index], omega[index], state[:2], voltage,
                          state[2:], balance, resistance, reference, float(ready)])
        commands.append(stationary)
        resistances.append(resistance)
        for substep in range(per_control):
            point = index+2*substep
            k1 = rhs(point, state, stationary, resistance)
            k2 = rhs(point+1, state+dt*k1/2, stationary, resistance)
            k3 = rhs(point+1, state+dt*k2/2, stationary, resistance)
            k4 = rhs(point+2, state+dt*k3, stationary, resistance)
            state = state+dt*(k1+2*k2+2*k3+k4)/6
            motor.current(state[:2])
            max_domain = max(max_domain, float(sum(abs(state[:2]))))
        end = (tick+1)*per_control
        balance = state[2]-state[3]-state[4]-motor.stored(theta[2*end], state[:2])+initial
        max_balance = max(max_balance, abs(float(balance)))
        if (tick+1) % 50 == 0:
            prediction = 0.
            for control in range(start_window//per_control, tick+1):
                left, right = 2*control*per_control, 2*(control+1)*per_control
                sampled = [loss_map.mean_power(resistance, omega_rad_s=float(v),
                    iq_reference_a=references[control]) for v in omega[left:right+1:2]]
                prediction += float(np.sum((np.array(sampled[:-1])+sampled[1:])*.5)*dt)
            eligible = guard.window_ready(start_window//per_control, tick+1)
            actual = float(state[3]-previous_copper)
            previous_copper = float(state[3])
            predicted += prediction
            thermal.advance_window(end, float(state[3]))
            max_heat_balance = max(max_heat_balance, abs(thermal.balance_j))
            thermal_rows.append(np.r_[times[2*end], thermal.outputs, resistance,
                thermal.resistance_ohm, actual, prediction, state[3], predicted,
                thermal.balance_j, float(eligible)])
            if tick+1 > round(BURN/TS):
                error = abs(prediction-actual)/actual
                all_actual += actual
                all_predicted += prediction
                if eligible:
                    score_actual += actual
                    score_predicted += prediction
                    max_window_error = max(max_window_error, error)
                    eligible_windows += 1
                else:
                    unready += 1
                    max_unready = max(max_unready, error)
            start_window = end
    voltage = np.array(park(*commands[-1], OFFSET+4*theta[-1]))
    balance = state[2]-state[3]-state[4]-motor.stored(theta[-1], state[:2])+initial
    rows.append(np.r_[TOTAL, theta[-1], omega[-1], state[:2], voltage,
                      state[2:], balance, resistance, reference, float(ready)])
    trace = np.array(rows)
    dop_errors, dop_trace = np.zeros(4), np.empty((0, 5))
    if replay:
        dop_errors, dop_trace = ramp_replay(motor, direction, trace, commands, resistances)
    relative = abs(score_predicted-score_actual)/score_actual
    result = dict(profile=profile, direction=direction, ambient_c=ambient, dt_s=dt,
                  eligible_windows=eligible_windows, unready_scored_windows=unready,
                  max_unready_window_relative_error=max_unready,
                  unguarded_total_copper_error=abs(all_predicted-all_actual)/all_actual,
                  score_actual_copper_j=score_actual, score_predicted_copper_j=score_predicted,
                  relative_total_copper_error=relative, max_window_relative_error=max_window_error,
                  max_balance_j=max_balance, max_thermal_balance_j=max_heat_balance,
                  max_l1_current_a=max_domain, limited_commands=limited,
                  dop_performed=replay, dop_current_error_a=float(dop_errors[0]),
                  dop_energy_error_j=dop_errors[1:].tolist(),
                  passed=bool(relative <= .005 and max_window_error <= .05 and limited == 0
                              and max_balance <= 1e-6 and max_heat_balance <= 1e-8
                              and dop_errors[0] <= 1e-5 and max(dop_errors[1:]) <= 1e-7
                              and (profile != "step" or unready >= 16)))
    arrays = dict(control=trace, stationary_commands=np.array(commands),
                  resistance_commands=np.array(resistances),
                  reference_commands=np.array(references),
                  thermal=np.array(thermal_rows),
                  dop_trace=dop_trace)
    return result, arrays

