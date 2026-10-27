"""Actual-loss nonlinear MSL coupling; every serialized RHS and control point audited."""
import csv
import gzip
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import validate_msl_drive as old
from msl_cooling_drive_adapter import LOG_COLUMNS, MSLCoolingDrive
from msl_cooling_drive_reference import BASE, CASES, PythonCooling, gc_at, rates
from msl_cooling_reference import SIGMA
from msl_drive_reference import resistance

from oeal.backends.motulator import CONTROL_COLUMNS
from oeal.energy import ENERGY_COLUMNS, TEMPERATURES
from oeal.refined_thermal import CAPACITIES

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/msl-cooling-drive"


def col(a, names, n):
    return a[:, names.index(n)]


def save(path, names, a):
    old.csv_save(path, names, a)


def audit_rhs(path, area, varying):
    maximum = np.zeros(11)
    power_error = state_sum = gc_error = 0.
    accepted, count, bad_route = [], 0, False

    def process(batch):
        nonlocal power_error, state_sum, gc_error, count, bad_route
        a = np.asarray(batch, dtype=float)
        assert np.all(np.isfinite(a))
        expected = rates(a[:, 2:8], a[:, 8:14], a[:, 19], area)
        maximum[:] = np.maximum(maximum, np.max(abs(a[:, 20:31]-expected), axis=0))
        power_error = max(power_error, float(np.max(abs(
            a[:, 20:26] @ CAPACITIES+a[:, 27]-a[:, 8:14].sum(axis=1)))))
        state_sum = max(state_sum, float(np.max(abs(a[:, 16:19].sum(axis=1)-a[:, 15]))))
        gc_error = max(gc_error, float(np.max(abs(a[:, 19]-gc_at(a[:, 1], varying)))))
        accepted.extend(a[a[:, 0] == 1].tolist())
        count += len(a)
        if not bad_route and np.max(a[:, 8]) > .1:
            k = int(np.argmax(a[:, 8]))
            wrong = a[k:k+1, 8:14].copy()
            wrong[0, 3] += wrong[0, 0]
            wrong[0, 0] = 0.
            bad_route = bool(np.max(abs(
                rates(a[k:k+1, 2:8], wrong, a[k:k+1, 19], area)[:, :6]
                - a[k:k+1, 20:26])) > 2e-7)
            save(path.with_name("fault-misrouted-copper.csv"), LOG_COLUMNS, a[k:k+1])
            save(path.with_name("fault-misrouted-heat.csv"),
                 [f"heat_{i}_w" for i in range(6)], wrong)

    with gzip.open(path, "rt") as f:
        reader = csv.reader(f)
        assert next(reader) == LOG_COLUMNS
        batch = []
        for row in reader:
            batch.append(row)
            if len(batch) == 20000:
                process(batch)
                batch = []
        if batch:
            process(batch)
    accepted = np.asarray(accepted)
    assert np.all(np.diff(accepted[:, 1]) > 0)
    passed = bool(max(maximum[:6]) <= 2e-7 and maximum[6] <= 1e-8
                  and max(maximum[7:]) <= 2e-7 and power_error <= 1e-8
                  and state_sum <= 1e-8 and gc_error <= 1e-14 and bad_route)
    return dict(passed=passed, rows=count, checkpoints=len(accepted),
                derivative_errors=maximum.tolist(), power_error_w=power_error,
                branch_sum_j=state_sum, gc_input_error=gc_error,
                misrouted_copper_fault_detected=bad_route), accepted


def energy_audit(control, energy):
    def get(n):
        return col(energy, ENERGY_COLUMNS, n)
    d, q = [col(control, CONTROL_COLUMNS, n) for n in ("id_a", "iq_a")]
    w = col(control, CONTROL_COLUMNS, "motor_speed_rad_s")
    t = np.column_stack([get(n) for n in TEMPERATURES])
    thermal = (t-t[0]) @ CAPACITIES
    magnetic = .75*.0008*(d*d+q*q)
    kinetic = .5*.002*w*w
    stored = magnetic+kinetic+thermal
    local = get("source_j")-get("load_work_j")-(stored-stored[0])-get("ambient_j")
    heat = sum(get(n) for n in ("copper_j", "conduction_j", "auxiliary_device_j",
                                "rotor_friction_j"))
    residual = heat-thermal-get("ambient_j")
    limit = 2e-5+2e-4*float(max(get("source_abs_j")))
    return dict(local_peak_j=float(max(abs(local))), local_limit_j=limit,
                thermal_peak_j=float(max(abs(residual)))), local, residual


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    old.OUT = OUT
    compatibility = old.legacy_probe()
    compatibility["baseline_commit"] = "c4499fb66cfed99d289de9f7f36f895b319c5c62"
    reports, kept = [], {}
    for name, changes, area, varying in CASES:
        config = BASE | changes
        target = OUT / name
        target.mkdir(exist_ok=True)
        (target / "input.json").write_text(json.dumps(dict(
            drive=config, area_m2=area, varying_gc=varying, initial_temperatures_c=[80.]*6),
            indent=2))
        provider = MSLCoolingDrive(target / "rhs.csv.gz", config["duration_s"], area, varying)
        try:
            control, energy, fine = old.simulate(config, provider)
            metadata = provider.describe()
        finally:
            provider.close()
        audit, accepted = audit_rhs(target / "rhs.csv.gz", area, varying)
        assert audit["rows"] == metadata["rhs_calls"]+metadata["accepted_checkpoints"]
        assert len(accepted) == len(control) == metadata["accepted_checkpoints"]
        np.testing.assert_allclose(accepted[:, 1], control[:, 0], atol=1e-14, rtol=0)
        reference = PythonCooling(area, varying)
        paired_c, paired_e, paired_f = old.simulate(config, reference)
        save(target / "control.csv", CONTROL_COLUMNS, control)
        save(target / "energy.csv", ENERGY_COLUMNS, energy)
        save(target / "waveforms.csv.gz", old.FINE_COLUMNS, fine)
        save(target / "reference-control.csv", CONTROL_COLUMNS, paired_c)
        save(target / "reference-energy.csv", ENERGY_COLUMNS, paired_e)
        save(target / "reference-waveforms.csv.gz", old.FINE_COLUMNS, paired_f)
        temp_error = max(float(max(abs(col(energy, ENERGY_COLUMNS, n)
                                      -col(paired_e, ENERGY_COLUMNS, n)))) for n in TEMPERATURES)
        paired_errors = {n: float(max(abs(col(control, CONTROL_COLUMNS, n)
                                         -col(paired_c, CONTROL_COLUMNS, n))))
                         for n in ("id_a", "iq_a", "motor_speed_rad_s",
                                   "vd_command_v", "vq_command_v")}
        accounting, local, thermal = energy_audit(control, energy)
        def get(n, data=energy):
            return col(data, ENERGY_COLUMNS, n)
        d, q = [col(control, CONTROL_COLUMNS, n) for n in ("id_a", "iq_a")]
        winding = get("winding_c")
        valid = np.hypot(d, q) > .1
        inferred = col(control, CONTROL_COLUMNS, "copper_w")[valid]/(
            1.5*(d[valid]**2+q[valid]**2))
        expected = resistance(winding[valid], config["thermal_feedback"])
        r_error = float(max(abs(inferred-expected)))
        all_r = resistance(winding, config["thermal_feedback"])
        all_r[valid] = inferred
        branch_error = float(np.max(abs(accepted[:, 16:19]-np.asarray(reference.accepted)[:, 1:4])))
        ambient_error = float(max(abs(get("ambient_j")-col(paired_e, ENERGY_COLUMNS, "ambient_j"))))
        heat = sum(get(n) for n in ("copper_j", "conduction_j", "auxiliary_device_j",
                                    "rotor_friction_j"))
        np.testing.assert_allclose(accepted[:, 14], heat, atol=1e-8, rtol=0)
        np.testing.assert_allclose(accepted[:, 15], get("ambient_j"), atol=1e-8, rtol=0)
        np.testing.assert_allclose(accepted[:, 8], col(control, CONTROL_COLUMNS, "copper_w"),
                                   atol=1e-8, rtol=0)
        # Corruption copies test the existing gates, never change actual trajectories.
        omitted = heat-(np.column_stack([get(n) for n in TEMPERATURES])-80) @ CAPACITIES \
                  -accepted[:, 16:18].sum(axis=1)
        wrong_celsius = area*SIGMA*(accepted[:, 7]**4-25**4)
        missing_radiation = bool(max(abs(omitted)) > 1e-7) if area else None
        celsius_fault = bool(max(abs(accepted[:, 30]-wrong_celsius)) > 2e-7) if area else None
        missing_dc = energy.copy()
        missing_dc[:, ENERGY_COLUMNS.index("source_j")] -= get("auxiliary_device_j")
        wrong, _, _ = energy_audit(control, missing_dc)
        missing_dc_fault = wrong["local_peak_j"] > wrong["local_limit_j"]
        frozen_fault = bool(max(abs(inferred-.3)) > 1e-10) if config["thermal_feedback"] else None
        save(target / "fault-missing-dc.csv", ENERGY_COLUMNS, missing_dc)
        save(target / "radiation-faults.csv",
             ["time_s", "actual_radiation_w", "wrong_celsius_w", "omitted_balance_j"],
             np.column_stack([control[:, 0], accepted[:, 30], wrong_celsius, omitted]))
        save(target / "resistance-check.csv", ["time_s", "actual_r_ohm", "expected_r_ohm",
                                               "wrong_frozen_r_ohm"],
             np.column_stack([control[valid, 0], inferred, expected, inferred*0+.3]))
        peak = float(max(np.hypot(fine[:, 1], fine[:, 2])))
        tail = float(np.mean(abs(q[-max(1, len(q)//10):]-config["iq_reference_a"])))
        min_source = float(min(get("source_w")))
        passed = bool(audit["passed"] and temp_error <= 2e-7
                      and max(paired_errors.values()) <= 2e-5 and branch_error <= 1e-7
                      and ambient_error <= 1e-7 and r_error <= 1e-10
                      and accounting["local_peak_j"] <= accounting["local_limit_j"]
                      and accounting["thermal_peak_j"] <= 1e-7 and peak <= 6.5 and tail <= .1
                      and missing_radiation is not False and celsius_fault is not False
                      and missing_dc_fault and frozen_fault is not False
                      and (min(accepted[:, 30]) > 1 if area else np.max(abs(accepted[:, 30])) == 0)
                      and (name != "regeneration" or min_source < -.1))
        if not config["thermal_feedback"]:
            passed = passed and max(abs(inferred-.3)) <= 1e-12
        columns = ["time_s", "iq_a", "id_a", *TEMPERATURES, "actual_r_ohm", "gc_w_k",
                   "case_out_j", "convection_out_j", "radiation_out_j",
                   "case_w", "convection_w", "radiation_w", "source_w",
                   "copper_w", "device_w", "local_balance_j", "thermal_balance_j",
                   "reference_iq_a", "reference_winding_c", "voltage_limited", "current_limited",
                   "enabled"]
        preview = np.column_stack([
            control[:, 0], q, d, *[get(n) for n in TEMPERATURES], all_r, accepted[:, 19],
            accepted[:, 16:19], accepted[:, 28:31], get("source_w"),
            col(control, CONTROL_COLUMNS, "copper_w"),
            get("conduction_w")+get("auxiliary_device_w"), local, thermal,
            col(paired_c, CONTROL_COLUMNS, "iq_a"), col(paired_e, ENERGY_COLUMNS, "winding_c"),
            *[col(control, CONTROL_COLUMNS, n) for n in
              ("voltage_limited", "current_limited", "enabled")],
        ])
        save(target / "coupling.csv", columns, preview)
        save(target / "reference-branches.csv",
             ["time_s", "case_out_j", "convection_out_j", "radiation_out_j"],
             np.asarray(reference.accepted))
        kept[name] = (control, energy)
        stride = max(1, len(control)//240)
        indices = sorted(set(range(0, len(control), stride)) | {len(control)-1})
        case = dict(id=name, passed=bool(passed), config=config, area_m2=area, varying_gc=varying,
                    rows=len(control), duration_s=config["duration_s"], rhs_audit=audit,
                    provider=metadata, temperature_difference_k=temp_error,
                    paired_errors=paired_errors, branch_difference_j=branch_error,
                    ambient_difference_j=ambient_error, resistance_error_ohm=r_error,
                    current_peak_a=peak, iq_tail_error_a=tail, min_source_w=min_source,
                    missing_radiation_fault_detected=missing_radiation,
                    celsius_fault_detected=celsius_fault,
                    missing_dc_fault_detected=missing_dc_fault,
                    frozen_resistance_fault_detected=frozen_fault, **accounting,
                    columns=columns, samples=preview[indices].tolist())
        reports.append(case)
        print("cooling-drive-case: "+json.dumps({k:v for k,v in case.items()
                                               if k not in {"samples", "columns"}}), flush=True)
    comparisons = {}
    for n, unit in [*[(n, "k") for n in TEMPERATURES],
                    *[(n, "si") for n in ("id_a", "iq_a", "motor_speed_rad_s",
                                          "vd_command_v", "vq_command_v")]]:
        k = 1 if unit == "k" else 0
        names = ENERGY_COLUMNS if k else CONTROL_COLUMNS
        comparisons[n] = float(max(abs(col(kept["radiation-feedback"][k], names, n)
                                      -col(kept["radiation-fine"][k], names, n))))
    causal = float(col(kept["radiation-feedback"][1], ENERGY_COLUMNS, "copper_j")[-1]
                   -col(kept["radiation-frozen"][1], ENERGY_COLUMNS, "copper_j")[-1])
    fine_pass = all(v <= (2e-7 if n in TEMPERATURES else 2e-5) for n,v in comparisons.items())
    source_paths = ("src/oeal/backends/energy.py", "src/oeal/backends/motulator.py",
                    "benchmarks/msl_cooling_drive_adapter.py")
    summary = dict(passed=all(c["passed"] for c in reports) and fine_pass and abs(causal) >= 1e-5,
                   cases=reports, fine_comparisons=comparisons,
                   copper_feedback_minus_frozen_j=causal, compatibility=compatibility,
                   evidence_level="model_simulated", current_profile_count=7,
                   scope="0.02-0.1s hot-start actual-drive coupling; no endurance or hardware",
                   metadata=dict(commit=subprocess.check_output(
                       ["git", "rev-parse", "HEAD"], text=True).strip(),
                       build=json.loads(
                           (ROOT / "outputs/msl-cooling/build-provenance.json").read_text()),
                       source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
                                      for p in source_paths}))
    (OUT / "validation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print("cooling-drive-summary: "+json.dumps({k:v for k,v in summary.items() if k != "cases"}),
          flush=True)
    assert summary["passed"], "fixed nonlinear drive cooling gate failed"


if __name__ == "__main__":
    main()
