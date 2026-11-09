"""Long thermal feedback under prescribed current envelopes, not continuous FOC."""
import json
import platform
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from p7_stator_fast_rom import OUT as ROM
from p7_stator_fast_rom import check_files, verified_model
from p7_winding_heat import ROOT, digest
from scipy.sparse import diags
from scipy.sparse.linalg import factorized

from oeal.current_envelope import advance_current_window, copper_power
from oeal.stator_feedback import CopperResistanceLaw, StatorCopperFeedback

OUT = ROOT / "outputs/p7-feedback-endurance"
CONTRACT = ROOT / "docs/p7-feedback-endurance-contract.md"
TOTAL = 24000
SNAPSHOT_S = 120


def envelope(name, tick, dt):
    if name in ("A", "B"):
        return .5
    if name == "C":
        return .5 if tick // round(600/dt) % 2 == 0 else 0.
    raise ValueError("unknown prescribed current envelope")


def make_feedback(bundle, h, ambient, dt):
    return StatorCopperFeedback(bundle, h_w_m2_k=h, drive_dt_s=dt,
                                ticks_per_window=1, ambient_c=ambient)


def steady_case(fom, bundle, basis, h, ambient, *, law=None, iq=.5):
    law = CopperResistanceLaw() if law is None else law
    source = fom["forcing"]
    if not np.array_equal(source, fom["observations"][0]):
        raise ValueError("symmetric winding source/observation required for stability certificate")
    stiffness = fom["bulk"]+h*fom["convection"]
    z = factorized(stiffness.tocsc())(source)
    a = copper_power(0., iq, law.resistance(ambient))
    beta = 1.5*iq*iq*law.reference_ohm*law.coefficient_per_k
    gain = float(beta*(source@z))
    if not 0 <= gain < 1:
        raise ValueError("unstable or invalid constant-current thermal feedback")
    full = a*z/(1-gain)
    reduced_k = bundle["bulk"]+h*bundle["convection"]
    reduced_f = bundle["forcing"]
    reduced_gain = float(beta*reduced_f@np.linalg.solve(reduced_k, reduced_f))
    effective = reduced_k-beta*np.outer(reduced_f, reduced_f)
    minimum = float(np.min(np.linalg.eigvalsh(effective)))
    if not 0 <= reduced_gain < 1 or minimum <= 0:
        raise ValueError("unstable reduced feedback operator")
    reduced = np.linalg.solve(effective, a*reduced_f)
    field = basis@reduced
    full_winding = float(source@full)
    reduced_winding = float(bundle["observations"][0]@reduced)
    full_power, reduced_power = a+beta*full_winding, a+beta*reduced_winding
    field_error = float(np.max(abs(full-field)))
    peak = float(np.max(abs(full)))
    relative = field_error/peak if peak else float("inf")
    mean_error = abs(full_winding-reduced_winding)
    upper = float(bundle["power_bounds_w"][1])
    law.resistance(ambient+full_winding)
    law.resistance(ambient+reduced_winding)
    result = dict(h=h, ambient_c=ambient, full_loop_gain=gain,
                  full_stability_margin=1-gain, reduced_loop_gain=reduced_gain,
                  reduced_effective_min_eigenvalue=minimum,
                  full_winding_rise_k=full_winding, reduced_winding_rise_k=reduced_winding,
                  full_power_w=full_power, reduced_power_w=reduced_power,
                  max_field_error_k=field_error, relative_field_error=relative,
                  winding_error_k=mean_error,
                  passed=bool(field_error <= 1e-3 and relative <= .001 and mean_error <= 1e-4
                              and 0 <= full_power <= upper and 0 <= reduced_power <= upper
                              and ambient+max(float(np.max(full)), float(np.max(field))) <= 125))
    return result, dict(full_field=full, rom_field=field, reduced_state=reduced)


def paired_case(fom, bundle, basis, name, h, ambient, dt):
    steps, stride = round(TOTAL/dt), round(SNAPSHOT_S/dt)
    feedback = make_feedback(bundle, h, ambient, dt)
    law = CopperResistanceLaw()
    initial_r = law.resistance(ambient)
    beta_r = law.reference_ohm*law.coefficient_per_k
    mass, source = fom["mass"], fom["forcing"]
    solve = factorized((diags(mass)+dt*(fom["bulk"]+h*fom["convection"])).tocsc())
    observation = fom["observations"].copy()
    observation[3] *= h
    state = np.zeros(len(mass))
    full_output = np.array([ambient, ambient, 0., 0.])
    full_source = full_boundary = 0.
    outputs = np.zeros((steps+1, 2, 4))
    outputs[0, :, :2] = ambient
    power = np.zeros((steps+1, 2))
    resistance = np.full((steps+1, 2), initial_r)
    energy = np.zeros((steps+1, 2, 3))  # source, boundary, balance; FE then ROM
    fields = [np.zeros((2, len(mass)))]
    max_field = peak = max_mean = max_balance = 0.
    for tick in range(1, steps+1):
        current = envelope(name, tick-1, dt)
        # Independent FE algebra: a + beta * winding rise at the LEFT window endpoint.
        full_power = 1.5*current*current*(initial_r+beta_r*float(source@state))
        if not np.isfinite(full_power) or not 0 <= full_power <= bundle["power_bounds_w"][1]:
            raise ValueError("FE current-envelope power outside frozen domain")
        state = solve(mass*state+dt*source*full_power)
        full_output = observation@state
        full_output[:2] += ambient
        full_r = law.resistance(float(full_output[0]))
        full_source += dt*full_power
        full_boundary += dt*full_output[3]
        old_source = feedback.copper_j
        reduced_output = advance_current_window(feedback, tick, id_a=0., iq_a=current)
        reduced_field = basis@feedback.state
        full_balance = full_source-full_boundary-full_output[2]
        max_balance = max(max_balance, abs(full_balance), abs(feedback.balance_j))
        max_field = max(max_field, float(np.max(abs(state-reduced_field))))
        peak = max(peak, float(np.max(abs(state))))
        max_mean = max(max_mean, float(max(abs(full_output[:2]-reduced_output[:2]))))
        outputs[tick] = full_output, reduced_output
        power[tick] = full_power, (feedback.copper_j-old_source)/dt
        resistance[tick] = full_r, feedback.resistance_ohm
        energy[tick, 0] = full_source, full_boundary, full_balance
        energy[tick, 1] = feedback.copper_j, feedback.boundary_j, feedback.balance_j
        if tick % stride == 0:
            fields.append(np.stack((state.copy(), reduced_field.copy())))
    relative = max_field/peak if peak else float("inf")
    fraction = float((feedback.resistance_ohm-initial_r)/initial_r)
    positive_feedback = name == "C" or fraction >= .001
    within_domain = bool(np.max(power) <= bundle["power_bounds_w"][1]
                         and np.min(outputs[:, :, :2]) >= 0
                         and np.max(outputs[:, :, :2]) <= 125)
    result = dict(name=name, h=h, ambient_c=ambient, duration_s=TOTAL, dt_s=dt,
                  endpoints=steps+1, field_snapshots=len(fields),
                  max_field_error_k=max_field, relative_field_error=relative,
                  max_mean_error_k=max_mean, max_balance_j=float(max_balance),
                  final_winding_rise_k=float(feedback.outputs[0]-ambient),
                  final_resistance_fraction=fraction, peak_field_rise_k=peak,
                  within_frozen_domain=within_domain,
                  passed=bool(max_field <= 1e-3 and relative <= .001 and max_mean <= 1e-4
                              and max_balance <= 1e-6 and positive_feedback and within_domain))
    arrays = dict(time_s=np.arange(steps+1)*dt, outputs=outputs, power_w=power,
                  resistance_ohm=resistance, energy_j=energy,
                  snapshot_time_s=np.arange(len(fields))*SNAPSHOT_S, fields=np.array(fields))
    print("endurance-case:", json.dumps(result), flush=True)
    return result, arrays


def fast_case(bundle, fine_outputs):
    dt, duration = .0025, 1200
    feedback = make_feedback(bundle, 8., 75., dt)
    count = round(duration/dt)
    values = np.zeros((count+1, 9))  # four outputs, R, power, source, boundary, balance
    values[0, :2] = 75.
    values[0, 4] = feedback.resistance_ohm
    start = time.perf_counter()
    for tick in range(1, count+1):
        old_source = feedback.copper_j
        output = advance_current_window(feedback, tick, id_a=0., iq_a=.5)
        values[tick] = np.r_[output, feedback.resistance_ohm,
                             (feedback.copper_j-old_source)/dt, feedback.copper_j,
                             feedback.boundary_j, feedback.balance_j]
    reference = fine_outputs[:round(duration/.5)+1, 0, :2]
    error = float(np.max(abs(values[::200, :2]-reference)))
    balance = float(np.max(abs(values[:, 8])))
    result = dict(duration_s=duration, dt_s=dt, updates=count,
                  mean_difference_from_half_second_fe_k=error,
                  max_balance_j=balance, execution_wall_s=time.perf_counter()-start,
                  passed=bool(error <= 1e-4 and balance <= 1e-6))
    np.savez_compressed(OUT / "B-400Hz.npz", dt_s=dt, values=values)
    print("endurance-fast:", json.dumps(result), flush=True)
    return result


def main():
    frozen, fom, basis, _ = verified_model()
    validated = json.loads((ROM / "summary.json").read_text(encoding="utf-8"))
    frozen_sha = digest(ROM / "frozen.json")
    if not validated["passed"] or validated["frozen_sha256"] != frozen_sha:
        raise ValueError("short-time ROM validation missing or stale")
    paths = (Path(__file__), CONTRACT, ROOT / "src/oeal/stator_feedback.py",
             ROOT / "src/oeal/current_envelope.py")
    hashes = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    with np.load(ROM / "inference.npz", allow_pickle=False) as data:
        bundle = {key: data[key] for key in data.files}
    OUT.mkdir(parents=True, exist_ok=True)
    cases, steady = [], []
    selected = None
    for name, h, ambient in (("A", 8., 25.), ("B", 8., 75.), ("C", 65., 75.)):
        case, arrays = paired_case(fom, bundle, basis, name, h, ambient, 1.)
        np.savez_compressed(OUT / f"{name}-1s.npz", **arrays)
        cases.append(case)
        if name != "C":
            result, states = steady_case(fom, bundle, basis, h, ambient)
            result.update(name=name, final_field_distance_from_steady_k=float(np.max(
                abs(arrays["fields"][-1, 0]-states["full_field"]))))
            steady.append(result)
            np.savez_compressed(OUT / f"{name}-steady.npz", **states)
            print("endurance-steady:", json.dumps(result), flush=True)
        if name == "B":
            selected = arrays
    fine, fine_arrays = paired_case(fom, bundle, basis, "B", 8., 75., .5)
    np.savez_compressed(OUT / "B-half-second.npz", **fine_arrays)
    mean_difference = float(np.max(abs(selected["outputs"][:, :, :2]
                                       -fine_arrays["outputs"][::2, :, :2])))
    field_difference = float(np.max(abs(selected["fields"]-fine_arrays["fields"])))
    refinement = dict(mean_difference_k=mean_difference,
                      snapshot_field_difference_k=field_difference,
                      passed=bool(mean_difference <= 1e-4 and field_difference <= 1e-3))
    fast = fast_case(bundle, fine_arrays["outputs"])
    rejection = make_feedback(bundle, 8., 75., 1.)
    try:
        advance_current_window(rejection, 1, id_a=0., iq_a=2.)
    except ValueError:
        domain_rejected = bool(rejection.windows == 0 and not np.any(rejection.state)
                               and rejection.copper_j == 0.)
    else:
        domain_rejected = False
    check_files(ROM, frozen["frozen_sha256"])
    check_files(ROOT, hashes)
    if digest(ROM / "frozen.json") != frozen_sha:
        raise ValueError("frozen metadata changed during endurance validation")
    summary = dict(passed=bool(all(c["passed"] for c in cases+steady)
                               and fine["passed"] and refinement["passed"]
                               and fast["passed"] and domain_rejected),
                   cases=cases, steady_cases=steady, fine=fine, refinement=refinement, fast=fast,
                   domain_rejected=domain_rejected, source_sha256=hashes,
                   frozen_sha256=frozen_sha, dimensions=frozen["dimensions"],
                   platform=platform.platform(), numpy_version=np.__version__,
                   electrical_model="prescribed_dq_current_envelope",
                   evidence_kind="model_simulated")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    figure(cases)
    manifest = {p.name: digest(p) for p in OUT.iterdir()
                if p.is_file() and p.name != "manifest.json"}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("feedback-endurance-summary:", json.dumps(summary), flush=True)
    if not summary["passed"]:
        raise SystemExit(1)


def figure(cases):
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for case in cases:
        with np.load(OUT / f"{case['name']}-1s.npz", allow_pickle=False) as data:
            hours = data["time_s"]/3600
            rise = data["outputs"][:, 1, 0]-case["ambient_c"]
            fraction = data["resistance_ohm"][:, 1]/data["resistance_ohm"][0, 1]-1
            label = f"{case['name']}: h={case['h']:g}, {case['ambient_c']:g}°C"
            axes[0].plot(hours, rise, label=label)
            axes[1].plot(hours, fraction*100, label=case["name"])
    axes[0].set(xlabel="Model time (h)", ylabel="Winding mean rise (K)",
                title="Prescribed-current thermal feedback")
    axes[1].set(xlabel="Model time (h)", ylabel="Resistance increase (%)",
                title="Self-heating feedback")
    for axis in axes:
        axis.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "endurance.png", dpi=160)
    fig.savefig(OUT / "endurance.svg")
    plt.close(fig)


if __name__ == "__main__":
    main()
