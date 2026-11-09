"""Prescribed continuous speed ramps with actual FOC, copper integration and thermal feedback."""
import math

import numpy as np
import p7_cogging_model as cogging
from p7_cogging_simulation import OFFSET, TS
from p7_locked_electrical import OMEGA
from p7_stator_fast_rom import OUT as ROM
from p7_temperature_feedback import load_motor
from scipy.integrate import solve_ivp

from oeal.current_control import CurrentPIParameters, CurrentPIState, current_control_step
from oeal.foc import average_svpwm
from oeal.stator_feedback import StatorCopperFeedback
from oeal.transforms import inverse_park, park

TOTAL, BURN = .6, .2
CONTROL_COLUMNS = ("time_s", "theta_rad", "omega_rad_s", "id_a", "iq_a", "vd_v", "vq_v",
                   "source_j", "copper_j", "shaft_j", "balance_j", "held_r_ohm")
THERMAL_COLUMNS = ("time_s", "winding_c", "core_c", "storage_j", "boundary_w", "applied_r_ohm",
                   "next_r_ohm", "actual_window_copper_j", "predicted_window_copper_j",
                   "actual_copper_j", "predicted_copper_j", "thermal_balance_j")


def motion(at, direction, theta0=.23):
    values = np.asarray(at)
    up, down = values-.2, values-.4
    ratio = np.where(values <= .2, .5, np.where(values <= .4, .5+7.5*up, 2-7.5*down))
    integral = np.where(values <= .2, .5*values,
                        np.where(values <= .4, .1+.5*up+3.75*up**2,
                                 .35+2*down-3.75*down**2))
    return theta0+direction*OMEGA*integral, direction*OMEGA*ratio


def ramp_case(loss_map, direction, ambient, *, dt=5e-6, replay=False):
    controls, per_control = round(TOTAL/TS), round(TS/dt)
    count = controls*per_control
    times = np.linspace(0., TOTAL, 2*count+1)
    theta, omega = motion(times, direction)
    # Exact prescribed anchors avoid roundoff moving an endpoint outside the map rectangle.
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
    rows, commands, resistances = [], [], []
    initial_r = thermal.resistance_ohm
    thermal_rows = [np.r_[0., thermal.outputs, initial_r, initial_r, np.zeros(5)]]
    previous_copper = predicted = score_actual = score_predicted = 0.
    max_balance = max_heat_balance = max_domain = max_window_error = 0.
    limited, start_window = 0, 0
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
        command = current_control_step(controller, pi, reference_d_a=0.,
            reference_q_a=direction*.5, measured_d_a=float(state[0]), measured_q_a=float(state[1]),
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
                          state[2:], balance, resistance])
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
            sampled = [loss_map.mean_power(resistance, omega_rad_s=float(v),
                         iq_reference_a=direction*.5) for v in omega[2*start_window:2*end+1:2]]
            prediction = float(np.sum((np.array(sampled[:-1])+sampled[1:])*.5)*dt)
            actual = float(state[3]-previous_copper)
            previous_copper = float(state[3])
            predicted += prediction
            thermal.advance_window(end, float(state[3]))
            max_heat_balance = max(max_heat_balance, abs(thermal.balance_j))
            thermal_rows.append(np.r_[times[2*end], thermal.outputs, resistance,
                thermal.resistance_ohm, actual, prediction, state[3], predicted, thermal.balance_j])
            if tick+1 > round(BURN/TS):
                score_actual += actual
                score_predicted += prediction
                max_window_error = max(max_window_error, abs(prediction-actual)/actual)
            start_window = end
    voltage = np.array(park(*commands[-1], OFFSET+4*theta[-1]))
    balance = state[2]-state[3]-state[4]-motor.stored(theta[-1], state[:2])+initial
    rows.append(np.r_[TOTAL, theta[-1], omega[-1], state[:2], voltage,
                      state[2:], balance, resistance])
    trace = np.array(rows)
    dop_errors, dop_trace = np.zeros(4), np.empty((0, 5))
    if replay:
        dop_errors, dop_trace = ramp_replay(motor, direction, trace, commands, resistances)
    relative = abs(score_predicted-score_actual)/score_actual
    result = dict(direction=direction, ambient_c=ambient, dt_s=dt,
                  score_actual_copper_j=score_actual, score_predicted_copper_j=score_predicted,
                  relative_total_copper_error=relative, max_window_relative_error=max_window_error,
                  max_balance_j=max_balance, max_thermal_balance_j=max_heat_balance,
                  max_l1_current_a=max_domain, limited_commands=limited,
                  dop_performed=replay, dop_current_error_a=float(dop_errors[0]),
                  dop_energy_error_j=dop_errors[1:].tolist(),
                  passed=bool(relative <= .005 and max_window_error <= .05 and limited == 0
                              and max_balance <= 1e-6 and max_heat_balance <= 1e-8
                              and dop_errors[0] <= 1e-5 and max(dop_errors[1:]) <= 1e-7))
    arrays = dict(control=trace, stationary_commands=np.array(commands),
                  resistance_commands=np.array(resistances), thermal=np.array(thermal_rows),
                  dop_trace=dop_trace)
    return result, arrays


def ramp_replay(motor, direction, trace, commands, resistances):
    start = round(BURN/TS)
    state = np.r_[trace[start, 3:5], np.zeros(3)]
    errors, result_trace = np.zeros(4), [state.copy()]
    for tick in range(start, len(commands)):
        motor.resistance = resistances[tick]
        stationary = commands[tick]

        def rhs(at, values, held=stationary):
            theta, omega = motion(at, direction)
            voltage = np.array(park(*held, OFFSET+4*float(theta)))
            di, _, _ = motor.rhs(float(theta), float(omega), values[:2], voltage, 0.)
            powers = motor.powers(float(theta), float(omega), values[:2], voltage, 0.)
            shaft = float(omega)*motor.torque(float(theta), values[:2])[0]
            return np.r_[di, powers[:2], shaft]

        solved = solve_ivp(rhs, (tick*TS, (tick+1)*TS), state, method="DOP853",
                           rtol=1e-10, atol=1e-12)
        if not solved.success:
            raise ValueError("independent speed-ramp replay failed")
        state = solved.y[:, -1]
        expected = trace[tick+1, 7:10]-trace[start, 7:10]
        errors = np.maximum(errors, np.r_[max(abs(state[:2]-trace[tick+1, 3:5])),
                                         abs(state[2:]-expected)])
        result_trace.append(state.copy())
    return errors, np.array(result_trace)
