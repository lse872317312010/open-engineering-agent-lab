"""Adapters that execute upstream motulator models, PWM events and diode transitions.

Requires the separately pinned Python 3.12 experiment environment.
No motulator solver, machine or converter equations are copied into OEAL.
"""

import math
from types import SimpleNamespace

import numpy as np
from motulator.common.model import Sensor
from motulator.common.model._simulation import SolverCfg
from motulator.common.utils import abc2complex, complex2abc
from motulator.drive import model, utils

from oeal.current_control import CurrentPIParameters, CurrentPIState, current_control_step
from oeal.refined_thermal import ThermalNetwork

CONTROL_COLUMNS = [
    "time_s", "id_a", "iq_a", "measured_id_a", "measured_iq_a", "iq_reference_a",
    "motor_angle_rad", "motor_speed_rad_s", "torque_nm", "bus_v", "vd_command_v",
    "vq_command_v", "voltage_limited", "current_limited", "integral_d_v", "integral_q_v",
    "copper_w", "core_w", "device_estimate_w", "winding_c", "junction_c", "enabled",
]


class DriveController:
    """OEAL current PI with observable states on an upstream event-driven plant."""

    def __init__(self, nominal, config, robot=None):
        self.nominal, self.config, self.robot = nominal, config, robot
        self.t = 0.0
        self.tick = 0
        self.pi = CurrentPIState()
        self.rows = []
        self.rng = np.random.default_rng(config.get("seed", 20261023))
        imperfect = config.get("sensors", False)
        self.sensor = Sensor(
            gain=[1.02, 0.99, 1.0] if imperfect else 1.0,
            offset=[0.03, -0.02, 0.01] if imperfect else 0.0,
            std=0.02 if imperfect else 0.0, rng=self.rng,
        )
        self.thermal = ThermalNetwork(period_s=config["period_s"])
        self.theta_continuous = 0.0
        self.last_theta = 0.0

    def get_enable(self):
        blocked = self.config.get("block_interval_s")
        return blocked is None or not blocked[0] <= self.t < blocked[1]

    def __call__(self, mdl):
        c, p = self.config, self.nominal
        dt = c["period_s"]
        theta = float(mdl.mechanics.out.theta_M)
        self.theta_continuous += math.remainder(theta - self.last_theta, 2 * math.pi)
        self.last_theta = theta
        speed = float(mdl.mechanics.out.w_M)
        true_i = complex(mdl.machine.out.i_s_dq)
        phase = np.asarray(complex2abc(mdl.machine.out.i_s_ab), dtype=float)
        measured = np.asarray(self.sensor(phase))
        theta_measured = theta
        if c.get("sensors", False):
            measured = np.round(np.clip(measured, -20, 20) / (40 / 4096)) * (40 / 4096)
            theta_measured = round(theta / (2 * math.pi / 16384)) * (2 * math.pi / 16384)
        measured_i = abc2complex(measured) * np.exp(-1j * p.n_p * theta_measured)
        iq_ref = c.get("iq_reference_a", 5.0) if self.t >= c["step_time_s"] else 0.0
        if self.robot is not None:
            iq_ref = self.robot.sample(self, mdl)
        bus = float(mdl.converter.out.u_dc)
        if bus <= 0:
            raise ValueError("DC bus left the positive-voltage model domain")
        bandwidth = c.get("bandwidth_per_s", 1000.0)
        parameters = CurrentPIParameters(
            p.L_d * bandwidth, p.R_s * bandwidth,
            p.L_q * bandwidth, p.R_s * bandwidth,
            bus / math.sqrt(3), c.get("current_limit_a", 15.0), bandwidth,
        )
        we = p.n_p * speed
        output = current_control_step(
            parameters, self.pi, reference_d_a=c.get("id_reference_a", 0.0),
            reference_q_a=iq_ref, measured_d_a=float(measured_i.real),
            measured_q_a=float(measured_i.imag), period_s=dt,
            feedforward_d_v=-we * p.L_q * measured_i.imag,
            feedforward_q_v=we * (p.L_d * measured_i.real + p.psi_f),
        )
        enabled = self.get_enable()
        self.pi = output.next_state if enabled else CurrentPIState()
        voltage = complex(output.vd_v, output.vq_v) if enabled else 0j
        # Space-vector common-mode injection, followed by upstream carrier comparison.
        u_abc = np.asarray(complex2abc(
            voltage * np.exp(1j * p.n_p * theta_measured)
        ))
        common = 0.5 * (u_abc.max() + u_abc.min())
        duties = np.clip(0.5 + (u_abc - common) / bus, 0, 1)
        resistance = float(mdl.machine.par.R_s)
        copper = 1.5 * resistance * abs(true_i) ** 2
        core_voltage = mdl.machine.inp.u_s_ab - resistance * mdl.machine.out.i_s_ab
        core = 1.5 * mdl.machine.par.G_c * abs(core_voltage) ** 2
        device = (
            c.get("device_drop_v", 0.0) * np.abs(phase).sum()
            + 1.5 * 0.02 * abs(true_i) ** 2
            + 6 * 20e-6 / dt * abs(true_i)
        )
        # Device switching heat is a declared research estimate, not transistor physics.
        temperatures = self.thermal.advance([copper, core, 0, device, 0, 0])
        if c.get("thermal_feedback", True):
            mdl.machine.par.R_s = p.R_s * (1 + 0.00393 * (temperatures[0] - 25))
        self.rows.append([
            self.t, true_i.real, true_i.imag, measured_i.real, measured_i.imag, iq_ref,
            self.theta_continuous, speed, float(mdl.machine.out.tau_M), bus,
            voltage.real, voltage.imag, float(output.voltage_limited),
            float(output.current_reference_limited), self.pi.integral_d_v,
            self.pi.integral_q_v, copper, core, device, temperatures[0],
            temperatures[3], float(enabled),
        ])
        self.tick += 1
        self.t = self.tick * dt
        return dt, duties

    def post_process(self):
        return SimpleNamespace(t=np.array([r[0] for r in self.rows]), samples=self.rows)


def make_drive(config, magnetic_map=None, robot=None):
    """Construct real upstream electrical, mechanical, converter and DC-bus models."""
    if magnetic_map is None:
        nominal = model.SynchronousMachinePars(
            n_p=7, R_s=0.3, L_d=0.0008, L_q=0.0008, psi_f=0.03
        )
        plant = model.SynchronousMachinePars(
            n_p=nominal.n_p, R_s=nominal.R_s, L_d=nominal.L_d,
            L_q=nominal.L_q, psi_f=nominal.psi_f, G_c=config.get("core_conductance_s", 0),
        )
    else:
        nominal, nonlinear = magnetic_map
        plant = nonlinear if config.get("nonlinear", False) else (
            model.SynchronousMachinePars(
                n_p=nominal.n_p, R_s=nominal.R_s, L_d=nominal.L_d,
                L_q=nominal.L_q, psi_f=nominal.psi_f,
            )
        )
    machine = model.SynchronousMachine(plant)
    if robot is not None:
        mechanics = model.MechanicalSystem(J=5e-5, B_L=1e-5)
    elif config.get("two_mass", False):
        mechanics = model.TwoMassMechanicalSystem(
            J_M=0.002, J_L=0.02 / 100, K_S=80 / 100, C_S=0.15 / 100, B_L=0.0002
        )
    else:
        mechanics = model.MechanicalSystem(J=config.get("inertia_kg_m2", 0.002), B_L=1e-5)
    mechanics.set_external_load_torque(
        lambda t: config.get("load_nm", 0.0)
        + (config.get("load_step_nm", 0.0) if t >= 0.015 else 0.0)
    )
    converter = model.VoltageSourceConverter(
        u_dc=None if config.get("dc_bus") else config["bus_v"],
        t_d=config.get("deadtime_s", 0.0), u_th=config.get("device_drop_v", 0.0),
    )
    dc_bus = None
    if config.get("dc_bus") == "capacitor":
        dc_bus = model.DCBus(C_dc=0.002, u_dc=config["bus_v"], converters=[converter])
        dc_bus.set_external_dc_current(
            lambda t: (config["bus_v"] - dc_bus.state.u_dc.real) / 0.15
        )
    elif config.get("dc_bus") == "diode":
        dc_bus = model.DiodeBridgeDCBus(
            C_dc=0.002, L_dc=0.001, U_g=config["bus_v"] / math.sqrt(2),
            f_g=50, converters=[converter],
        )
    drive = model.Drive(
        machine, mechanics, converter, dc_bus=dc_bus, pwm=config.get("pwm", True),
        delay=2 if config.get("delay", True) else 0, single_update=True,
    )
    drive.oeal_pwm_records = []
    upstream_pwm = drive.pwm
    elapsed = 0.0

    def record_pwm(period, duties):
        nonlocal elapsed
        intervals, gates, blanking = upstream_pwm(period, duties)
        for duration, q, b in zip(intervals, gates, blanking, strict=True):
            if duration > 0:
                drive.oeal_pwm_records.append([
                    elapsed, float(duration), *map(float, q), *map(float, b),
                    float(converter.inp.enabled),
                ])
            elapsed += float(duration)
        return intervals, gates, blanking

    drive.pwm = record_pwm
    controller = DriveController(nominal, config, robot)
    controller.drive = drive
    return drive, controller


def run_drive(config, magnetic_map=None, robot=None):
    drive, controller = make_drive(config, magnetic_map, robot)
    sim = model.Simulation(
        drive, controller, show_progress=False,
        cfg=SolverCfg(
            method="RK45", rtol=config.get("rtol", 1e-7), atol=1e-10,
            max_step=config.get("max_step_s", 10e-6),
        ),
    )
    result = sim.simulate(t_stop=config["duration_s"], N_eval=2)
    if not result.success:
        raise AssertionError("upstream motulator simulation did not finish")
    return result, controller


def load_magnetic_map(path):
    """Use the pinned upstream measured-map example and its interpolation/inversion."""
    data = np.load(path)
    flux = utils.MagneticModel(
        i_s_dq=data["i_s_dq"], psi_s_dq=data["psi_s_dq"], type="flux_map"
    )
    current = flux.invert()
    nonlinear = model.SaturatedSynchronousMachinePars(
        n_p=2, R_s=0.63, i_s_dq_fcn=current, psi_s_dq_fcn=flux
    )
    h = 0.01
    ld = float((complex(flux(h)).real - complex(flux(-h)).real) / (2 * h))
    lq = float((complex(flux(1j * h)).imag - complex(flux(-1j * h)).imag) / (2 * h))
    nominal = model.SynchronousMachinePars(
        n_p=2, R_s=0.63, L_d=ld, L_q=lq, psi_f=nonlinear.psi_f
    )
    return (nominal, nonlinear), flux, current
