"""Current-reference copper Gram model with independent amplitude and transient holdouts."""
import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from p7_foc_loss_map import checked_thermal
from p7_locked_electrical import COLUMNS, OMEGA, TS, generator_and_work, quadratic_flow
from p7_reference_periodic import control_states, quadratic_moments, simulate_reference
from p7_reference_ramp import CONTROL_COLUMNS, THERMAL_COLUMNS, reference_case
from p7_speed_loss_map import OUT as PARENT
from p7_stator_fast_rom import OUT as ROM
from p7_stator_fast_rom import check_files
from p7_temperature_feedback import MOTOR, load_motor
from p7_winding_heat import ROOT, digest

from oeal.current_envelope import advance_current_window
from oeal.reference_loss_map import ReferenceCopperLossMap
from oeal.stator_feedback import CopperResistanceLaw, StatorCopperFeedback

OUT = ROOT / "outputs/p7-reference-loss-map"
CONTRACT = ROOT / "docs/p7-reference-loss-map-contract.md"


def checked_parent():
    checked_thermal()
    frozen = json.loads((PARENT / "frozen.json").read_text(encoding="utf-8"))
    summary = json.loads((PARENT / "summary.json").read_text(encoding="utf-8"))
    if (not frozen["passed"] or not summary["passed"]
            or summary["frozen_sha256"] != digest(PARENT / "frozen.json")):
        raise ValueError("parent loss-grid evidence missing or stale")
    check_files(ROOT, frozen["source_sha256"])
    check_files(PARENT, frozen["frozen_sha256"])
    return frozen


def source_hashes():
    paths = (Path(__file__), CONTRACT, ROOT / "benchmarks/p7_reference_periodic.py",
             ROOT / "benchmarks/p7_reference_ramp.py", ROOT / "src/oeal/reference_loss_map.py",
             ROOT / "src/oeal/reference_validity.py", ROOT / "benchmarks/p7_speed_ramp.py",
             ROOT / "benchmarks/p7_locked_electrical.py", ROOT / "src/oeal/stator_feedback.py",
             ROOT / "src/oeal/current_envelope.py", ROOT / "src/oeal/current_control.py",
             ROOT / "src/oeal/foc.py", ROOT / "src/oeal/transforms.py", MOTOR,
             MOTOR.with_name("fields.json"))
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}


def save_run(name, arrays, columns=COLUMNS):
    np.savez_compressed(OUT / (name+".npz"), **arrays)
    with (OUT / (name+".csv")).open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(columns)
        writer.writerows(arrays["control"])
    if "thermal" in arrays:
        with (OUT / (name+"-thermal.csv")).open("w", encoding="utf-8", newline="") as fp:
            writer = csv.writer(fp)
            writer.writerow(THERMAL_COLUMNS)
            writer.writerows(arrays["thermal"])


def train():
    parent = checked_parent()
    hashes = source_hashes()
    parent_sha, thermal_sha = digest(PARENT / "frozen.json"), digest(ROM / "frozen.json")
    with np.load(PARENT / "inference.npz", allow_pickle=False) as data:
        resistance, speeds = data["resistance_ohm"], data["speed_abs_rad_s"]
    coefficients = np.zeros((2, len(speeds), len(resistance), 3))
    OUT.mkdir(parents=True, exist_ok=True)
    cases = []
    for anchor in parent["training_cases"]:
        motor = load_motor(anchor["resistance_ohm"])
        metrics, arrays = simulate_reference(motor, anchor["direction"], .1, reference_abs_a=0.,
            omega_abs_rad_s=abs(anchor["omega_rad_s"]), repeat_s=anchor["repeat_s"],
            burn_cycles=anchor["burn_cycles"], score_cycles=anchor["score_cycles"])
        name = "zero-"+anchor["name"]
        save_run(name, arrays)
        parent_file = anchor["name"]+".npz"
        with np.load(PARENT / parent_file, allow_pickle=False) as data:
            full_trace = data["control"]
        trace = arrays["control"]
        if not np.array_equal(trace[:, :2], full_trace[:, :2]):
            raise ValueError("parent and zero-reference clocks/phases differ")
        start = anchor["burn_cycles"]*round(anchor["repeat_s"]/TS)
        zero_states = control_states(trace[start:-1])
        full_states = control_states(full_trace[start:-1])
        generator, work, _, _ = generator_and_work(motor, anchor["omega_rad_s"])
        _, gram = quadratic_flow(generator, work[1:2], TS)
        duration = (len(trace)-1-start)*TS
        values = quadratic_moments(gram[0], zero_states, full_states, .5, duration)
        matrix = np.array([[values[0], values[1]/2], [values[1]/2, values[2]]])
        minimum = float(np.min(np.linalg.eigvalsh(matrix)))
        low_error = abs(values[2]-metrics["mean_copper_w"])/metrics["mean_copper_w"]
        full_error = abs(np.polyval(values, .5)-anchor["mean_copper_w"])/anchor["mean_copper_w"]
        row = 1 if anchor["direction"] > 0 else 0
        vi = int(np.flatnonzero(speeds == abs(anchor["omega_rad_s"]))[0])
        ri = int(np.flatnonzero(resistance == anchor["resistance_ohm"])[0])
        coefficients[row, vi, ri] = values
        metrics.update(name=name, role="zero_reference_endpoint", parent_name=anchor["name"],
            parent_file_sha256=parent["frozen_sha256"][parent_file], coefficients=values.tolist(),
            coefficient_min_eigenvalue=minimum,
            endpoint_reconstruction_relative=float(max(low_error, full_error)),
            passed=bool(metrics["passed"] and minimum >= -1e-12
                        and max(low_error, full_error) <= 1e-6))
        cases.append(metrics)
        print("reference-map-training:", json.dumps(metrics), flush=True)
    bundle = dict(format_version=1, resistance_ohm=resistance, speed_abs_rad_s=speeds,
                  copper_coefficients=coefficients, reference_max_a=.5)
    ReferenceCopperLossMap(bundle)
    np.savez(OUT / "inference.npz", **bundle)
    names = ["inference.npz"]+[p.name for p in OUT.glob("zero-*") if p.is_file()]
    check_files(ROOT, hashes)
    if digest(PARENT / "frozen.json") != parent_sha or digest(ROM / "frozen.json") != thermal_sha:
        raise ValueError("parent evidence changed during coefficient construction")
    frozen = dict(passed=all(c["passed"] for c in cases), zero_cases=cases,
        reused_training_cases=parent["training_cases"], parent_frozen_sha256=parent_sha,
        thermal_frozen_sha256=thermal_sha, source_sha256=hashes,
        frozen_sha256={name: digest(OUT / name) for name in sorted(names)})
    (OUT / "frozen.json").write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    metadata = {k: v for k, v in frozen.items() if k not in ("zero_cases", "reused_training_cases")}
    print("reference-map-frozen:", json.dumps(metadata), flush=True)
    if not frozen["passed"]:
        raise SystemExit(1)


def thermal_application(model, direction, ambient):
    mapped = StatorCopperFeedback.from_npz(ROM / "inference.npz", h_w_m2_k=8.,
        drive_dt_s=1., ticks_per_window=1, ambient_c=ambient)
    ideal = StatorCopperFeedback.from_npz(ROM / "inference.npz", h_w_m2_k=8.,
        drive_dt_s=1., ticks_per_window=1, ambient_c=ambient)
    values = np.zeros((24001, 2, 9))
    values[0, :, :2], values[0, :, 4] = ambient, mapped.resistance_ohm
    commands = np.zeros((24001, 2))
    for tick in range(1, 24001):
        phase = (tick-1) % 1200
        weight = phase/600 if phase <= 600 else (1200-phase)/600
        speed, reference = direction*OMEGA*(.5+1.5*weight), direction*(.125+.325*weight)
        commands[tick] = speed, reference
        for row, feedback in enumerate((mapped, ideal)):
            before = feedback.copper_j
            if row == 0:
                power = model.mean_power(feedback.resistance_ohm, omega_rad_s=speed,
                                         iq_reference_a=reference)
                output = feedback.advance_window(tick, before+power)
            else:
                output = advance_current_window(feedback, tick, id_a=0., iq_a=reference)
            values[tick, row] = np.r_[output, feedback.resistance_ohm, feedback.copper_j-before,
                                     feedback.copper_j, feedback.boundary_j, feedback.balance_j]
    name = f"thermal-{direction:+g}-{ambient:g}C"
    np.savez_compressed(OUT / (name+".npz"), time_s=np.arange(24001),
                        commands=commands, values=values)
    balance = float(np.max(abs(values[:, :, 8])))
    with np.load(ROM / "inference.npz", allow_pickle=False) as packet:
        upper = float(packet["power_bounds_w"][1])
    domain = bool(np.isfinite(values).all() and np.min(values[:, :, :2]) >= 25
                  and np.max(values[:, :, :2]) <= 125 and np.min(values[:, :, 5]) >= 0
                  and np.max(values[:, :, 5]) <= upper)
    result = dict(name=name, direction=direction, ambient_c=ambient, max_balance_j=balance,
        max_model_difference_k=float(np.max(abs(values[:, 0, 0]-values[:, 1, 0]))),
        within_domain=domain, passed=bool(domain and balance <= 1e-6))
    print("reference-map-thermal:", json.dumps(result), flush=True)
    return result


def validate():
    checked_parent()
    frozen = json.loads((OUT / "frozen.json").read_text(encoding="utf-8"))
    frozen_sha = digest(OUT / "frozen.json")
    if not frozen["passed"]:
        raise ValueError("reference coefficient construction failed")
    check_files(ROOT, frozen["source_sha256"])
    check_files(OUT, frozen["frozen_sha256"])
    if (digest(PARENT / "frozen.json") != frozen["parent_frozen_sha256"]
            or digest(ROM / "frozen.json") != frozen["thermal_frozen_sha256"]):
        raise ValueError("parent evidence changed")
    model, law = ReferenceCopperLossMap.from_npz(OUT / "inference.npz"), CopperResistanceLaw()
    holdouts = []
    for direction in (-1., 1.):
        for ratio, period in ((.75, .08), (1.5, .04)):
            ticks = round(period/TS)
            for temperature in (50., 100.):
                resistance = law.resistance(temperature)
                for amplitude in (.125, .375):
                    result, arrays = simulate_reference(load_motor(resistance), direction, .17,
                        reference_abs_a=amplitude, omega_abs_rad_s=ratio*OMEGA, repeat_s=period,
                        burn_cycles=(4000+ticks-1)//ticks, score_cycles=(2000+ticks-1)//ticks,
                        replay=direction == 1. and ratio == 1.5
                        and temperature == 50. and amplitude == .125)
                    predicted = model.mean_power(resistance, omega_rad_s=direction*ratio*OMEGA,
                                                 iq_reference_a=direction*amplitude)
                    relative = abs(predicted-result["mean_copper_w"])/result["mean_copper_w"]
                    name = f"holdout-{direction:+g}-{temperature:g}C-v{ratio:g}-I{amplitude:g}"
                    save_run(name, arrays)
                    result.update(name=name, role="holdout", temperature_c=temperature,
                        speed_ratio=ratio,
                        predicted_mean_copper_w=predicted, relative_map_error=relative,
                        passed=bool(result["passed"] and relative <= .005))
                    holdouts.append(result)
                    print("reference-map-holdout:", json.dumps(result), flush=True)
    ramps, selected = [], None
    configurations = ((1., 50., "smooth"), (-1., 100., "smooth"), (1., 50., "step"))
    for direction, ambient, profile in configurations:
        result, arrays = reference_case(model, direction, ambient, profile,
                                        replay=direction == 1. and profile == "smooth")
        name = f"{profile}-{direction:+g}"
        result["name"] = name
        save_run(name, arrays, CONTROL_COLUMNS)
        ramps.append(result)
        print("reference-map-dynamic:", json.dumps(result), flush=True)
        if direction == 1. and profile == "smooth":
            selected = arrays
    fine, fine_arrays = reference_case(model, 1., 50., dt=2.5e-6)
    save_run("smooth-fine", fine_arrays, CONTROL_COLUMNS)
    current_error = float(np.max(abs(selected["control"][:, 3:5]-fine_arrays["control"][:, 3:5])))
    copper_error = abs(float(selected["control"][-1, 8]/fine_arrays["control"][-1, 8]-1))
    refinement = dict(max_current_difference_a=current_error,
                      relative_copper_difference=copper_error,
                      passed=bool(current_error <= 1e-5 and copper_error <= 1e-5))
    applications = [thermal_application(model, d, t) for d in (-1., 1.) for t in (25., 75.)]
    check_files(ROOT, frozen["source_sha256"])
    check_files(OUT, frozen["frozen_sha256"])
    if digest(OUT / "frozen.json") != frozen_sha:
        raise ValueError("frozen reference map changed during validation")
    summary = dict(passed=bool(all(c["passed"] for c in holdouts+ramps+applications)
                               and fine["passed"] and refinement["passed"]),
        zero_cases=frozen["zero_cases"], reused_training_cases=frozen["reused_training_cases"],
        holdouts=holdouts, dynamics=ramps, fine=fine, refinement=refinement,
        thermal_applications=applications, frozen_sha256=frozen_sha,
        parent_frozen_sha256=frozen["parent_frozen_sha256"], source_sha256=frozen["source_sha256"],
        evidence_kind="model_simulated",
        operating_model="prescribed_speed_reference_with_validity_guard")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    figure(summary)
    manifest = {p.name: digest(p) for p in OUT.iterdir()
                if p.is_file() and p.name != "manifest.json"}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("reference-loss-map-summary:", json.dumps(summary), flush=True)
    if not summary["passed"]:
        raise SystemExit(1)


def figure(summary):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for direction in (-1., 1.):
        cases = [c for c in summary["holdouts"] if c["direction"] == direction]
        axes[0].scatter([c["reference_abs_a"] for c in cases],
                        [100*c["relative_map_error"] for c in cases], label=f"dir {direction:+g}")
    with np.load(OUT / "step-+1.npz", allow_pickle=False) as data:
        values = data["thermal"]
        mask = values[:, 0] > .2
        times, error = values[mask, 0], (values[mask, 8]/values[mask, 7]-1)*100
        ready = values[mask, 12].astype(bool)
        axes[1].plot(times, error, color="gray", label="All raw windows")
        axes[1].scatter(times[ready], error[ready], s=7, label="Guard ready")
        axes[1].scatter(times[~ready], error[~ready], s=12, label="Guard unready")
    axes[0].set(xlabel="Untrained reference amplitude (A)", ylabel="Copper interpolation error (%)",
                title="New amplitude, speed and resistance")
    axes[1].set(xlabel="Time (s)", ylabel="Window prediction error (%)",
                title="Step transient: all errors retained")
    for axis in axes:
        axis.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "reference-map.png", dpi=160)
    fig.savefig(OUT / "reference-map.svg")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("train", "validate"))
    args = parser.parse_args()
    (train if args.stage == "train" else validate)()
