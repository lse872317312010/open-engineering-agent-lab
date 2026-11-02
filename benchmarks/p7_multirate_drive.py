"""Actual motulator FOC, integrated heat windows and 400 Hz contact-ROM feedback."""
import gzip
import importlib.metadata
import json
import platform
import resource
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from motulator.common.model import Subsystem, SubsystemTimeSeries
from motulator.common.model._simulation import SolverCfg
from motulator.drive import model
from p7_rom import hashes, kernel, rms
from scipy.sparse import load_npz

from oeal.backends.energy import value
from oeal.backends.motulator import CONTROL_COLUMNS, make_drive
from oeal.energy import linear_magnetic_energy
from oeal.multirate import ThermalWindowClock
from oeal.thermal_rom import AffineThermalROM

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-multirate"
BUNDLE = ROOT / "outputs/p7-param-rom"
DT = 50e-6
TICKS = 5000
J_FIELDS = ("copper_j", "device_j", "source_j", "ac_j", "load_j", "friction_j")
RHS_COLUMNS = ("time_s", "resistance_ohm", "current_abs_a", "dc_w", "ac_w",
               "copper_w", "device_w", "load_w", "friction_w")
CASES = [
    ("feedback", .07, 50, True, False),
    ("frozen-resistance", .07, 50, False, False),
    ("fine-thermal", .07, 25, True, False),
    ("regeneration", .2, 50, True, True),
]


def save_rows(path, rows):
    columns = list(rows[0])
    np.savetxt(path, [[r[c] for c in columns] for r in rows], delimiter=",", comments="",
               header=",".join(columns))


class LedgerSeries(SubsystemTimeSeries):
    def __init__(self, subsystem):
        for name, values in subsystem._history.items():
            setattr(self, name, np.real(np.asarray(values)))


class LossLedger(Subsystem):
    def __init__(self, drive):
        self.drive = drive
        self.state = SimpleNamespace(**dict.fromkeys(J_FIELDS, 0.))
        self.inp, self.out = None, SimpleNamespace()
        self.rows = []

    def powers(self, t):
        d = self.drive
        current = complex(d.machine.out.i_s_ab)
        resistance = float(d.machine.par.R_s)
        dc = float(d.converter.out.u_dc*d.converter.compute_internal_dc_current(d.converter.inp))
        ac = 1.5*float((d.machine.inp.u_s_ab*np.conj(current)).real)
        copper = 1.5*resistance*abs(current)**2
        speed = float(d.mechanics.state.w_M.real)
        friction = float(value(d.mechanics.B_L, speed))*speed**2
        load = float(value(d.mechanics.inp.tau_L, t))*speed
        return np.array([copper, dc-ac, dc, ac, load, friction])

    def rhs(self, t):
        p = self.powers(t)
        self.rows.append([t, float(self.drive.machine.par.R_s),
                          abs(complex(self.drive.machine.out.i_s_ab)),
                          p[2], p[3], p[0], p[1], p[4], p[5]])
        if len(self.rows) > 2_000_000:
            raise ValueError("actual solver RHS budget exceeded")
        return p.tolist()

    def set_outputs(self, t):
        pass

    def create_time_series(self, t):
        return "window_losses", LedgerSeries(self)

    def integrals(self):
        return np.array([float(getattr(self.state, n).real) for n in J_FIELDS])


class ReadbackView:
    """Legacy controller logging view; no six-node thermal evolution or loss estimate is used."""
    def __init__(self, owner):
        self.owner = owner

    def advance(self, ignored_legacy_heat):
        v = self.owner.held
        return np.array([v[0], 25., 25., v[1], 25., 25.])


class CoupledController:
    def __init__(self, drive, base, ledger, sink, ratio, feedback, regeneration):
        self.drive, self.base, self.ledger, self.sink = drive, base, ledger, sink
        self.ratio, self.feedback, self.regeneration = ratio, feedback, regeneration
        self.clock = ThermalWindowClock(sink, source_powers_w=[.04, .12],
                                        thermal_period_ns=ratio*50_000)
        self.held = np.array([25., 25., 25., 25., 0., 0.])
        self.last_thermal_tick = 0
        self.packets, self.states, self.rows = [], [sink.state], []
        self.initial_electrical = None
        base.thermal = ReadbackView(self)

    def get_enable(self):
        return self.base.get_enable()

    def reference(self, tick):
        magnitude = 0. if tick < 223 else .25 if tick < 2713 else .15
        if self.regeneration:
            magnitude = 0. if tick < 223 else -.2 if tick < 2713 else -.12
        return magnitude

    def capture(self, issued):
        tick, d = self.base.tick, self.drive
        integrals = self.ledger.integrals()
        packet = self.clock.sample(tick, integrals[:2])
        if packet is not None:
            self.packets.append(packet)
            self.states.append(self.sink.state)
            self.held = packet["outputs"].copy()
            self.last_thermal_tick = tick
        resistance = .3*(1+.00393*(self.held[0]-25)) if self.feedback else .3
        d.machine.par.R_s = resistance
        d.set_outputs(d.t0)
        par = d.machine.par
        magnetic = float(linear_magnetic_energy(
            d.machine.state.psi_s_dq, par.L_d, par.L_q, par.psi_f))
        kinetic = .5*d.mechanics.J*float(d.mechanics.state.w_M.real)**2
        if self.initial_electrical is None:
            self.initial_electrical = magnetic+kinetic
        balance = (integrals[2]-integrals[0]-integrals[1]-integrals[4]-integrals[5]
                   -magnetic-kinetic+self.initial_electrical)
        powers = self.ledger.powers(tick*DT)
        current = complex(d.machine.out.i_s_dq)
        row = dict(tick=tick, time_s=tick*DT, command_issued=int(issued),
                   last_thermal_tick=self.last_thermal_tick,
                   temperature_age_ticks=tick-self.last_thermal_tick,
                   id_a=float(current.real), iq_a=float(current.imag),
                   iq_reference_a=self.reference(tick),
                   speed_rad_s=float(d.mechanics.state.w_M.real),
                   held_left_c=float(self.held[0]), held_right_c=float(self.held[1]),
                   resistance_ohm=resistance, nominal_resistance_ohm=float(self.base.nominal.R_s),
                   **dict(zip(J_FIELDS, integrals.tolist(), strict=True)),
                   magnetic_j=magnetic, kinetic_j=kinetic, electrical_balance_j=balance,
                   instant_copper_w=float(powers[0]), instant_device_w=float(powers[1]),
                   instant_source_w=float(powers[2]), thermal_updates=len(self.packets))
        self.rows.append(row)

    def __call__(self, drive):
        self.capture(issued=True)
        self.base.config["iq_reference_a"] = self.reference(self.base.tick)
        return self.base(drive)

    def finish(self):
        assert self.base.tick == TICKS
        assert abs(self.drive.t0-TICKS*DT) <= 5e-12
        self.capture(issued=False)

    def post_process(self):
        return self.base.post_process()


def thermal_references(controller, rc, folder):
    public = np.load(BUNDLE / "train/public.npz")
    bundle = np.load(BUNDLE / "model/rom.npz")
    free = public["free"]
    mass = load_npz(BUNDLE / "train/mass.npz")
    stiffness = load_npz(BUNDLE / "train/stiffness.npz")
    contact = load_npz(BUNDLE / "train/contact-stiffness.npz")
    actual_k = stiffness+(.1/rc-1)*contact
    dt = controller.ratio*DT
    packets = controller.packets
    energies = np.array([p["energy_j"] for p in packets])
    factors = energies/dt/public["source_powers"]
    rom_states = np.array(controller.states)
    states = rom_states@bundle["basis"].T
    mf, kf = mass[free][:, free], actual_k[free][:, free]
    fom_step = kernel(mf, kf, public["forcing"][free], dt)
    truth = np.zeros_like(states)
    for i, mean in enumerate(factors):
        truth[i+1] = fom_step(truth[i], mean)
    full = np.zeros((len(states), len(public["points"])))
    full_truth = np.zeros_like(full)
    full[:, free], full_truth[:, free] = states, truth
    middle, derivative = (full[1:]+full[:-1])/2, np.diff(full, axis=0)/dt
    fixed = public["fixed"]
    sm = np.asarray(mass[fixed].sum(axis=0)).ravel()
    sk = np.asarray(actual_k[fixed].sum(axis=0)).ravel()
    sf = public["forcing"][fixed].sum(axis=0)
    left = -derivative@sm-middle@sk+factors@sf
    right = middle@public["observations"][5]
    interface = middle@public["observations"][4]*.1/rc
    left_j, right_j, interface_j = [np.r_[0., dt*np.cumsum(p)] for p in
                                    (left, right, interface)]
    input_j = np.vstack([np.zeros(2), np.cumsum(energies, axis=0)])
    energy = full@public["energy"].T
    balance = np.column_stack([
        energy.sum(axis=1)-input_j.sum(axis=1)+left_j+right_j,
        energy[:, 0]-input_j[:, 0]+left_j+interface_j,
        energy[:, 1]-input_j[:, 1]+right_j-interface_j])
    observed, expected = full@public["observations"].T, full_truth@public["observations"].T
    observed[:, :4] += 25
    expected[:, :4] += 25
    observed[:, 4] *= .1/rc
    expected[:, 4] *= .1/rc
    controls = controller.rows
    micro_energy = np.diff([[r["copper_j"], r["device_j"]] for r in controls], axis=0)
    micro_step = kernel(bundle["mass"],
                        bundle["bulk_stiffness"]+.1/rc*bundle["contact_stiffness"],
                        bundle["forcing"], DT)
    fine_states = np.zeros((TICKS+1, len(rom_states[0])))
    for i, e in enumerate(micro_energy):
        fine_states[i+1] = micro_step(fine_states[i], e/DT/public["source_powers"])
    fine_outputs = fine_states@bundle["observations"].T
    fine_outputs[:, :4] += 25
    fine_outputs[:, 4] *= .1/rc
    sampled_fine = fine_outputs[::controller.ratio]
    rows = []
    for i in range(len(states)):
        p = packets[i-1] if i else None
        rows.append(dict(
            tick=i*controller.ratio, time_s=i*dt,
            window_start_tick=(i-1)*controller.ratio if i else 0,
            control_count=controller.ratio if i else 0,
            energy_left_j=float(p["energy_j"][0]) if p else 0.,
            energy_right_j=float(p["energy_j"][1]) if p else 0.,
            mean_left_w=float(p["mean_power_w"][0]) if p else 0.,
            mean_right_w=float(p["mean_power_w"][1]) if p else 0.,
            factor_left=float(p["source_factors"][0]) if p else 0.,
            factor_right=float(p["source_factors"][1]) if p else 0.,
            left_c=float(observed[i, 0]), right_c=float(observed[i, 1]),
            interface_left_c=float(observed[i, 2]), interface_right_c=float(observed[i, 3]),
            interface_right_w=float(observed[i, 4]), right_out_w=float(observed[i, 5]),
            stored_left_j=float(energy[i, 0]), stored_right_j=float(energy[i, 1]),
            input_left_j=float(input_j[i, 0]), input_right_j=float(input_j[i, 1]),
            left_out_j=float(left_j[i]), right_out_j=float(right_j[i]),
            interface_right_j=float(interface_j[i]),
            global_balance_j=float(balance[i, 0]), left_balance_j=float(balance[i, 1]),
            right_balance_j=float(balance[i, 2]), fom_left_c=float(expected[i, 0]),
            fom_right_c=float(expected[i, 1]), fast_left_c=float(sampled_fine[i, 0]),
            fast_right_c=float(sampled_fine[i, 1])))
    save_rows(folder / "thermal.csv", rows)
    np.savez_compressed(folder / "thermal-fields.npz", points=public["points"],
                        triangles=public["triangles"], rom_temperature_c=full+25,
                        fom_temperature_c=full_truth+25, rom_states=rom_states,
                        fast_20khz_states=fine_states)
    last_sample = np.array([[controls[p["end_tick"]]["instant_copper_w"],
                             controls[p["end_tick"]]["instant_device_w"]] for p in packets])*dt
    fault_last_sample = float(np.max(abs(last_sample.sum(axis=0)-energies.sum(axis=0))))
    fault_missing_final = float(np.max(abs(energies[-1])))
    target = np.array([controls[-1]["copper_j"], controls[-1]["device_j"]])
    micro_sum = micro_energy.reshape(len(packets), controller.ratio, 2).sum(axis=1)
    metrics = dict(
        mapped_energy_error_j=float(np.max(abs(energies.sum(axis=0)-target))),
        window_sum_error_j=float(np.max(abs(micro_sum-energies))),
        thermal_balance_j=float(np.max(abs(balance))),
        fom_rms_relative=rms(states-truth, truth, mf),
        fom_peak_error_k=float(np.max(abs(states-truth))),
        fom_mean_peak_error_k=float(np.max(abs(observed[:, :2]-expected[:, :2]))),
        fine_20khz_mean_peak_error_k=float(
            np.max(abs(observed[:, :2]-sampled_fine[:, :2]))),
        max_source_factor=float(max(np.max(factors),
                                    np.max(micro_energy/DT/public["source_powers"]))),
        last_sample_fault_j=fault_last_sample, missing_final_fault_j=fault_missing_final,
        final_left_c=float(observed[-1, 0]), final_right_c=float(observed[-1, 1]))
    metrics["passed"] = bool(
        metrics["mapped_energy_error_j"] <= 1e-11 and metrics["window_sum_error_j"] <= 1e-12
        and metrics["thermal_balance_j"] <= 1e-8 and metrics["fom_rms_relative"] <= .01
        and metrics["fom_peak_error_k"] <= .01 and metrics["fom_mean_peak_error_k"] <= .005
        and metrics["fine_20khz_mean_peak_error_k"] <= .001
        and metrics["max_source_factor"] <= 2
        and fault_last_sample > 1e-9 and fault_missing_final > 1e-9)
    return metrics


def refresh_loss_direction(drive):
    """Use upstream smooth sign with current-state refresh, without moving gate events."""
    if drive.machine.par.G_c != 0:
        raise ValueError("direction refresh requires the declared Gc=0 current-state model")
    converter = drive.converter
    converter.sign = lambda i:2/np.pi*np.arctan(i/.02)
    upstream_gates, upstream_outputs = converter.set_gate_signals, drive.set_outputs
    cached = {}

    def remember_gates(gates, blanking):
        cached["gates"] = np.array(gates, copy=True)
        cached["blanking"] = np.array(blanking, copy=True)
        upstream_gates(gates, blanking)

    def continuous_outputs(t):
        upstream_outputs(t)
        if cached:
            upstream_gates(cached["gates"], cached["blanking"])
            upstream_outputs(t)

    converter.set_gate_signals = remember_gates
    drive.set_outputs = continuous_outputs


def execute(name, rc, ratio, feedback, regeneration):
    started = time.perf_counter()
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    config = dict(duration_s=TICKS*DT, period_s=DT, step_time_s=0., bus_v=48.,
                  pwm=False, delay=False, device_drop_v=.1, bandwidth_per_s=2000.,
                  current_limit_a=.5, thermal_feedback=False, load_nm=-.1 if regeneration else .02)
    drive, base = make_drive(config)
    refresh_loss_direction(drive)
    ledger = LossLedger(drive)
    drive.subsystems.append(ledger)
    drive._outgoing[ledger] = []
    ledger.init_state_history()
    sink = AffineThermalROM.from_npz(BUNDLE / "model/rom.npz", rc=rc, dt_s=ratio*DT)
    controller = CoupledController(drive, base, ledger, sink, ratio, feedback, regeneration)
    simulation = model.Simulation(drive, controller, show_progress=False,
                                  cfg=SolverCfg(method="RK45", rtol=1e-8,
                                                atol=1e-11, max_step=25e-6))
    try:
        result = simulation.simulate(t_stop=(TICKS-.25)*DT, N_eval=2)
    except Exception:
        if controller.rows:
            save_rows(folder / "failed-control.csv", controller.rows)
        with gzip.open(folder / "failed-rhs.csv.gz", "wt") as output:
            np.savetxt(output, np.array(ledger.rows), delimiter=",", comments="",
                       header=",".join(RHS_COLUMNS))
        failure = dict(control_tick=base.tick, time_s=drive.t0,
                       integrals_j=ledger.integrals().tolist(),
                       powers_w=ledger.powers(drive.t0).tolist(),
                       minimum_rhs_heat_w=float(np.min(np.array(ledger.rows)[:, [5, 6]])))
        (folder / "failure.json").write_text(json.dumps(failure, indent=2))
        print("p7-multirate-failure: "+json.dumps(failure), flush=True)
        raise
    assert result.success
    controller.finish()
    assert len(base.rows) == TICKS and len(controller.rows) == TICKS+1
    assert len(controller.packets) == TICKS//ratio
    assert all(p["control_count"] == ratio and p["end_tick"] % ratio == 0
               for p in controller.packets)
    assert all(0 <= r["temperature_age_ticks"] < ratio for r in controller.rows)
    save_rows(folder / "control.csv", controller.rows)
    np.savetxt(folder / "native-controller.csv", base.rows, delimiter=",", comments="",
               header=",".join(CONTROL_COLUMNS))
    rhs = np.array(ledger.rows)
    with gzip.open(folder / "rhs.csv.gz", "wt") as output:
        np.savetxt(output, rhs, delimiter=",", comments="", header=",".join(RHS_COLUMNS))
    audit = thermal_references(controller, rc, folder)
    resistance_error = max(abs(
        r["resistance_ohm"]-(.3*(1+.00393*(r["held_left_c"]-25)) if feedback else .3))
        for r in controller.rows)
    power_error = max(float(np.max(abs(rhs[:, 5]-1.5*rhs[:, 1]*rhs[:, 2]**2))),
                      float(np.max(abs(rhs[:, 6]-(rhs[:, 3]-rhs[:, 4])))))
    electrical = max(abs(r["electrical_balance_j"]) for r in controller.rows)
    metrics = dict(
        id=name, rc=rc, ratio=ratio, thermal_hz=20_000/ratio, feedback=feedback,
        regeneration=regeneration, control_rows=len(controller.rows),
        thermal_rows=len(controller.packets)+1, control_commands=len(base.rows),
        rhs_rows=len(rhs), resistance_error_ohm=float(resistance_error),
        resistance_growth_ohm=float(max(r["resistance_ohm"] for r in controller.rows)-.3),
        power_audit_error_w=power_error, minimum_heat_w=float(np.min(rhs[:, [5, 6]])),
        electrical_balance_j=float(electrical),
        minimum_source_w=float(np.min(rhs[:, 3])), nominal_resistance_ohm=float(base.nominal.R_s),
        elapsed_s=time.perf_counter()-started, **{k:v for k, v in audit.items() if k != "passed"})
    metrics["passed"] = bool(
        audit["passed"] and resistance_error <= 1e-12 and power_error <= 1e-10
        and electrical <= 1e-7 and metrics["minimum_heat_w"] >= -1e-9
        and metrics["nominal_resistance_ohm"] == .3
        and (not feedback or metrics["resistance_growth_ohm"] >= 1e-7)
        and (not regeneration or metrics["minimum_source_w"] < -.01))
    (folder / "input.json").write_text(json.dumps(
        dict(config=config, rc=rc, ratio=ratio, feedback=feedback,
             current_sign_regularization_a=.02, current_sign_refresh="continuous outputs",
             regeneration=regeneration, initial_c=25.), indent=2))
    (folder / "result.json").write_text(json.dumps(metrics, indent=2))
    print("p7-multirate-case: "+json.dumps(metrics), flush=True)
    return metrics, controller.rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = json.loads((BUNDLE / "model/freeze.json").read_text())
    assert frozen["model_sha256"] == hashes(BUNDLE / "model", exclude=("freeze.json",))
    assert frozen["training_sha256"] == hashes(BUNDLE / "train")
    cases, controls = [], {}
    for specification in CASES:
        metrics, rows = execute(*specification)
        cases.append(metrics)
        controls[specification[0]] = rows
    main_rows, frozen_rows, fine_rows = [controls[n] for n in
                                       ("feedback", "frozen-resistance", "fine-thermal")]
    copper_difference = abs(main_rows[-1]["copper_j"]-frozen_rows[-1]["copper_j"])
    current_difference = max(abs(a["iq_a"]-b["iq_a"])
                             for a, b in zip(main_rows, frozen_rows, strict=True))
    fine_current = max(abs(a["iq_a"]-b["iq_a"])
                       for a, b in zip(main_rows, fine_rows, strict=True))
    a = np.genfromtxt(OUT / "feedback/thermal.csv", delimiter=",", names=True)
    b = np.genfromtxt(OUT / "fine-thermal/thermal.csv", delimiter=",", names=True)[::2]
    fine_temperature = max(float(np.max(abs(a[n]-b[n]))) for n in ("left_c", "right_c"))
    checks = dict(all_cases=all(c["passed"] for c in cases),
                  causal_feedback=copper_difference >= 1e-10 and current_difference >= 1e-9,
                  macro_refinement=fine_current <= .001 and fine_temperature <= .001,
                  frozen_training=frozen["training_sha256"] == hashes(BUNDLE / "train"),
                  frozen_model=frozen["model_sha256"] == hashes(
                      BUNDLE / "model", exclude=("freeze.json",)))
    report = dict(
        passed=bool(all(checks.values())), checks=checks, cases=cases,
        feedback_copper_difference_j=float(copper_difference),
        feedback_current_difference_a=float(current_difference),
        macro_refinement_current_a=float(fine_current),
        macro_refinement_mean_k=float(fine_temperature),
        source_kind="synthetic", evidence_level="model_simulated",
        scope="actual average-inverter motulator + equivalent synthetic thermal slab",
        commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        motulator_commit="2ffbf1ae52d5fadcdffd85d10c80dd15fd2e39fa",
        versions={p:importlib.metadata.version(p) for p in
                  ("motulator", "numpy", "scipy", "pymor", "scikit-fem")},
        host=dict(platform=platform.platform(), cpu_info=Path("/proc/cpuinfo").read_text(),
                  peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
    (OUT / "validation.json").write_text(json.dumps(report, indent=2))
    print("p7-multirate-summary: "+json.dumps({k:v for k, v in report.items()
                                            if k not in {"cases", "host"}}), flush=True)
    assert report["passed"], checks


if __name__ == "__main__":
    main()
