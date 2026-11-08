"""Fixed-speed Fourier electrical plant with exact linear flow and quadratic work."""
import math

import numpy as np
import p7_cogging_model as cogging
from p7_cogging_simulation import OFFSET, TS
from scipy.integrate import solve_ivp
from scipy.linalg import expm

from oeal.current_control import CurrentPIParameters, CurrentPIState, current_control_step
from oeal.foc import average_svpwm
from oeal.transforms import inverse_park, park

PERIOD_S = .02
OMEGA = cogging.PERIOD/PERIOD_S
BURN, SCORE = 10, 5
DT = 5e-6
COLUMNS = ("time_s", "theta_rad", "id_a", "iq_a", "vd_v", "vq_v", "source_j",
           "copper_j", "electromagnetic_shaft_j", "balance_j")


def quadratic_flow(generator, forms, dt):
    """Return exp(H dt) and integrals of exp(Ht).T Q exp(Ht), without quadrature."""
    size = len(generator)
    advance = expm(generator*dt)
    integrals = []
    for form in forms:
        block = np.block([[-generator.T, form], [np.zeros_like(generator), generator]])
        integral = advance.T@expm(block*dt)[:size, size:]
        integrals.append((integral+integral.T)/2)
    return advance, np.array(integrals)


def augmented(current, voltage, theta):
    values = np.empty(17)
    values[:2], values[2:4], values[4] = current, voltage, 1.
    for n in range(1, 7):
        values[3+2*n:5+2*n] = math.cos(8*n*theta), math.sin(8*n*theta)
    return values


def generator_and_work(motor, omega):
    size, constant = 17, 4
    matrix = motor.inductance
    inverse = np.linalg.inv(matrix)
    rotation = cogging.JROT
    generator = np.zeros((size, size))
    generator[:2, :2] = -inverse@(motor.resistance*np.eye(2)+4*omega*rotation@matrix)
    generator[:2, 2:4] = inverse
    generator[2:4, 2:4] = -4*omega*rotation
    port = np.zeros((2, size))
    port[:, :2] = 4*rotation@matrix
    port[:, constant] = 4*rotation@motor.psi.a[0]
    magnetic = np.zeros((size, size))
    magnetic[:2, :2] = .75*matrix
    cog_work = np.zeros((size, size))
    for n in range(1, 7):
        cosine, sine, k = 3+2*n, 4+2*n, 8*n
        generator[cosine, sine], generator[sine, cosine] = -k*omega, k*omega
        port[:, cosine] = k*motor.psi.b[n]+4*rotation@motor.psi.a[n]
        port[:, sine] = -k*motor.psi.a[n]+4*rotation@motor.psi.b[n]
        a, b = float(motor.cog.a[n, 0]), float(motor.cog.b[n, 0])
        cog_work[constant, cosine] = cog_work[cosine, constant] = .5*omega*a
        cog_work[constant, sine] = cog_work[sine, constant] = .5*omega*b
        magnetic[constant, cosine] = magnetic[cosine, constant] = .5*b/k
        magnetic[constant, sine] = magnetic[sine, constant] = -.5*a/k
        magnetic[constant, constant] -= b/k
    generator[:2, constant:] = -omega*inverse@port[:, constant:]
    source = np.zeros((size, size))
    source[:2, 2:4] = source[2:4, :2] = .75*np.eye(2)
    copper = np.zeros((size, size))
    copper[:2, :2] = 1.5*motor.resistance*np.eye(2)
    selection = np.zeros((2, size))
    selection[:, :2] = np.eye(2)
    shaft = .75*omega*(selection.T@port+port.T@selection)+cog_work
    identity_error = float(np.max(abs(generator.T@magnetic+magnetic@generator
                                      -source+copper+shaft)))
    if identity_error > 1e-10:
        raise ValueError("electrical work identity failed")
    return generator, np.stack((source, copper, shaft)), magnetic, identity_error


def simulate_locked(motor, direction, theta0, *, replay=False):
    omega = direction*OMEGA
    generator, work, magnetic, identity = generator_and_work(motor, omega)
    advance, integrals = quadratic_flow(generator, work, DT)
    per_control, per_cycle = round(TS/DT), round(PERIOD_S/TS)
    count = (BURN+SCORE)*per_cycle
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
            parameters, pi, reference_d_a=0., reference_q_a=direction*.5,
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
    first = (BURN+SCORE-1)*per_cycle
    periodic = float(np.max(abs(trace[first:first+per_cycle+1, 2:4]
                                -trace[first-per_cycle:first+1, 2:4])))
    cycle_power = cycles[-SCORE:, 1]/PERIOD_S
    mean = float(np.mean(cycle_power))
    spread = float(np.ptp(cycle_power)/mean)
    reference_errors = np.zeros(4)
    reference_trace = np.empty((0, 5))
    if replay:
        reference_errors, reference_trace = dop_replay(motor, omega, theta0, trace, commands)
    metrics = dict(direction=direction, resistance_ohm=motor.resistance, theta0_rad=theta0,
                   omega_rad_s=omega, burn_cycles=BURN, score_cycles=SCORE,
                   mean_copper_w=mean, ideal_copper_w=1.5*motor.resistance*.25,
                   ideal_relative_bias=1.5*motor.resistance*.25/mean-1,
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
                  cycle_mean_copper_w=cycles[:, 1]/PERIOD_S, dop_trace=reference_trace)
    return metrics, arrays


def dop_replay(motor, omega, theta0, trace, commands):
    start = BURN*round(PERIOD_S/TS)
    state = np.r_[trace[start, 2:4], np.zeros(3)]
    errors = np.zeros(4)
    result_trace = [state.copy()]
    for tick in range(start, len(commands)):
        stationary = commands[tick]

        def rhs(at, values, held=stationary):
            theta = theta0+omega*at
            voltage = np.array(park(*held, OFFSET+4*theta))
            di, _, _ = motor.rhs(theta, omega, values[:2], voltage, 0.)
            powers = motor.powers(theta, omega, values[:2], voltage, 0.)
            shaft = omega*motor.torque(theta, values[:2])[0]
            return np.r_[di, powers[:2], shaft]

        result = solve_ivp(rhs, (tick*TS, (tick+1)*TS), state, method="DOP853",
                           rtol=1e-10, atol=1e-12)
        if not result.success:
            raise ValueError("independent locked-speed replay failed")
        state = result.y[:, -1]
        expected_energy = trace[tick+1, 6:9]-trace[start, 6:9]
        errors = np.maximum(errors, np.r_[max(abs(state[:2]-trace[tick+1, 2:4])),
                                         abs(state[2:]-expected_energy)])
        result_trace.append(state.copy())
    return errors, np.array(result_trace)
