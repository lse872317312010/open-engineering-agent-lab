"""Two-second actual-drive duty cycle, braking/cooling and warm same-object continuation."""
import gc
import gzip
import json
import platform
import resource
import subprocess
import time
from pathlib import Path

import numpy as np
import p7_multirate_drive as base
from p7_cycle_reference import CHUNK_TICKS, SETTLED_TICK, TOTAL_TICKS, cycle_command
from p7_rom import hashes

from oeal.thermal_rom import AffineThermalROM

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-drive-cycle"
RHS_COLUMNS = (*base.RHS_COLUMNS, "control_tick", "held_load_nm", "held_brake_nms", "speed_rad_s")
CASES = [
    ("cycle-feedback", 50, True, ()),
    ("cycle-frozen", 50, False, ()),
    ("cycle-fine", 25, True, ()),
    ("cycle-chunked", 50, True, CHUNK_TICKS),
]


class CycleLedger(base.LossLedger):
    def rhs(self, t):
        result = super().rhs(t)
        self.rows[-1].extend([
            self.controller.active_tick, self.controller.held_load,
            self.drive.mechanics.B_L, float(self.drive.mechanics.state.w_M.real)])
        return result


class CycleController(base.CoupledController):
    def __init__(self, drive, controller, ledger, sink, ratio, feedback):
        super().__init__(drive, controller, ledger, sink, ratio, feedback, False)
        self.active_tick, self.held_load = 0, 0.
        ledger.controller = self
        drive.mechanics.set_external_load_torque(lambda t:self.held_load)

    def reference(self, tick):
        return cycle_command(tick)["iq_a"]

    def capture(self, issued):
        tick = self.base.tick
        command = cycle_command(tick)
        self.active_tick, self.held_load = tick, command["load_nm"]
        self.drive.mechanics.B_L = command["brake_nms"]
        super().capture(issued)
        self.rows[-1].update(phase_code=command["phase"], held_load_nm=self.held_load,
                             held_brake_nms=command["brake_nms"],
                             control_enabled=int(self.get_enable()))

    def finish(self):
        assert self.base.tick == TOTAL_TICKS
        assert abs(self.drive.t0-TOTAL_TICKS*base.DT) <= 5e-12
        self.capture(issued=False)

    def checkpoint(self):
        current = complex(self.drive.machine.out.i_s_dq)
        return dict(tick=self.base.tick, next_clock_tick=self.clock.next_tick,
                    last_thermal_tick=self.last_thermal_tick,
                    pending_control_intervals=self.base.tick-self.last_thermal_tick,
                    pi_d_v=self.base.pi.integral_d_v, pi_q_v=self.base.pi.integral_q_v,
                    thermal_state=self.sink.state.tolist(),
                    id_a=float(current.real), iq_a=float(current.imag),
                    speed_rad_s=float(self.drive.mechanics.state.w_M.real),
                    integrals_j=self.ledger.integrals().tolist())


def execute(name, ratio, feedback, chunks):
    started = time.perf_counter()
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    config = dict(duration_s=TOTAL_TICKS*base.DT, period_s=base.DT, step_time_s=0.,
                  bus_v=48., pwm=False, delay=False, device_drop_v=.1, bandwidth_per_s=2000.,
                  current_limit_a=.5, thermal_feedback=False, load_nm=0.)
    drive, controller = base.make_drive(config)
    base.refresh_loss_direction(drive)
    ledger = CycleLedger(drive)
    drive.subsystems.append(ledger)
    drive._outgoing[ledger] = []
    ledger.init_state_history()
    sink = AffineThermalROM.from_npz(base.BUNDLE / "model/rom.npz", rc=.07,
                                     dt_s=ratio*base.DT)
    coupled = CycleController(drive, controller, ledger, sink, ratio, feedback)
    simulation = base.model.Simulation(
        drive, coupled, show_progress=False,
        cfg=base.SolverCfg(method="RK45", rtol=1e-8, atol=1e-11, max_step=25e-6))
    checkpoints = []
    try:
        for boundary in (*chunks, TOTAL_TICKS):
            result = simulation.simulate(t_stop=(boundary-.25)*base.DT, N_eval=2)
            assert result.success and controller.tick == boundary
            assert coupled.clock.next_tick == boundary
            assert abs(drive.t0-boundary*base.DT) <= 5e-12
            if boundary < TOTAL_TICKS:
                checkpoints.append(coupled.checkpoint())
        coupled.finish()
    except Exception:
        if coupled.rows:
            base.save_rows(folder / "failed-control.csv", coupled.rows)
        with gzip.open(folder / "failed-rhs.csv.gz", "wt") as stream:
            np.savetxt(stream, np.array(ledger.rows), delimiter=",", comments="",
                       header=",".join(RHS_COLUMNS))
        failure = dict(tick=controller.tick, time_s=drive.t0,
                       cumulative_j=ledger.integrals().tolist())
        (folder / "failure.json").write_text(json.dumps(failure, indent=2))
        print("p7-cycle-failure: "+json.dumps(failure), flush=True)
        raise
    assert len(controller.rows) == TOTAL_TICKS and len(coupled.rows) == TOTAL_TICKS+1
    assert len(coupled.packets) == TOTAL_TICKS//ratio
    assert all(p["control_count"] == ratio and p["end_tick"] % ratio == 0
               for p in coupled.packets)
    assert all(0 <= r["temperature_age_ticks"] < ratio and r["control_enabled"] == 1
               for r in coupled.rows)
    base.save_rows(folder / "control.csv", coupled.rows)
    np.savetxt(folder / "native-controller.csv", controller.rows, delimiter=",", comments="",
               header=",".join(base.CONTROL_COLUMNS))
    rhs = np.array(ledger.rows)
    with gzip.open(folder / "rhs.csv.gz", "wt") as stream:
        np.savetxt(stream, rhs, delimiter=",", comments="", header=",".join(RHS_COLUMNS))
    audit = base.thermal_references(coupled, .07, folder)
    thermal = np.genfromtxt(folder / "thermal.csv", delimiter=",", names=True)
    settled = coupled.rows[SETTLED_TICK]
    final = coupled.rows[-1]
    tail_heat = final["copper_j"]+final["device_j"]-settled["copper_j"]-settled["device_j"]
    storage = thermal["stored_left_j"]+thermal["stored_right_j"]
    cooling_ratio = float(storage[-1]/storage[SETTLED_TICK//ratio])
    heated = [p for p in coupled.packets if sum(p["energy_j"]) > 1e-6]
    assert heated
    last_heated_fault = float(max(heated[-1]["energy_j"]))
    reset_fault = float(max(abs(thermal["left_c"][SETTLED_TICK//ratio]-25),
                            abs(thermal["right_c"][SETTLED_TICK//ratio]-25)))
    zero_window_change = max(abs(thermal[n][-1]-thermal[n][-2])
                             for n in ("left_c", "right_c"))
    lookup = [cycle_command(k) for k in range(TOTAL_TICKS+1)]
    phase_tick = rhs[:, 9].astype(int)
    expected_load = np.array([c["load_nm"] for c in lookup])[phase_tick]
    expected_brake = np.array([c["brake_nms"] for c in lookup])[phase_tick]
    phase_error = max(float(np.max(abs(rhs[:, 10]-expected_load))),
                      float(np.max(abs(rhs[:, 11]-expected_brake))))
    mechanical_error = max(float(np.max(abs(rhs[:, 7]-rhs[:, 10]*rhs[:, 12]))),
                           float(np.max(abs(rhs[:, 8]-rhs[:, 11]*rhs[:, 12]**2))))
    resistance_error = max(abs(
        r["resistance_ohm"]-(.3*(1+.00393*(r["held_left_c"]-25)) if feedback else .3))
        for r in coupled.rows)
    power_error = max(float(np.max(abs(rhs[:, 5]-1.5*rhs[:, 1]*rhs[:, 2]**2))),
                      float(np.max(abs(rhs[:, 6]-(rhs[:, 3]-rhs[:, 4])))))
    metrics = dict(
        id=name, ratio=ratio, thermal_hz=20_000/ratio, feedback=feedback,
        control_rows=len(coupled.rows), control_commands=len(controller.rows),
        thermal_rows=len(coupled.packets)+1, rhs_rows=len(rhs), checkpoints=checkpoints,
        tail_heat_j=float(tail_heat), cooling_storage_ratio=cooling_ratio,
        settled_storage_j=float(storage[SETTLED_TICK//ratio]), final_storage_j=float(storage[-1]),
        final_speed_rad_s=final["speed_rad_s"], phase_hold_error=float(phase_error),
        mechanical_power_error_w=mechanical_error, resistance_error_ohm=float(resistance_error),
        resistance_growth_ohm=float(max(r["resistance_ohm"] for r in coupled.rows)-.3),
        electrical_balance_j=float(max(abs(r["electrical_balance_j"]) for r in coupled.rows)),
        power_audit_error_w=power_error, minimum_heat_w=float(np.min(rhs[:, [5, 6]])),
        heated_window_drop_fault_j=last_heated_fault, reset_temperature_fault_k=reset_fault,
        zero_heat_final_step_change_k=float(zero_window_change),
        dropped_final_count_rejected=(len(coupled.packets)-1 != TOTAL_TICKS//ratio),
        elapsed_s=time.perf_counter()-started,
        **{k:v for k, v in audit.items() if k != "passed"})
    # Short-run final-heat fault predicates are inapplicable after a legitimate zero-heat tail.
    # Preserve all physics thresholds and test final closure plus a genuinely heated window.
    metrics["passed"] = bool(
        metrics["mapped_energy_error_j"] <= 1e-11 and metrics["window_sum_error_j"] <= 1e-12
        and metrics["thermal_balance_j"] <= 1e-8 and metrics["fom_rms_relative"] <= .01
        and metrics["fom_peak_error_k"] <= .01 and metrics["fom_mean_peak_error_k"] <= .005
        and metrics["fine_20khz_mean_peak_error_k"] <= .001 and metrics["max_source_factor"] <= 2
        and metrics["electrical_balance_j"] <= 1e-7 and power_error <= 1e-10
        and mechanical_error <= 1e-10 and phase_error == 0 and resistance_error <= 1e-12
        and metrics["minimum_heat_w"] >= -1e-9 and tail_heat <= 1e-8
        and metrics["settled_storage_j"] > 1e-8 and cooling_ratio <= .99
        and abs(final["speed_rad_s"]) <= .001
        and (not feedback or metrics["resistance_growth_ohm"] >= 1e-7)
        and metrics["dropped_final_count_rejected"] and zero_window_change > 0
        and last_heated_fault > 1e-9 and reset_fault > 1e-6)
    (folder / "input.json").write_text(json.dumps(
        dict(config=config, ratio=ratio, rc=.07, feedback=feedback, chunks=list(chunks),
             stage_change_ticks=[223, 8003, 16000], settled_tick=SETTLED_TICK,
             current_sign_regularization_a=.02, control_always_enabled=True), indent=2))
    (folder / "result.json").write_text(json.dumps(metrics, indent=2))
    print("p7-cycle-case: "+json.dumps(metrics), flush=True)
    return metrics


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    freeze = json.loads((base.BUNDLE / "model/freeze.json").read_text())
    assert freeze["training_sha256"] == hashes(base.BUNDLE / "train")
    assert freeze["model_sha256"] == hashes(base.BUNDLE / "model", exclude=("freeze.json",))
    cases = []
    for spec in CASES:
        cases.append(execute(*spec))
        gc.collect()
    controls = {c["id"]:np.genfromtxt(OUT / c["id"] / "control.csv", delimiter=",", names=True)
                for c in cases}
    thermal = {c["id"]:np.genfromtxt(OUT / c["id"] / "thermal.csv", delimiter=",", names=True)
               for c in cases}
    normal, chunk = controls["cycle-feedback"], controls["cycle-chunked"]
    compare = ("id_a", "iq_a", "speed_rad_s", "held_left_c", "held_right_c",
               "resistance_ohm", *base.J_FIELDS)
    chunk_control_error = max(float(np.max(abs(normal[n]-chunk[n]))) for n in compare)
    chunk_thermal_error = max(float(np.max(abs(
        thermal["cycle-feedback"][n]-thermal["cycle-chunked"][n])))
        for n in thermal["cycle-feedback"].dtype.names)
    native = np.genfromtxt(OUT / "cycle-feedback/native-controller.csv", delimiter=",", names=True)
    states = np.load(OUT / "cycle-feedback/thermal-fields.npz")["rom_states"]
    checkpoint_error = 0.
    for checkpoint in cases[-1]["checkpoints"]:
        tick = checkpoint["tick"]
        errors = [abs(checkpoint["pi_d_v"]-native["integral_d_v"][tick-1]),
                  abs(checkpoint["pi_q_v"]-native["integral_q_v"][tick-1]),
                  float(np.max(abs(np.array(checkpoint["thermal_state"])-states[tick//50])))]
        errors.extend(abs(checkpoint[n]-normal[n][tick]) for n in
                      ("id_a", "iq_a", "speed_rad_s"))
        errors.extend(abs(a-normal[n][tick]) for a, n in
                      zip(checkpoint["integrals_j"], base.J_FIELDS, strict=True))
        checkpoint_error = max(checkpoint_error, *errors)
        assert checkpoint["next_clock_tick"] == tick
        assert checkpoint["pending_control_intervals"] == tick % 50
    fine = thermal["cycle-fine"][::2]
    fine_mean = max(float(np.max(abs(thermal["cycle-feedback"][n]-fine[n])))
                    for n in ("left_c", "right_c"))
    fine_iq = float(np.max(abs(normal["iq_a"]-controls["cycle-fine"]["iq_a"])))
    frozen = controls["cycle-frozen"]
    copper_difference = float(abs(normal["copper_j"][-1]-frozen["copper_j"][-1]))
    iq_difference = float(np.max(abs(normal["iq_a"]-frozen["iq_a"])))
    checks = dict(
        all_cases=all(c["passed"] for c in cases),
        chunk_continuity=chunk_control_error <= 1e-10 and chunk_thermal_error <= 1e-10
        and checkpoint_error <= 1e-10,
        exact_chunk_clock=bool(np.array_equal(normal["tick"], chunk["tick"])
                               and np.array_equal(normal["phase_code"], chunk["phase_code"])),
        fine_rate=fine_mean <= .001 and fine_iq <= .001,
        causal_feedback=copper_difference >= 1e-10 and iq_difference >= 1e-9,
        frozen_training=freeze["training_sha256"] == hashes(base.BUNDLE / "train"),
        frozen_model=freeze["model_sha256"] == hashes(
            base.BUNDLE / "model", exclude=("freeze.json",)))
    report = dict(
        passed=bool(all(checks.values())), checks=checks, cases=cases,
        chunk_control_max_error=chunk_control_error, chunk_thermal_max_error=chunk_thermal_error,
        checkpoint_max_error=checkpoint_error, fine_mean_error_k=fine_mean,
        fine_iq_error_a=fine_iq, feedback_copper_difference_j=copper_difference,
        feedback_iq_difference_a=iq_difference, total_ticks=TOTAL_TICKS, duration_s=2.,
        chunk_ticks=list(CHUNK_TICKS), source_kind="synthetic", evidence_level="model_simulated",
        scope="two-second same-object continuation; external mechanical braking and cooling",
        commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        host=dict(platform=platform.platform(), cpu_info=Path("/proc/cpuinfo").read_text(),
                  peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
    (OUT / "validation.json").write_text(json.dumps(report, indent=2))
    print("p7-cycle-summary: "+json.dumps({k:v for k, v in report.items()
                                        if k not in {"cases", "host"}}), flush=True)
    assert report["passed"], checks


if __name__ == "__main__":
    main()
