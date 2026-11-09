"""Actual FOC/copper/thermal/resistance co-simulation and independent references."""
import csv
import json
import math
from functools import partial
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import p7_cogging_model as cogging
from p7_cogging_simulation import LOAD, OFFSET, TS, derivative
from p7_stator_fast_rom import OUT as ROM
from p7_stator_fast_rom import verified_model
from p7_winding_heat import ROOT, digest
from scipy.integrate import solve_ivp
from scipy.sparse import diags
from scipy.sparse.linalg import factorized

from oeal.current_control import CurrentPIParameters, CurrentPIState, current_control_step
from oeal.foc import average_svpwm
from oeal.stator_feedback import CopperResistanceLaw, StatorCopperFeedback
from oeal.transforms import inverse_park

OUT = ROOT / "outputs/p7-temperature-feedback"
MOTOR = ROOT / "outputs/p7-cogging-report/coenergy-model.json"
CONTRACT = ROOT / "docs/p7-temperature-feedback-contract.md"
CONTROL_COLUMNS = ("time_s", "id_a", "iq_a", "theta_rad", "omega_rad_s", "source_j",
                   "copper_j", "friction_j", "load_j", "magnetic_j", "kinetic_j",
                   "drive_balance_j", "held_r_ohm")


class FullThermalFeedback:
    """Independent FE trajectory: its own fields, copper history, and resistance."""

    def __init__(self, fom, h, ambient, drive_dt, ticks, law):
        self.fom, self.ambient, self.law = fom, ambient, law
        self.dt, self.ticks = drive_dt*ticks, ticks
        self.solve = factorized((diags(fom["mass"])+self.dt*(
            fom["bulk"]+h*fom["convection"])).tocsc())
        self.observations = fom["observations"].copy()
        self.observations[3] *= h
        self.state = np.zeros(len(fom["mass"]))
        self.outputs = np.array([ambient, ambient, 0., 0.])
        self.resistance_ohm = law.resistance(ambient)
        self.copper_j = self.boundary_j = 0.
        self.windows = 0

    @property
    def balance_j(self):
        return self.copper_j-self.boundary_j-self.outputs[2]

    def advance_window(self, end_tick, energy):
        if end_tick != (self.windows+1)*self.ticks:
            raise ValueError("FE clock mismatch")
        power = (energy-self.copper_j)/self.dt
        if not np.isfinite(power) or not 0 <= power <= 2*self.fom["p0"]:
            raise ValueError("FE source outside fixed power domain")
        candidate = self.solve(self.fom["mass"]*self.state+self.dt*self.fom["forcing"]*power)
        outputs = self.observations@candidate
        outputs[:2] += self.ambient
        resistance = self.law.resistance(float(outputs[0]))
        self.state, self.outputs, self.resistance_ohm = candidate, outputs, resistance
        self.copper_j = energy
        self.boundary_j += self.dt*outputs[3]
        self.windows += 1


def load_motor(resistance):
    fields_path = MOTOR.with_name("fields.json")
    fields = json.loads(fields_path.read_text(encoding="utf-8"))
    if (not fields["evidence_passed"] or not fields["model_supported"]
            or digest(MOTOR) != fields["model_sha256"]):
        raise ValueError("frozen electromagnetic model integrity/support failure")
    parameters = json.loads(MOTOR.read_text(encoding="utf-8"))
    return cogging.CoggingMotor(
        cogging.FourierSeries(parameters["psi_a"], parameters["psi_b"]),
        cogging.FourierSeries(parameters["cog_a"], parameters["cog_b"]),
        parameters["inductance_h"], resistance=resistance)


def run(fom, basis, h, ambient, direction, *, full=False, drive_dt=5e-6,
        window_s=.0025, replay=False):
    control_steps, window_ticks = round(TS/drive_dt), round(window_s/drive_dt)
    if (not math.isclose(control_steps*drive_dt, TS, abs_tol=1e-14)
            or not math.isclose(window_ticks*drive_dt, window_s, abs_tol=1e-14)
            or window_ticks % control_steps or round(.05/drive_dt) % window_ticks):
        raise ValueError("integer aligned electrical/control/thermal clocks required")
    law = CopperResistanceLaw()
    if full:
        thermal = FullThermalFeedback(fom, h, ambient, drive_dt, window_ticks, law)
    else:
        thermal = StatorCopperFeedback.from_npz(
            ROM / "inference.npz", h_w_m2_k=h, drive_dt_s=drive_dt,
            ticks_per_window=window_ticks, ambient_c=ambient, law=law)
    motor = load_motor(thermal.resistance_ohm)
    matrix = motor.inductance
    controller = CurrentPIParameters(matrix[0, 0]*1000, law.reference_ohm*1000,
                                     matrix[1, 1]*1000, law.reference_ohm*1000,
                                     48/math.sqrt(3), 1., 1000.)
    pi = CurrentPIState()
    state = np.zeros(8)
    state[2:4] = .1, 40*direction
    reference = state.copy()
    initial_energy = motor.stored(state[2], state[:2])+.5*motor.inertia*state[3]**2
    initial_r = thermal.resistance_ohm
    rows, fields = [], [np.zeros(len(fom["mass"]))]
    heat_outputs = [thermal.outputs]
    thermal_rows = [np.array([0., 0., 0., 0., 0., initial_r, initial_r])]
    max_domain = max_voltage = max_drive_balance = max_joint_balance = max_heat_balance = 0.
    max_transfer = 0.
    replay_error = np.zeros(3)
    load = direction*LOAD

    def control_row(at):
        stored = motor.stored(state[2], state[:2])
        kinetic = .5*motor.inertia*state[3]**2
        balance = state[4]-state[5]-state[6]-state[7]-stored-kinetic+initial_energy
        return np.r_[at, state[:4], state[4:8], stored, kinetic, balance, motor.resistance]

    for control_tick in range(1000):
        start_tick = control_tick*control_steps
        start = start_tick*drive_dt
        motor.resistance = thermal.resistance_ohm
        rows.append(control_row(start))
        angle, omega = state[2:4]
        flux = motor.flux(angle, state[:2])
        feedforward = omega*(motor.psi.derivative(angle)+4*cogging.JROT@flux)
        command = current_control_step(
            controller, pi, reference_d_a=0., reference_q_a=direction*.5,
            measured_d_a=float(state[0]), measured_q_a=float(state[1]), period_s=TS,
            feedforward_d_v=float(feedforward[0]), feedforward_q_v=float(feedforward[1]))
        pi = command.next_state
        stationary = inverse_park(command.vd_v, command.vq_v, OFFSET+4*angle)
        alpha, beta, _ = average_svpwm(*stationary, 48.)
        stationary = np.array([alpha, beta])
        max_voltage = max(max_voltage, float(np.linalg.norm(stationary)))
        for substep in range(control_steps):
            at = (start_tick+substep)*drive_dt
            k1 = derivative(motor, stationary, load, at, state)
            k2 = derivative(motor, stationary, load, at+drive_dt/2, state+drive_dt*k1/2)
            k3 = derivative(motor, stationary, load, at+drive_dt/2, state+drive_dt*k2/2)
            k4 = derivative(motor, stationary, load, at+drive_dt, state+drive_dt*k3)
            state = state+drive_dt*(k1+2*k2+2*k3+k4)/6
            motor.current(state[:2])
            max_domain = max(max_domain, float(sum(abs(state[:2]))))
        if replay:
            solved = solve_ivp(partial(derivative, motor, stationary, load),
                               (start, start+TS), reference, method="DOP853",
                               rtol=1e-10, atol=1e-12)
            if not solved.success:
                raise ValueError("independent electrical replay failed")
            reference = solved.y[:, -1]
            replay_error = np.maximum(replay_error, [max(abs(reference[:2]-state[:2])),
                                                    abs(reference[2]-state[2]),
                                                    abs(reference[3]-state[3])])
        end_tick = (control_tick+1)*control_steps
        drive_balance = float(control_row(end_tick*drive_dt)[-2])
        max_drive_balance = max(max_drive_balance, abs(drive_balance))
        if end_tick % window_ticks == 0:
            applied_r = motor.resistance
            thermal.advance_window(end_tick, float(state[5]))
            max_transfer = max(max_transfer, abs(thermal.copper_j-state[5]))
            joint = drive_balance+state[5]-thermal.boundary_j-thermal.outputs[2]
            max_joint_balance = max(max_joint_balance, abs(float(joint)))
            max_heat_balance = max(max_heat_balance, abs(float(thermal.balance_j)))
            fields.append(thermal.state.copy() if full else basis@thermal.state)
            heat_outputs.append(thermal.outputs.copy())
            thermal_rows.append(np.array([end_tick*drive_dt, thermal.copper_j,
                                          thermal.boundary_j, thermal.balance_j, joint,
                                          applied_r, thermal.resistance_ohm]))
    rows.append(control_row(.05))
    metrics = dict(windows=thermal.windows, control_endpoints=len(rows),
                   initial_r_ohm=initial_r, final_r_ohm=thermal.resistance_ohm,
                   resistance_change_ohm=thermal.resistance_ohm-initial_r,
                   max_drive_balance_j=max_drive_balance, max_joint_balance_j=max_joint_balance,
                   max_thermal_balance_j=max_heat_balance, max_transfer_difference_j=max_transfer,
                   max_l1_current_a=max_domain, max_voltage_v=max_voltage,
                   replay_current_a=float(replay_error[0]), replay_angle_rad=float(replay_error[1]),
                   replay_speed_rad_s=float(replay_error[2]), replay_performed=replay,
                   drive_dt_s=drive_dt, window_s=window_s)
    metrics["passed"] = bool(thermal.windows == round(.05/window_s) and len(rows) == 1001
                              and max_joint_balance <= 1e-5 and max_drive_balance <= 1e-5
                              and max_heat_balance <= 1e-8 and max_transfer <= 1e-12
                              and thermal.resistance_ohm-initial_r > 1e-10
                              and max_domain <= 2 and max_voltage <= 48/math.sqrt(3)+1e-12
                              and replay_error[0] <= 1e-4 and replay_error[1] <= 1e-5
                              and replay_error[2] <= 1e-3)
    return metrics, dict(control=np.array(rows), fields=np.array(fields),
                         outputs=np.array(heat_outputs), thermal=np.array(thermal_rows))


def save_case(name, arrays):
    np.savez_compressed(OUT / (name+".npz"), **arrays)
    with (OUT / (name+"-control.csv")).open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(CONTROL_COLUMNS)
        writer.writerows(arrays["control"])
    with (OUT / (name+"-thermal.csv")).open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(("time_s", "copper_j", "boundary_j", "thermal_balance_j",
                         "joint_balance_j", "applied_r_ohm", "next_r_ohm"))
        writer.writerows(arrays["thermal"])


def compare(left, right, *, field_budget, mean_budget, relative_budget=None,
            current_budget=1e-6, angle_budget=1e-7, speed_budget=1e-5):
    field = float(np.max(abs(left["fields"]-right["fields"])))
    peak = float(np.max(abs(right["fields"])))
    relative = field/peak if peak else float("inf")
    mean = float(np.max(abs(left["outputs"][:, :2]-right["outputs"][:, :2])))
    difference = np.max(abs(left["control"][:, 1:5]-right["control"][:, 1:5]), axis=0)
    return dict(max_field_difference_k=field, relative_field_difference=relative,
                max_mean_difference_k=mean, max_current_difference_a=float(max(difference[:2])),
                max_angle_difference_rad=float(difference[2]),
                max_speed_difference_rad_s=float(difference[3]),
                passed=bool(field <= field_budget and mean <= mean_budget
                            and max(difference[:2]) <= current_budget
                            and difference[2] <= angle_budget and difference[3] <= speed_budget
                            and (relative_budget is None or relative <= relative_budget)))


def main():
    frozen, fom, basis, _ = verified_model()
    upstream = json.loads((ROM / "summary.json").read_text(encoding="utf-8"))
    if not upstream["passed"] or upstream["frozen_sha256"] != digest(ROM / "frozen.json"):
        raise ValueError("short-time ROM validation missing or stale")
    frozen_sha, motor_sha = digest(ROM / "frozen.json"), digest(MOTOR)
    OUT.mkdir(parents=True, exist_ok=True)
    results, selected = [], None
    for ambient in (25., 75.):
        for direction, h, label in ((1., 12., "forward"), (-1., 40., "reverse")):
            name = f"{label}-{ambient:g}C"
            replay = ambient == 75. and direction == 1.
            rom, ra = run(fom, basis, h, ambient, direction, replay=replay)
            full, fa = run(fom, basis, h, ambient, direction, full=True)
            save_case(name+"-rom", ra)
            save_case(name+"-fe", fa)
            comparison = compare(ra, fa, field_budget=1e-5, mean_budget=1e-5, relative_budget=.05)
            case = dict(name=name, ambient_c=ambient, h=h, rom=rom, full=full,
                        comparison=comparison,
                        passed=rom["passed"] and full["passed"] and comparison["passed"])
            results.append(case)
            print("feedback-case:", json.dumps(case), flush=True)
            if replay:
                selected = ra
    fine, fine_arrays = run(fom, basis, 12., 75., 1., drive_dt=2.5e-6, window_s=.00125)
    save_case("forward-75C-fine", fine_arrays)
    common = {key: values[::2] if key in ("fields", "outputs", "thermal") else values
              for key, values in fine_arrays.items()}
    refinement = compare(selected, common, field_budget=1e-6, mean_budget=1e-7,
                         current_budget=1e-4, angle_budget=1e-5, speed_budget=1e-3)
    if digest(ROM / "frozen.json") != frozen_sha or digest(MOTOR) != motor_sha:
        raise ValueError("frozen model changed during coupled validation")
    paths = (Path(__file__), CONTRACT, ROOT / "src/oeal/stator_feedback.py",
             ROOT / "benchmarks/p7_cogging_model.py", ROOT / "benchmarks/p7_cogging_simulation.py",
             ROOT / "src/oeal/current_control.py", ROOT / "src/oeal/foc.py",
             ROOT / "src/oeal/transforms.py", MOTOR.with_name("fields.json"))
    summary = dict(passed=bool(all(c["passed"] for c in results)
                               and fine["passed"] and refinement["passed"]),
                   cases=results, fine=fine, refinement=refinement,
                   frozen_sha256=frozen_sha, model_sha256=motor_sha,
                   dimensions=frozen["dimensions"],
                   source_sha256={p.relative_to(ROOT).as_posix(): digest(p) for p in paths},
                   resistance_law=dict(reference_ohm=.3, reference_c=25., coefficient_per_k=.004,
                                       temperature_domain_c=[0., 125.], kind="synthetic"),
                   evidence_kind="model_simulated")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    figure(results)
    manifest = {p.name: digest(p) for p in OUT.iterdir()
                if p.is_file() and p.name != "manifest.json"}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("temperature-feedback-summary:", json.dumps(summary), flush=True)
    if not summary["passed"]:
        raise SystemExit(1)


def figure(results):
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for result in results:
        name = result["name"]
        with np.load(OUT / (name+"-rom.npz"), allow_pickle=False) as data:
            times = data["thermal"][:, 0]*1000
            axes[0].plot(times, (data["outputs"][:, 0]-result["ambient_c"])*1e6, label=name)
            axes[1].plot(times, (data["thermal"][:, 6]-data["thermal"][0, 6])*1e9, label=name)
    axes[0].set(xlabel="Time (ms)", ylabel="Winding mean rise (µK)", title="Coupled self-heating")
    axes[1].set(xlabel="Time (ms)", ylabel="Resistance increase (nΩ)",
                title="R used from the next window")
    for axis in axes:
        axis.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "feedback.png", dpi=160)
    fig.savefig(OUT / "feedback.svg")
    plt.close(fig)


if __name__ == "__main__":
    main()
