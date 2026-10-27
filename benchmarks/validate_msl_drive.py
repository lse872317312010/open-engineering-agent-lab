"""Fixed continuous drive/MSL cases, full derivative audit, and raw evidence."""

import csv
import gzip
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from msl_drive_adapter import LOG_COLUMNS, MSLDriveThermal
from msl_drive_reference import independent_rates, resistance

from oeal.backends.motulator import CONTROL_COLUMNS, run_drive
from oeal.energy import ENERGY_COLUMNS
from oeal.refined_thermal import CAPACITIES

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/msl-drive"
BASE = dict(energy_consistent=True, duration_s=.4, period_s=50e-6, bus_v=48.,
            step_time_s=.005, iq_reference_a=5., current_limit_a=6.,
            load_nm=1.5, pwm=False, delay=False, thermal_feedback=True,
            bandwidth_per_s=1000., tracking_rate_per_s=1000., rtol=1e-8,
            max_step_s=20e-6, seed=20261027)
CASES = [
    ("average-feedback", {}),
    ("average-frozen", dict(thermal_feedback=False)),
    ("pwm-feedback", dict(duration_s=.06, pwm=True, delay=True,
                          deadtime_s=1e-6, device_drop_v=.4, max_step_s=5e-6)),
    ("regeneration", dict(duration_s=.06, iq_reference_a=-2., load_nm=-2.,
                          max_step_s=10e-6)),
    ("average-fine", dict(max_step_s=10e-6)),
]
FINE_COLUMNS = ["time_s", "id_a", "iq_a", "speed_rad_s",
                "u_alpha_v", "u_beta_v", "i_alpha_a", "i_beta_a",
                "bus_v", "source_dc_a"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def column(data, columns, name):
    return data[:, columns.index(name)]


def csv_save(path, columns, data):
    with gzip.open(path, "wt", compresslevel=1) if path.suffix == ".gz" else path.open("w") as f:
        np.savetxt(f, data, delimiter=",", header=",".join(columns), comments="")


def legacy_probe():
    config = BASE | dict(duration_s=.004, step_time_s=.0005)
    script = """
import hashlib,json,numpy as np,sys
from pathlib import Path
from oeal.backends.motulator import run_drive
import oeal.backends.energy as energy_module
cfg=json.loads(sys.argv[1]); destination=Path(sys.argv[2])
result,controller=run_drive(cfg)
arrays=dict(control=np.asarray(controller.rows),energy=np.asarray(controller.energy_rows),
            time=result.mdl.t,current=result.mdl.machine.i_s_dq)
np.savez(destination,**arrays)
hashes={k:hashlib.sha256(v.tobytes()).hexdigest() for k,v in arrays.items()}
hashes["_source_file"]=str(Path(energy_module.__file__).resolve())
print(json.dumps(hashes))
"""
    old_source = ROOT / "outputs/msl-drive-base/src"
    assert old_source.is_dir()
    environment = dict(os.environ, PYTHONPATH=str(old_source))
    old = subprocess.check_output([sys.executable, "-c", script, json.dumps(config),
                                   str(OUT / "previous-native.npz")],
                                  env=environment, text=True).strip()
    new = subprocess.check_output([sys.executable, "-c", script, json.dumps(config),
                                   str(OUT / "current-native.npz")], text=True).strip()
    old_hashes, new_hashes = json.loads(old.splitlines()[-1]), json.loads(new.splitlines()[-1])
    old_file, new_file = old_hashes.pop("_source_file"), new_hashes.pop("_source_file")
    assert old_file == str(old_source / "oeal/backends/energy.py")
    assert new_file == str(ROOT / "src/oeal/backends/energy.py")
    assert old_hashes == new_hashes
    return dict(passed=True, baseline_commit="65acdc66d3ccdcdfcee933c3e82b67c2a549cad4",
                array_sha256=new_hashes, previous_source=old_file, current_source=new_file)


def simulate(config, provider=None):
    result, controller = run_drive(config, thermal_provider=provider)
    control = np.asarray(controller.rows)
    energy = np.asarray(controller.energy_rows)
    mask = result.mdl.t <= config["duration_s"]+1e-12
    machine = result.mdl.machine
    voltage, current = result.mdl.converter.u_c_ab, machine.i_s_ab
    fine = np.column_stack([
        result.mdl.t, machine.i_s_dq.real, machine.i_s_dq.imag, result.mdl.mechanics.w_M,
        voltage.real, voltage.imag, current.real, current.imag,
        result.mdl.converter.u_dc, result.mdl.converter.i_dc_int,
    ])[mask]
    assert len(control) == round(config["duration_s"]/config["period_s"])+1
    np.testing.assert_allclose(control[:, 0], energy[:, 0], atol=1e-14)
    assert abs(control[-1, 0]-config["duration_s"]) <= 1e-12
    return control, energy, fine


def energy_audit(control, energy):
    def get(n):
        return column(energy, ENERGY_COLUMNS, n)
    d = column(control, CONTROL_COLUMNS, "id_a")
    q = column(control, CONTROL_COLUMNS, "iq_a")
    w = column(control, CONTROL_COLUMNS, "motor_speed_rad_s")
    temperatures = np.column_stack([get(n) for n in
                                    ("winding_c", "core_c", "case_c", "junction_c",
                                     "board_c", "sink_c")])
    magnetic = .75*.0008*(d*d+q*q)
    kinetic = .5*.002*w*w
    thermal = (temperatures-25.) @ CAPACITIES
    stored = magnetic+kinetic+thermal
    local = get("source_j")-get("load_work_j")-(stored-stored[0])-get("ambient_j")
    heat = sum(get(n) for n in ("copper_j", "conduction_j", "auxiliary_device_j",
                                "rotor_friction_j"))
    thermal_residual = heat-thermal-get("ambient_j")
    limit = 2e-5+2e-4*float(max(get("source_abs_j")))
    return dict(local_peak_j=float(max(abs(local))),
                thermal_peak_j=float(max(abs(thermal_residual))),
                local_limit_j=limit), local, thermal_residual


def audit_rhs(path):
    max_error = np.zeros(8)
    power_error = 0.
    accepted_times, count = [], 0
    fault_detected = False

    def process(batch):
        nonlocal count, power_error, fault_detected
        a = np.asarray(batch, dtype=float)
        expected = independent_rates(a[:, 2:8], a[:, 8:14])
        max_error[:] = np.maximum(max_error, np.max(abs(a[:, 16:24]-expected), axis=0))
        power_error = max(power_error, float(max(abs(
            a[:, 16:22] @ CAPACITIES+a[:, 23]-a[:, 8:14].sum(axis=1)))))
        accepted_times.extend(a[a[:, 0] == 1, 1].tolist())
        count += len(a)
        if not fault_detected and np.max(a[:, 8]) > .1:
            k = int(np.argmax(a[:, 8]))
            wrong_heat = a[k:k+1, 8:14].copy()
            wrong_heat[0, 3] += wrong_heat[0, 0]
            wrong_heat[0, 0] = 0.
            wrong = independent_rates(a[k:k+1, 2:8], wrong_heat)
            fault_detected = bool(np.max(abs(a[k:k+1, 16:22]-wrong[:, :6])) > 2e-7)
            fault_row = a[k:k+1].copy()
            fault_row[:, 8:14] = wrong_heat
            csv_save(path.with_name("fault-misrouted-copper.csv"), LOG_COLUMNS, fault_row)

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
    assert all(np.diff(accepted_times) > 0)
    passed = bool(max(max_error[:6]) <= 2e-7 and max_error[6] <= 1e-8
                  and max_error[7] <= 2e-7 and power_error <= 1e-8 and fault_detected)
    return dict(passed=passed, total_rows=count, checkpoints=len(accepted_times),
                first_checkpoint_s=accepted_times[0], last_checkpoint_s=accepted_times[-1],
                derivative_errors=max_error.tolist(), power_identity_w=power_error,
                misrouted_copper_fault_detected=fault_detected)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    compatibility = legacy_probe()
    reports, kept = [], {}
    for name, changes in CASES:
        config = BASE | changes
        target = OUT / name
        target.mkdir(exist_ok=True)
        (target / "input.json").write_text(json.dumps(config, indent=2))
        provider = MSLDriveThermal(target / "rhs.csv.gz", config["duration_s"])
        try:
            control, energy, fine = simulate(config, provider)
            metadata = provider.describe()
        finally:
            provider.close()
        rhs_audit = audit_rhs(target / "rhs.csv.gz")
        csv_save(target / "control.csv", CONTROL_COLUMNS, control)
        csv_save(target / "energy.csv", ENERGY_COLUMNS, energy)
        csv_save(target / "waveforms.csv.gz", FINE_COLUMNS, fine)
        accounting, local, thermal = energy_audit(control, energy)
        if name != "average-fine":
            native_control, native_energy, native_fine = simulate(config)
            csv_save(target / "native-control.csv", CONTROL_COLUMNS, native_control)
            csv_save(target / "native-energy.csv", ENERGY_COLUMNS, native_energy)
            csv_save(target / "native-waveforms.csv.gz", FINE_COLUMNS, native_fine)
            np.testing.assert_allclose(control[:, 0], native_control[:, 0], atol=1e-14)
            # Resolve physical quantities by their declared names.
            temperature_error = max(float(np.max(abs(
                column(energy, ENERGY_COLUMNS, n)-column(native_energy, ENERGY_COLUMNS, n))))
                for n in ("winding_c", "core_c", "case_c", "junction_c", "board_c", "sink_c"))
            paired_errors = {n: float(np.max(abs(column(control, CONTROL_COLUMNS, n)
                                                 - column(native_control, CONTROL_COLUMNS, n))))
                             for n in ("id_a", "iq_a", "motor_speed_rad_s",
                                       "vd_command_v", "vq_command_v")}
        else:
            previous_control, previous_energy = kept["average-feedback"]
            temperature_error = max(float(np.max(abs(
                column(energy, ENERGY_COLUMNS, n)-column(previous_energy, ENERGY_COLUMNS, n))))
                for n in ("winding_c", "core_c", "case_c", "junction_c", "board_c", "sink_c"))
            paired_errors = {n: float(np.max(abs(column(control, CONTROL_COLUMNS, n)
                                                 - column(previous_control, CONTROL_COLUMNS, n))))
                             for n in ("id_a", "iq_a", "motor_speed_rad_s",
                                       "vd_command_v", "vq_command_v")}
        d = column(control, CONTROL_COLUMNS, "id_a")
        q = column(control, CONTROL_COLUMNS, "iq_a")
        winding = column(energy, ENERGY_COLUMNS, "winding_c")
        copper = column(control, CONTROL_COLUMNS, "copper_w")
        valid = np.hypot(d, q) > .1
        inferred = copper[valid]/(1.5*(d[valid]**2+q[valid]**2))
        expected_r = resistance(winding[valid], config["thermal_feedback"])
        resistance_error = float(max(abs(inferred-expected_r)))
        peak = float(max(np.hypot(fine[:, 1], fine[:, 2])))
        tail = float(np.mean(abs(q[-max(1, len(q)//10):]-config["iq_reference_a"])))
        missing = energy.copy()
        missing[:, ENERGY_COLUMNS.index("source_j")] -= column(
            energy, ENERGY_COLUMNS, "auxiliary_device_j")
        fault, _, _ = energy_audit(control, missing)
        missing_fault = fault["local_peak_j"] > fault["local_limit_j"]
        frozen_fault = (bool(float(max(abs(inferred-.3))) > 1e-10)
                        if config["thermal_feedback"] else None)
        csv_save(target / "fault-missing-dc-energy.csv", ENERGY_COLUMNS, missing)
        if config["thermal_feedback"]:
            csv_save(target / "fault-frozen-resistance.csv",
                     ["time_s", "corrupted_r_ohm", "independent_expected_r_ohm"],
                     np.column_stack([control[valid, 0], np.full(sum(valid), .3), expected_r]))
        min_source = float(min(column(energy, ENERGY_COLUMNS, "source_w")))
        passed = bool(rhs_audit["passed"] and metadata["projection_temperature_k"] <= 1e-10
                      and metadata["projection_energy_j"] <= 1e-8
                      and temperature_error <= 2e-7 and max(paired_errors.values()) <= 2e-5
                      and accounting["local_peak_j"] <= accounting["local_limit_j"]
                      and accounting["thermal_peak_j"] <= 1e-7
                      and resistance_error <= 1e-10 and peak <= 6.5 and tail <= .1
                      and missing_fault and frozen_fault is not False
                      and (name != "regeneration" or min_source < -.1))
        if name == "average-feedback":
            passed = passed and max(inferred)-.3 >= 1e-5
        if name == "average-frozen":
            passed = passed and max(abs(inferred-.3)) <= 1e-12
        kept[name] = (control, energy)
        columns = ["time_s", "iq_a", "id_a", "winding_c", "junction_c",
                   "copper_w", "device_w", "actual_r_ohm", "source_w",
                   "source_j", "copper_j", "ambient_j", "local_balance_j", "thermal_balance_j",
                   "core_c", "case_c", "board_c", "sink_c", "native_iq_a", "native_winding_c",
                   "vd_command_v", "vq_command_v", "voltage_limited", "current_limited", "enabled"]
        all_r = resistance(winding, config["thermal_feedback"])
        all_r[valid] = inferred
        compare_control = native_control if name != "average-fine" else previous_control
        compare_energy = native_energy if name != "average-fine" else previous_energy
        preview = np.column_stack([
            control[:, 0], q, d, winding, column(energy, ENERGY_COLUMNS, "junction_c"), copper,
            column(energy, ENERGY_COLUMNS, "conduction_w")
            + column(energy, ENERGY_COLUMNS, "auxiliary_device_w"), all_r,
            column(energy, ENERGY_COLUMNS, "source_w"), column(energy, ENERGY_COLUMNS, "source_j"),
            column(energy, ENERGY_COLUMNS, "copper_j"),
            column(energy, ENERGY_COLUMNS, "ambient_j"), local, thermal,
            *[column(energy, ENERGY_COLUMNS, n) for n in ("core_c", "case_c", "board_c", "sink_c")],
            column(compare_control, CONTROL_COLUMNS, "iq_a"),
            column(compare_energy, ENERGY_COLUMNS, "winding_c"),
            *[column(control, CONTROL_COLUMNS, n) for n in
              ("vd_command_v", "vq_command_v", "voltage_limited", "current_limited", "enabled")],
        ])
        csv_save(target / "coupling.csv", columns, preview)
        stride = max(1, len(control)//240)
        indices = sorted(set(range(0, len(control), stride)) | {len(control)-1})
        case = dict(id=name, passed=bool(passed), config=config, rows=len(control),
                    duration_s=config["duration_s"], rhs_audit=rhs_audit, provider=metadata,
                    temperature_difference_k=temperature_error, paired_errors=paired_errors,
                    resistance_error_ohm=resistance_error,
                    max_resistance_ohm=float(max(inferred)), min_source_w=min_source,
                    current_peak_a=peak, iq_tail_error_a=tail, **accounting,
                    missing_dc_branch_fault_detected=bool(missing_fault),
                    frozen_resistance_fault_detected=frozen_fault,
                    columns=columns, samples=preview[indices].tolist())
        reports.append(case)
        print("msl-drive-case: "+json.dumps({k: v for k, v in case.items()
                                            if k not in {"samples", "columns"}}), flush=True)
    feedback = column(kept["average-feedback"][1], ENERGY_COLUMNS, "copper_j")[-1]
    frozen = column(kept["average-frozen"][1], ENERGY_COLUMNS, "copper_j")[-1]
    causal_difference = float(feedback-frozen)
    metadata = dict(commit=subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                   text=True).strip(),
                    build=json.loads(
                        (ROOT / "outputs/msl-thermal/build-provenance.json").read_text()),
                    source_sha256={p: sha(ROOT / p) for p in
                                   ("src/oeal/backends/energy.py", "src/oeal/backends/motulator.py",
                                    "benchmarks/msl_drive_adapter.py")})
    report = dict(passed=all(c["passed"] for c in reports) and abs(causal_difference) >= 1e-5,
                  cases=reports, compatibility=compatibility,
                  copper_feedback_minus_frozen_j=causal_difference, metadata=metadata,
                  evidence_level="model_simulated", current_profile_count=7,
                  scope="short coupled motulator/MSL continuous integration, no robot or hardware")
    (OUT / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("msl-drive-summary: "+json.dumps({k: v for k, v in report.items() if k != "cases"}),
          flush=True)
    assert report["passed"], "predeclared continuous coupling gate failed"


if __name__ == "__main__":
    main()
