"""Train/freeze a fixed-speed FOC mean-loss table, validate holdouts, apply to a ROM."""
import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from p7_locked_electrical import COLUMNS, OMEGA, simulate_locked
from p7_stator_fast_rom import OUT as ROM
from p7_stator_fast_rom import check_files, verified_model
from p7_temperature_feedback import MOTOR, load_motor
from p7_winding_heat import ROOT, digest

from oeal.current_envelope import advance_current_window
from oeal.foc_loss_map import FixedSpeedCopperLossMap
from oeal.stator_feedback import CopperResistanceLaw, StatorCopperFeedback

OUT = ROOT / "outputs/p7-foc-loss-map"
CONTRACT = ROOT / "docs/p7-foc-loss-map-contract.md"


def source_hashes():
    paths = (Path(__file__), CONTRACT, ROOT / "benchmarks/p7_locked_electrical.py",
             ROOT / "src/oeal/foc_loss_map.py", ROOT / "src/oeal/current_envelope.py",
             ROOT / "src/oeal/stator_feedback.py", ROOT / "src/oeal/current_control.py",
             ROOT / "src/oeal/foc.py", ROOT / "src/oeal/transforms.py",
             ROOT / "benchmarks/p7_cogging_model.py",
             ROOT / "benchmarks/p7_cogging_simulation.py",
             ROOT / "benchmarks/p7_temperature_feedback.py", MOTOR, MOTOR.with_name("fields.json"))
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}


def checked_thermal():
    frozen, _, _, _ = verified_model()
    summary = json.loads((ROM / "summary.json").read_text(encoding="utf-8"))
    if not summary["passed"] or summary["frozen_sha256"] != digest(ROM / "frozen.json"):
        raise ValueError("upstream ROM validation missing or stale")
    return frozen


def save_case(name, arrays):
    np.savez_compressed(OUT / (name+".npz"), **arrays)
    with (OUT / (name+".csv")).open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(COLUMNS)
        writer.writerows(arrays["control"])


def train():
    checked_thermal()
    hashes = source_hashes()
    thermal_sha = digest(ROM / "frozen.json")
    law = CopperResistanceLaw()
    temperatures = (25., 75., 125.)
    resistance = np.array([law.resistance(t) for t in temperatures])
    power = np.zeros((2, len(resistance)))
    OUT.mkdir(parents=True, exist_ok=True)
    cases = []
    for row, direction in enumerate((-1., 1.)):
        for column, (temperature, r) in enumerate(zip(temperatures, resistance, strict=True)):
            metrics, arrays = simulate_locked(load_motor(float(r)), direction, .1)
            name = f"train-{direction:+g}-{temperature:g}C"
            save_case(name, arrays)
            power[row, column] = metrics["mean_copper_w"]
            metrics.update(name=name, temperature_c=temperature, role="training")
            cases.append(metrics)
            print("loss-map-training:", json.dumps(metrics), flush=True)
    bundle = dict(format_version=1, resistance_ohm=resistance, mean_copper_w=power,
                  omega_abs_rad_s=OMEGA, reference_abs_a=.5)
    FixedSpeedCopperLossMap(bundle)
    np.savez(OUT / "inference.npz", **bundle)
    names = ["inference.npz"]+[p.name for p in OUT.glob("train-*") if p.is_file()]
    check_files(ROOT, hashes)
    if digest(ROM / "frozen.json") != thermal_sha:
        raise ValueError("upstream changed during loss-table training")
    frozen = dict(passed=all(c["passed"] for c in cases), training_cases=cases,
                  source_sha256=hashes, thermal_frozen_sha256=thermal_sha,
                  frozen_sha256={name: digest(OUT / name) for name in sorted(names)})
    (OUT / "frozen.json").write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    print("loss-map-frozen:", json.dumps({k: v for k, v in frozen.items()
                                         if k != "training_cases"}), flush=True)
    if not frozen["passed"]:
        raise SystemExit(1)


def thermal_application(model, direction, ambient):
    count = 24000
    mapped = StatorCopperFeedback.from_npz(ROM / "inference.npz", h_w_m2_k=8.,
                                          drive_dt_s=1., ticks_per_window=1, ambient_c=ambient)
    ideal = StatorCopperFeedback.from_npz(ROM / "inference.npz", h_w_m2_k=8.,
                                         drive_dt_s=1., ticks_per_window=1, ambient_c=ambient)
    values = np.zeros((count+1, 2, 9))
    values[0, :, :2] = ambient
    values[0, :, 4] = mapped.resistance_ohm
    for tick in range(1, count+1):
        for row, feedback in enumerate((mapped, ideal)):
            before = feedback.copper_j
            if row == 0:
                outputs = model.advance_thermal_window(feedback, tick,
                    omega_rad_s=direction*OMEGA, iq_reference_a=direction*.5)
            else:
                outputs = advance_current_window(feedback, tick, id_a=0., iq_a=direction*.5)
            values[tick, row] = np.r_[outputs, feedback.resistance_ohm,
                feedback.copper_j-before, feedback.copper_j, feedback.boundary_j,
                feedback.balance_j]
    difference = values[:, 0, 0]-values[:, 1, 0]
    balance = float(np.max(abs(values[:, :, 8])))
    name = f"thermal-{direction:+g}-{ambient:g}C"
    np.savez_compressed(OUT / (name+".npz"), time_s=np.arange(count+1), values=values)
    with np.load(ROM / "inference.npz", allow_pickle=False) as packet:
        upper = float(packet["power_bounds_w"][1])
    domain = bool(np.isfinite(values).all() and np.min(values[:, :, :2]) >= 25
                  and np.max(values[:, :, :2]) <= 125 and np.min(values[:, :, 5]) >= 0
                  and np.max(values[:, :, 5]) <= upper)
    result = dict(name=name, direction=direction, ambient_c=ambient, duration_s=count,
                  mapped_final_rise_k=float(mapped.outputs[0]-ambient),
                  ideal_final_rise_k=float(ideal.outputs[0]-ambient),
                  final_model_difference_k=float(difference[-1]),
                  max_model_difference_k=float(np.max(abs(difference))),
                  max_balance_j=balance, within_domain=domain,
                  passed=bool(domain and balance <= 1e-6))
    print("loss-map-thermal:", json.dumps(result), flush=True)
    return result


def validate():
    checked_thermal()
    frozen = json.loads((OUT / "frozen.json").read_text(encoding="utf-8"))
    frozen_sha = digest(OUT / "frozen.json")
    if not frozen["passed"]:
        raise ValueError("loss-map training failed")
    check_files(ROOT, frozen["source_sha256"])
    check_files(OUT, frozen["frozen_sha256"])
    if digest(ROM / "frozen.json") != frozen["thermal_frozen_sha256"]:
        raise ValueError("upstream thermal model changed")
    model = FixedSpeedCopperLossMap.from_npz(OUT / "inference.npz")
    law = CopperResistanceLaw()
    holdouts = []
    for direction in (-1., 1.):
        for temperature in (50., 100.):
            resistance = law.resistance(temperature)
            metrics, arrays = simulate_locked(load_motor(resistance), direction, .17,
                                              replay=direction == 1. and temperature == 50.)
            predicted = model.mean_power(resistance, omega_rad_s=direction*OMEGA,
                                         iq_reference_a=direction*.5)
            relative = abs(predicted-metrics["mean_copper_w"])/metrics["mean_copper_w"]
            name = f"holdout-{direction:+g}-{temperature:g}C"
            save_case(name, arrays)
            metrics.update(name=name, role="holdout", temperature_c=temperature,
                           predicted_mean_copper_w=predicted, relative_map_error=relative,
                           passed=bool(metrics["passed"] and relative <= .005))
            holdouts.append(metrics)
            print("loss-map-holdout:", json.dumps(metrics), flush=True)
    applications = [thermal_application(model, direction, ambient)
                    for direction in (-1., 1.) for ambient in (25., 75.)]
    rejections = {}
    for name, resistance, speed, reference in (
        ("low_R", .29, OMEGA, .5), ("high_R", .421, OMEGA, .5),
        ("speed", .33, 40., .5), ("reference", .33, OMEGA, .6),
        ("nonfinite", float("nan"), OMEGA, .5)):
        try:
            model.mean_power(resistance, omega_rad_s=speed, iq_reference_a=reference)
        except ValueError:
            rejections[name] = True
        else:
            rejections[name] = False
    check_files(ROOT, frozen["source_sha256"])
    check_files(OUT, frozen["frozen_sha256"])
    if digest(OUT / "frozen.json") != frozen_sha:
        raise ValueError("frozen loss-map metadata changed during validation")
    summary = dict(passed=bool(all(c["passed"] for c in holdouts+applications)
                               and all(rejections.values())),
                   training_cases=frozen["training_cases"], holdouts=holdouts,
                   thermal_applications=applications, domain_rejections=rejections,
                   frozen_sha256=frozen_sha, source_sha256=frozen["source_sha256"],
                   evidence_kind="model_simulated", operating_model="fixed_speed_periodic_FOC")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    figure(summary)
    manifest = {p.name: digest(p) for p in OUT.iterdir()
                if p.is_file() and p.name != "manifest.json"}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("foc-loss-map-summary:", json.dumps(summary), flush=True)
    if not summary["passed"]:
        raise SystemExit(1)


def figure(summary):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for direction, label in ((-1., "Reverse"), (1., "Forward")):
        train = [c for c in summary["training_cases"] if c["direction"] == direction]
        test = [c for c in summary["holdouts"] if c["direction"] == direction]
        axes[0].plot([c["temperature_c"] for c in train],
                     [100*c["ideal_relative_bias"] for c in train], "o-", label=label+" anchors")
        axes[0].scatter([c["temperature_c"] for c in test],
                        [100*c["ideal_relative_bias"] for c in test],
                        marker="x", label=label+" holdouts")
    for case in summary["thermal_applications"]:
        with np.load(OUT / (case["name"]+".npz"), allow_pickle=False) as data:
            difference = data["values"][:, 0, 0]-data["values"][:, 1, 0]
            axes[1].plot(data["time_s"]/3600, difference*1e6,
                         label=f"{case['direction']:+g}, {case['ambient_c']:g}°C")
    axes[0].set(xlabel="Resistance-law temperature (°C)", ylabel="Ideal-current copper bias (%)",
                title="Fixed-speed periodic FOC")
    axes[1].set(xlabel="Model time (h)", ylabel="Mapped minus ideal mean rise (µK)",
                title="ROM model difference, h=8")
    for axis in axes:
        axis.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "loss-map.png", dpi=160)
    fig.savefig(OUT / "loss-map.svg")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("train", "validate"))
    args = parser.parse_args()
    (train if args.stage == "train" else validate)()
