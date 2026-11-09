"""Freeze a speed/resistance FOC loss grid; validate periodic and accelerating holdouts."""
import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from p7_foc_loss_map import checked_thermal
from p7_locked_electrical import COLUMNS, OMEGA, TS, simulate_locked
from p7_speed_ramp import CONTROL_COLUMNS, THERMAL_COLUMNS, ramp_case
from p7_stator_fast_rom import OUT as ROM
from p7_stator_fast_rom import check_files
from p7_temperature_feedback import MOTOR, load_motor
from p7_winding_heat import ROOT, digest

from oeal.current_envelope import advance_current_window
from oeal.speed_loss_map import SpeedCopperLossMap
from oeal.stator_feedback import CopperResistanceLaw, StatorCopperFeedback

OUT = ROOT / "outputs/p7-speed-loss-map"
CONTRACT = ROOT / "docs/p7-speed-loss-map-contract.md"


def source_hashes():
    paths = (Path(__file__), CONTRACT, ROOT / "benchmarks/p7_speed_ramp.py",
             ROOT / "benchmarks/p7_locked_electrical.py", ROOT / "src/oeal/speed_loss_map.py",
             ROOT / "src/oeal/stator_feedback.py", ROOT / "src/oeal/current_envelope.py",
             ROOT / "src/oeal/current_control.py", ROOT / "src/oeal/foc.py",
             ROOT / "src/oeal/transforms.py", ROOT / "benchmarks/p7_cogging_model.py",
             ROOT / "benchmarks/p7_cogging_simulation.py", ROOT / "benchmarks/p7_foc_loss_map.py",
             ROOT / "benchmarks/p7_temperature_feedback.py", MOTOR, MOTOR.with_name("fields.json"))
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


def periodic_case(resistance, direction, ratio, repeat_s, theta0, *, replay=False):
    ticks = round(repeat_s/TS)
    burn = (round(.2/TS)+ticks-1)//ticks
    score = (round(.1/TS)+ticks-1)//ticks
    return simulate_locked(load_motor(resistance), direction, theta0, replay=replay,
        omega_abs_rad_s=ratio*OMEGA, repeat_s=repeat_s, burn_cycles=burn, score_cycles=score)


def train():
    checked_thermal()
    hashes, thermal_sha = source_hashes(), digest(ROM / "frozen.json")
    law = CopperResistanceLaw()
    temperatures, speeds = (25., 75., 125.), ((.5, .04), (1., .02), (2., .01))
    resistance = np.array([law.resistance(t) for t in temperatures])
    power = np.zeros((2, 3, 3))
    OUT.mkdir(parents=True, exist_ok=True)
    cases = []
    for row, direction in enumerate((-1., 1.)):
        for column, (ratio, period) in enumerate(speeds):
            for index, (temperature, r) in enumerate(zip(temperatures, resistance, strict=True)):
                result, arrays = periodic_case(float(r), direction, ratio, period, .1)
                name = f"train-{direction:+g}-{temperature:g}C-v{ratio:g}"
                save_run(name, arrays)
                power[row, column, index] = result["mean_copper_w"]
                result.update(name=name, temperature_c=temperature,
                              speed_ratio=ratio, role="training")
                cases.append(result)
                print("speed-map-training:", json.dumps(result), flush=True)
    bundle = dict(format_version=1, resistance_ohm=resistance,
                  speed_abs_rad_s=[v[0]*OMEGA for v in speeds],
                  mean_copper_w=power, reference_abs_a=.5)
    SpeedCopperLossMap(bundle)
    np.savez(OUT / "inference.npz", **bundle)
    names = ["inference.npz"]+[p.name for p in OUT.glob("train-*") if p.is_file()]
    check_files(ROOT, hashes)
    if digest(ROM / "frozen.json") != thermal_sha:
        raise ValueError("upstream thermal model changed during training")
    frozen = dict(passed=all(c["passed"] for c in cases), training_cases=cases,
                  source_sha256=hashes, thermal_frozen_sha256=thermal_sha,
                  frozen_sha256={name: digest(OUT / name) for name in sorted(names)})
    (OUT / "frozen.json").write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    print("speed-map-frozen:", json.dumps({k: v for k, v in frozen.items()
                                          if k != "training_cases"}), flush=True)
    if not frozen["passed"]:
        raise SystemExit(1)


def thermal_application(model, direction, ambient):
    mapped = StatorCopperFeedback.from_npz(ROM / "inference.npz", h_w_m2_k=8.,
        drive_dt_s=1., ticks_per_window=1, ambient_c=ambient)
    ideal = StatorCopperFeedback.from_npz(ROM / "inference.npz", h_w_m2_k=8.,
        drive_dt_s=1., ticks_per_window=1, ambient_c=ambient)
    values = np.zeros((24001, 2, 9))
    values[0, :, :2] = ambient
    values[0, :, 4] = mapped.resistance_ohm
    speeds = np.zeros(24001)
    for tick in range(1, 24001):
        phase = (tick-1) % 1200
        ratio = .5+1.5*(phase/600 if phase <= 600 else (1200-phase)/600)
        speed = direction*OMEGA*ratio
        speeds[tick] = speed
        for row, feedback in enumerate((mapped, ideal)):
            before = feedback.copper_j
            if row == 0:
                outputs = model.advance_thermal_window(feedback, tick, omega_rad_s=speed,
                                                       iq_reference_a=direction*.5)
            else:
                outputs = advance_current_window(feedback, tick, id_a=0., iq_a=direction*.5)
            values[tick, row] = np.r_[outputs, feedback.resistance_ohm,
                feedback.copper_j-before, feedback.copper_j, feedback.boundary_j,
                feedback.balance_j]
    name = f"thermal-{direction:+g}-{ambient:g}C"
    np.savez_compressed(OUT / (name+".npz"), time_s=np.arange(24001),
                        omega_rad_s=speeds, values=values)
    balance = float(np.max(abs(values[:, :, 8])))
    with np.load(ROM / "inference.npz", allow_pickle=False) as data:
        upper = float(data["power_bounds_w"][1])
    domain = bool(np.isfinite(values).all() and np.min(values[:, :, :2]) >= 25
                  and np.max(values[:, :, :2]) <= 125 and np.min(values[:, :, 5]) >= 0
                  and np.max(values[:, :, 5]) <= upper)
    result = dict(name=name, direction=direction, ambient_c=ambient,
                  max_model_difference_k=float(np.max(abs(values[:, 0, 0]-values[:, 1, 0]))),
                  max_balance_j=balance, within_domain=domain,
                  passed=bool(domain and balance <= 1e-6))
    print("speed-map-thermal:", json.dumps(result), flush=True)
    return result


def validate():
    checked_thermal()
    frozen = json.loads((OUT / "frozen.json").read_text(encoding="utf-8"))
    frozen_sha = digest(OUT / "frozen.json")
    if not frozen["passed"]:
        raise ValueError("speed-loss-map training failed")
    check_files(ROOT, frozen["source_sha256"])
    check_files(OUT, frozen["frozen_sha256"])
    if digest(ROM / "frozen.json") != frozen["thermal_frozen_sha256"]:
        raise ValueError("upstream thermal model changed")
    model = SpeedCopperLossMap.from_npz(OUT / "inference.npz")
    law = CopperResistanceLaw()
    holdouts = []
    for direction in (-1., 1.):
        for ratio, period in ((.75, .08), (1.5, .04)):
            for temperature in (50., 100.):
                resistance = law.resistance(temperature)
                result, arrays = periodic_case(resistance, direction, ratio, period, .17,
                    replay=direction == 1. and ratio == 1.5 and temperature == 50.)
                prediction = model.mean_power(resistance, omega_rad_s=direction*ratio*OMEGA,
                                              iq_reference_a=direction*.5)
                relative = abs(prediction-result["mean_copper_w"])/result["mean_copper_w"]
                name = f"holdout-{direction:+g}-{temperature:g}C-v{ratio:g}"
                save_run(name, arrays)
                result.update(name=name, role="holdout", speed_ratio=ratio,
                              temperature_c=temperature,
                              predicted_copper_w=prediction, relative_map_error=relative,
                              passed=bool(result["passed"] and relative <= .005))
                holdouts.append(result)
                print("speed-map-holdout:", json.dumps(result), flush=True)
    ramps, selected = [], None
    for direction, ambient in ((1., 50.), (-1., 100.)):
        result, arrays = ramp_case(model, direction, ambient, replay=direction == 1.)
        result["name"] = f"ramp-{direction:+g}"
        save_run(result["name"], arrays, CONTROL_COLUMNS)
        ramps.append(result)
        print("speed-map-ramp:", json.dumps(result), flush=True)
        if direction == 1.:
            selected = arrays
    fine, fine_arrays = ramp_case(model, 1., 50., dt=2.5e-6)
    save_run("ramp-fine", fine_arrays, CONTROL_COLUMNS)
    current_difference = float(np.max(abs(selected["control"][:, 3:5]
                                         -fine_arrays["control"][:, 3:5])))
    energy_difference = abs(float(selected["control"][-1, 8]-fine_arrays["control"][-1, 8]))
    relative_energy = energy_difference/float(fine_arrays["control"][-1, 8])
    refinement = dict(max_current_difference_a=current_difference,
                      relative_total_copper_difference=relative_energy,
                      passed=bool(current_difference <= 1e-5 and relative_energy <= 1e-5))
    applications = [thermal_application(model, direction, ambient)
                    for direction in (-1., 1.) for ambient in (25., 75.)]
    rejections = {}
    for name, r, v, i in (("R", .29, OMEGA, .5), ("low_speed", .33, .49*OMEGA, .5),
        ("high_speed", .33, 2.01*OMEGA, .5), ("reference", .33, OMEGA, -.5),
        ("nonfinite", float("nan"), OMEGA, .5)):
        try:
            model.mean_power(r, omega_rad_s=v, iq_reference_a=i)
        except ValueError:
            rejections[name] = True
        else:
            rejections[name] = False
    check_files(ROOT, frozen["source_sha256"])
    check_files(OUT, frozen["frozen_sha256"])
    if digest(OUT / "frozen.json") != frozen_sha:
        raise ValueError("frozen map changed during validation")
    summary = dict(passed=bool(all(c["passed"] for c in holdouts+ramps+applications)
                               and fine["passed"] and refinement["passed"]
                               and all(rejections.values())),
                   training_cases=frozen["training_cases"], holdouts=holdouts,
                   ramps=ramps, fine=fine, refinement=refinement,
                   thermal_applications=applications, domain_rejections=rejections,
                   frozen_sha256=frozen_sha, source_sha256=frozen["source_sha256"],
                   evidence_kind="model_simulated",
                   operating_model="prescribed_speed_fixed_reference")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    figure(summary)
    manifest = {p.name: digest(p) for p in OUT.iterdir()
                if p.is_file() and p.name != "manifest.json"}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("speed-loss-map-summary:", json.dumps(summary), flush=True)
    if not summary["passed"]:
        raise SystemExit(1)


def figure(summary):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for direction in (-1., 1.):
        cases = [c for c in summary["holdouts"] if c["direction"] == direction]
        axes[0].scatter([c["speed_ratio"] for c in cases],
                        [100*c["relative_map_error"] for c in cases], label=f"dir {direction:+g}")
    for case in summary["ramps"]:
        with np.load(OUT / (case["name"]+".npz"), allow_pickle=False) as data:
            rows = data["thermal"]
            mask = rows[:, 0] > .2
            error = (rows[mask, 8]/rows[mask, 7]-1)*100
            axes[1].plot(rows[mask, 0], error, label=case["name"])
    axes[0].set(xlabel="Holdout speed / Ω0", ylabel="Mean copper interpolation error (%)",
                title="Untrained speed and resistance")
    axes[1].set(xlabel="Time (s)", ylabel="Window copper prediction error (%)",
                title="Actual FOC acceleration/deceleration")
    for axis in axes:
        axis.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "speed-map.png", dpi=160)
    fig.savefig(OUT / "speed-map.svg")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("train", "validate"))
    args = parser.parse_args()
    (train if args.stage == "train" else validate)()
