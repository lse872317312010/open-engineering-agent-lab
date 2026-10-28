"""Energy-conserving thermal extension of the pinned upstream drive.

The upstream machine, converter, mechanics and integrator remain unchanged.
One auxiliary subsystem integrates physical heat and measured port powers.
An explicitly declared equivalent DC shunt supplies extra device heating.
"""

from numbers import Real
from types import SimpleNamespace

import numpy as np
from motulator.common.model import Subsystem, SubsystemTimeSeries

from oeal.energy import (
    ENERGY_COLUMNS,
    INTEGRALS,
    TEMPERATURES,
    auxiliary_device_power,
    linear_magnetic_energy,
    thermal_energy,
)
from oeal.refined_thermal import AMBIENT_LINKS, CAPACITIES, NAMES, ThermalNetwork


def value(signal, t):
    return signal(t) if callable(signal) else signal


class EnergyTimeSeries(SubsystemTimeSeries):
    def __init__(self, subsystem):
        for name, values in subsystem._history.items():
            setattr(self, name, np.real(np.asarray(values)))


class EnergySubsystem(Subsystem):
    def __init__(self, drive, config, bridge_current, robot, thermal_provider=None):
        self.drive, self.config, self.bridge_current, self.robot = (
            drive, config, bridge_current, robot
        )
        self.network = ThermalNetwork(period_s=config["period_s"])
        self.thermal_provider = thermal_provider  # trusted object, never an experiment JSON path
        self.provider_state_names = tuple(getattr(thermal_provider, "energy_state_names", ()))
        if self.provider_state_names not in ((), (
                "case_out_j", "convection_out_j", "radiation_out_j")):
            raise ValueError("unsupported thermal provider energy states")
        initial = np.asarray(getattr(thermal_provider, "initial_temperatures_c", [25.]*6),
                             dtype=float)
        if initial.shape != (6,) or not np.all(np.isfinite(initial)):
            raise ValueError("thermal provider needs six finite initial temperatures")
        self.custom_capacities = hasattr(thermal_provider, "capacities_j_per_k")
        declared = np.asarray(getattr(thermal_provider, "capacities_j_per_k", CAPACITIES),
                              dtype=object)
        if (declared.shape != (6,) or any(
                isinstance(v, (bool, np.bool_)) or not isinstance(v, Real) for v in declared)):
            raise ValueError("thermal provider needs six real capacities")
        self.capacities = np.array(declared, dtype=float, copy=True)
        if (self.capacities.shape != (6,) or not np.all(np.isfinite(self.capacities))
                or np.any(self.capacities <= 0)):
            raise ValueError("thermal provider needs six finite positive capacities")
        self.capacities.setflags(write=False)
        self.resistance_25 = float(drive.machine.par.R_s)
        self.inp, self.out = None, SimpleNamespace()
        self.state = SimpleNamespace(**{
            **dict(zip(TEMPERATURES, initial, strict=True)), **dict.fromkeys(INTEGRALS, 0.0),
            **dict.fromkeys(self.provider_state_names, 0.0)
        })
        if config.get("coupling_method") == "midpoint_predictor":
            self.state.motor_torque_impulse_nms = 0.0
            self.state.motor_torque_time_moment_nms2 = 0.0
        self.initial_storage = self.storage()

    @property
    def temperatures(self):
        return np.array([float(getattr(self.state, n).real) for n in TEMPERATURES])

    def storage(self):
        machine, mechanics = self.drive.machine, self.drive.mechanics
        p = machine.par
        magnetic = float(linear_magnetic_energy(
            machine.state.psi_s_dq, p.L_d, p.L_q, p.psi_f
        ))
        kinetic = 0.5 * mechanics.J * float(mechanics.state.w_M.real) ** 2
        bus = self.drive.dc_bus
        capacitor = 0 if bus is None else 0.5 * bus.C_dc * float(bus.state.u_dc.real) ** 2
        thermal = (float((self.temperatures-25.) @ self.capacities) if self.custom_capacities
                   else float(thermal_energy(self.temperatures, 25.0)))
        return dict(magnetic_j=magnetic, kinetic_j=kinetic, bus_j=capacitor, thermal_j=thermal)

    def powers(self, t):
        drive = self.drive
        converter, machine, mechanics = drive.converter, drive.machine, drive.mechanics
        voltage = float(converter.out.u_dc)
        current = complex(machine.out.i_s_ab)
        bridge = voltage * float(self.bridge_current(converter.inp))
        ac = 1.5 * float((machine.inp.u_s_ab * np.conj(current)).real)
        auxiliary = float(auxiliary_device_power(
            current, self.config["period_s"], converter.inp.enabled
        ))
        conduction = bridge - ac
        copper = 1.5 * machine.par.R_s * abs(current) ** 2
        speed = float(mechanics.state.w_M.real)
        friction = float(value(mechanics.B_L, speed)) * speed ** 2
        load = float(value(mechanics.inp.tau_L, t)) * speed
        imported = 0.0 if self.robot is None else self.robot.thermal_power_w
        temperatures = self.temperatures
        ambient = sum(
            (temperatures[node] - 25) / resistance
            for node, resistance in AMBIENT_LINKS
        )
        if drive.dc_bus is None:
            source = bridge + auxiliary
        else:
            external = drive.dc_bus.inp.i_dc
            source = voltage * (0 if external is None else float(value(external, t)))
        powers = dict(
            source_w=source, copper_w=copper, conduction_w=conduction,
            auxiliary_device_w=auxiliary, rotor_friction_w=friction,
            load_w=load, shaft_heat_import_w=imported, ambient_w=ambient,
        )
        rates = dict(
            source_j=source, source_abs_j=abs(source), bridge_j=bridge, ac_j=ac,
            copper_j=copper, conduction_j=conduction, auxiliary_device_j=auxiliary,
            rotor_friction_j=friction, load_work_j=load,
            shaft_heat_import_j=imported, ambient_j=ambient,
        )
        heat = np.array([copper, 0, friction + imported, conduction + auxiliary, 0, 0])
        return powers, rates, heat

    def set_outputs(self, t):
        pass

    def _provider_rates(self, t, heat, *, accepted=False):
        heat_j = sum(float(getattr(self.state, n).real) for n in (
            "copper_j", "conduction_j", "auxiliary_device_j", "rotor_friction_j",
            "shaft_heat_import_j",
        ))
        extra = {}
        if self.provider_state_names:
            extra["branch_energy_j"] = [
                float(getattr(self.state, n).real) for n in self.provider_state_names
            ]
            if abs(sum(extra["branch_energy_j"])-float(self.state.ambient_j.real)) > 1e-8:
                raise ValueError("thermal provider branch state sum disagrees with ambient energy")
        response = np.asarray(self.thermal_provider.evaluate(
            t, self.temperatures, heat, heat_j, float(self.state.ambient_j.real),
            accepted=accepted, **extra,
        ), dtype=float)
        if (response.shape != (8+len(self.provider_state_names),)
                or not np.all(np.isfinite(response))):
            raise ValueError("thermal provider returned invalid thermal/energy derivatives")
        if abs(response[6]-sum(heat)) > 1e-8:
            raise ValueError("thermal provider input power disagrees with actual heat")
        if abs(self.capacities @ response[:6]+response[7]-sum(heat)) > 1e-8:
            raise ValueError("thermal provider violates six-node power balance")
        if self.provider_state_names and abs(sum(response[8:])-response[7]) > 1e-8:
            raise ValueError("thermal provider branch powers disagree with total ambient power")
        return response

    def rhs(self, t):
        _, rates, heat = self.powers(t)
        if self.thermal_provider is None:
            thermal = self.network.rates(self.temperatures, heat)
        else:
            response = self._provider_rates(t, heat)
            thermal, rates["ambient_j"] = response[:6], response[7]
        derivatives = [*thermal, *[rates[name] for name in INTEGRALS]]
        if self.provider_state_names:
            derivatives.extend(response[8:])
        if hasattr(self.state, "motor_torque_impulse_nms"):
            torque = float(self.drive.machine.out.tau_M)
            derivatives.extend([torque, t * torque])
        return derivatives

    def snapshot(self, t):
        powers, _, heat = self.powers(t)
        if self.thermal_provider is not None:
            powers["ambient_w"] = self._provider_rates(t, heat, accepted=True)[7]
        integrals = {n: float(getattr(self.state, n).real) for n in INTEGRALS}
        storage = self.storage()
        delta = sum(storage[n] - self.initial_storage[n] for n in storage)
        residual = (integrals["source_j"] + integrals["shaft_heat_import_j"]
                    - integrals["load_work_j"] - delta - integrals["ambient_j"])
        heat = sum(integrals[n] for n in (
            "copper_j", "conduction_j", "auxiliary_device_j", "rotor_friction_j",
            "shaft_heat_import_j",
        ))
        thermal_residual = (heat - (storage["thermal_j"] - self.initial_storage["thermal_j"])
                            - integrals["ambient_j"])
        row = dict(
            time_s=t, **integrals, **storage, local_residual_j=residual,
            thermal_residual_j=thermal_residual, **dict(zip(
                TEMPERATURES, self.temperatures, strict=True
            )), **powers,
        )
        return [float(row[n]) for n in ENERGY_COLUMNS]

    def describe(self):
        bus = self.drive.dc_bus
        mechanics = self.drive.mechanics
        description = {
            "boundary": "DC feed port + linear PMSM + rotor + six thermal nodes",
            "thermal_nodes": list(NAMES),
            "capacities_j_per_k": self.capacities.tolist(),
            "conductance_w_per_k": self.network.conductance.tolist(),
            "ambient_c": self.network.ambient_c,
            "rotor_inertia_kg_m2": mechanics.J,
            "rotor_viscous_nms": mechanics.B_L,
            "capacitor_f": 0.0 if bus is None else bus.C_dc,
            "resistance_at_25c_ohm": self.resistance_25,
            "copper_alpha_per_k": 0.00393,
            "additional_device_on_resistance_ohm": 0.02,
            "switching_energy_coefficient_j_per_a": 20e-6,
            "source_port": "fixed DC converter input" if bus is None
            else "Vbus * external feed current; feed resistor outside boundary",
            "thermal_semantics": "continuous states in the upstream electrical solver",
            "torque_impulse_semantics": "integral of actual torque; predictor-only, N*m*s",
            "torque_moment_semantics": "integral of solver-time * torque; N*m*s^2",
        }

        if self.thermal_provider is not None:
            description["thermal_provider"] = self.thermal_provider.describe()
            description["ambient_c"] = getattr(self.thermal_provider, "ambient_c", 25.)
            description["conductance_role"] = "native fallback; thermal_provider is authoritative"
            description["thermal_semantics"] = "provider derivatives in upstream continuous solver"
        return description

    def create_time_series(self, t):
        return "energy", EnergyTimeSeries(self)


def attach_energy(drive, config, robot=None, *, thermal_provider=None):
    """Attach the opt-in extension using the fixed upstream subsystem API."""
    original_dc = drive.converter.compute_internal_dc_current
    energy = EnergySubsystem(drive, config, original_dc, robot, thermal_provider)
    converter = drive.converter

    def with_device_shunt(inp):
        bus = converter.u_dc if inp.u_dc is None else inp.u_dc
        return original_dc(inp) + auxiliary_device_power(
            inp.i_c_ab, config["period_s"], inp.enabled
        ) / bus

    converter.compute_internal_dc_current = with_device_shunt
    drive.subsystems.append(energy)
    drive._outgoing[energy] = []
    energy.init_state_history()
    original_outputs = drive.set_outputs

    def coupled_outputs(t):
        if config.get("thermal_feedback", True):
            drive.machine.par.R_s = energy.resistance_25 * (
                1 + 0.00393 * (energy.temperatures[0] - 25)
            )
        original_outputs(t)

    drive.set_outputs = coupled_outputs
    drive.oeal_energy = energy
    return energy
