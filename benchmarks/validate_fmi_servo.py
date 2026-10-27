"""Validate the shared FMI host against separate plant and sampled PI equations."""

import copy
import gzip
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
from fmi_servo_reference import command, rhs, stored
from joint_fmi_reference import initial
from scipy.integrate import solve_ivp
from validate_configurable_fmi import OUT as PLANT_OUT
from validate_configurable_fmi import build

from oeal.backends import fmi_joint, fmi_servo
from oeal.backends.fmi_servo import load_asset
from oeal.experiments import run_experiment
from oeal.ir import document_hash
from oeal.studies import export_streams, model_parameters, recompute, resolved_settings
from oeal.study_tools import StudyTools

ROOT = Path(__file__).parents[1]
OUT = ROOT / "outputs/fmi-servo"


def specs():
    base = json.loads((ROOT / "examples/studies/fmi_servo_v2.json").read_text())
    result = {}
    for name in ("nominal", "reverse", "loaded-board", "mismatch", "mismatch-fine",
                 "unreachable"):
        item = copy.deepcopy(base)
        item["id"] = name
        if name == "reverse":
            item["settings"]["position_step_rad"]["value"] = -.02
        if name == "loaded-board":
            item["settings"]["load_nm"]["value"] = .1
            item["settings"]["board_power_w"]["value"] = 20.
        if name.startswith("mismatch"):
            item["model"]["parameters"] = {
                name: dict(value=value, unit=unit) for name, value, unit in [
                    ("stator_resistance_ohm", .36, "ohm"), ("d_inductance_h", .00064, "H"),
                    ("q_inductance_h", .00096, "H"), ("flux_linkage_wb", .027, "Wb"),
                    ("inertia_kg_m2", .0001, "kg*m^2"),
                    ("viscous_friction_nms", .00002, "N*m*s/rad"),
                ]
            }
        if name == "mismatch-fine":
            item["settings"]["integration_step_s"]["value"] = 2.5e-6
        if name == "unreachable":
            item["settings"]["vdc_v"]["value"] = 2.
            item["settings"]["position_step_rad"]["value"] = .2
        result[name] = item
    return result


def independent(document, result):
    s = resolved_settings(document)
    p = model_parameters(document["model"])
    rows = np.asarray(result["streams"]["control"]["samples"])
    waves = np.asarray(result["streams"]["waveforms"]["samples"])
    count = (len(waves)-1)//(len(rows)-1)
    reference = [initial()]
    x, integral, previous = initial(), np.zeros(2), np.zeros(2)
    voltage_error = 0.
    for tick, row in enumerate(rows[:-1]):
        applied, integral, previous = command(s, x, tick, integral, previous)
        voltage_error = max(voltage_error, float(np.max(np.abs(applied-row[14:16]))))
        t, end = row[0], rows[tick+1, 0]
        solution = solve_ivp(rhs, (t, end), x, args=(row[14:18], p), method="DOP853",
                             rtol=2e-12, atol=2e-13, dense_output=True)
        assert solution.success
        points = waves[tick*count+1:(tick+1)*count+1, 0]
        values = solution.sol(points).T
        reference.extend(values)
        x = values[-1]
    reference = np.asarray(reference)
    errors = np.max(np.abs(waves[:, 1:10]-reference[:, :9]), axis=0)
    energy = stored(waves[:, 1:13], p)
    residual = energy-energy[0]-waves[:, 10]+waves[:, 11]+waves[:, 12]
    assert np.max(np.abs(residual)) <= 2e-6
    assert np.max(errors) <= 2e-5
    assert voltage_error <= 2e-5
    return reference, errors, voltage_error


def legacy_feedback(document):
    s = resolved_settings(document)
    p = model_parameters(document["model"])

    def original_command(s, x, tick, state):
        q, velocity = fmi_servo.reference(tick*s["control_period_s"], s)
        effort = (s["outer_kp_nm_per_rad"]*(q-x[4])
                  + s["outer_kd_nms_per_rad"]*(velocity-x[5]))
        return fmi_servo.bounded_voltage(fmi_joint.control(
            dict(s, id_reference_a=0., iq_reference_a=effort/3.15, step_time_s=0.),
            x, tick, state), s)

    rows, waves, context = fmi_joint.run(
        s, load_asset(OUT), guid=fmi_servo.GUID, ident=fmi_servo.IDENT,
        command=original_command, motor_values=[p[k] for k in fmi_servo.PARAMETERS])
    actual = np.asarray(rows)
    targets = s["position_step_rad"]*np.clip(
        (actual[:, 0]-s["position_start_s"])/s["position_ramp_s"], 0, 1)
    error = actual[:, 5]-targets
    metrics = dict(position_peak_error_rad=float(np.max(np.abs(error))),
                   position_tail_error_rad=float(np.mean(np.abs(error[
                       actual[:, 0] >= .9*s["duration_s"]]))))
    peak = np.asarray(waves)
    metrics["current_peak_a"] = float(np.max(np.hypot(peak[:, 1], peak[:, 2])))
    metrics["shaft_torque_peak_nm"] = float(np.max(np.abs(peak[:, 13])))
    balance = stored(peak[:, 1:13], p)-peak[:, 10]+peak[:, 11]+peak[:, 12]
    metrics["energy_balance_abs_j"] = float(np.max(np.abs(balance)))
    passed = all(metrics[name] <= goal["value"] for name, goal in document["acceptance"].items())
    with gzip.open(OUT / "legacy-load-velocity.json.gz", "wt") as handle:
        json.dump(dict(input=document, parameters=p, rows=rows, waves=waves, context=context,
                       metrics=metrics, passed=passed), handle, allow_nan=False)
    record = dict(passed=passed, metrics=metrics,
                  samples=actual[::10, [0, 5]].tolist(),
                  scope="Original A load-side derivative; unchanged gains and goals")
    print("legacy-feedback-A: "+json.dumps({k: value for k, value in record.items()
                                           if k != "samples"}))
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    _, metadata = build()
    shutil.copyfile(PLANT_OUT / "oeal-servo.fmu", OUT / "oeal-servo.fmu")
    legacy = legacy_feedback(specs()["nominal"])
    cases = []
    trajectories = {}
    checks = []
    for name, document in specs().items():
        result = run_experiment(document, OUT)
        directory = OUT / name
        directory.mkdir(exist_ok=True)
        (directory / "input.json").write_text(json.dumps(document, indent=2))
        (directory / "result.json").write_text(json.dumps(result, allow_nan=False))
        export_streams(result, directory / "csv")
        reference, errors, voltage_error = independent(document, result)
        rows = np.asarray(result["streams"]["control"]["samples"])
        waves = np.asarray(result["streams"]["waveforms"]["samples"])
        count = (len(waves)-1)//(len(rows)-1)
        x = rows[:, 1:13]
        p = model_parameters(document["model"])
        residual = stored(x, p)-x[:, 9]+x[:, 10]+x[:, 11]
        joint = np.asarray(result["streams"]["joint"]["samples"])
        trajectories[name] = joint[:, 1].copy()
        columns = [*result["streams"]["control"]["columns"],
                   *["reference_"+n for n in result["streams"]["control"]["columns"][1:10]],
                   "balance_j", "reference_rad", "reference_speed_rad_s"]
        data = np.column_stack([rows, reference[::count, :9], residual, joint[:, 3:5]])
        np.savetxt(OUT / (name+".csv"), data, delimiter=",", header=",".join(columns), comments="")
        expected = name != "unreachable"
        assert result["numeric_passed"] and result["goal_passed"] == expected
        case = dict(id=name, passed=result["goal_passed"], expected_passed=expected,
                    physical_parameters=p,
                    nominal_parameters=result["context"]["nominal_parameters"],
                    metrics=result["metrics"], max_state_error=float(max(errors)),
                    state_errors=errors.tolist(), voltage_error_v=voltage_error,
                    peak_balance_j=result["metrics"]["energy_balance_abs_j"],
                    columns=columns, samples=data[::10].tolist(), rows=len(rows),
                    waveform_rows=len(waves), raw_sha256=result["raw_sha256"],
                    limited_ticks=int(np.sum(rows[:-1, -2])))
        cases.append(case)
        print("fmi-servo-case: " + json.dumps({k: v for k, v in case.items()
                                             if k not in {"samples", "columns"}}))
        if name == "nominal":
            repeated = run_experiment(document, OUT)
            assert repeated["raw_sha256"] == result["raw_sha256"]
            checks.append("bitwise raw stream replay")
            subprocess.run([sys.executable, "-m", "oeal", "run-experiment",
                            str(directory / "input.json"), "--assets-root", str(OUT),
                            "--output", str(OUT / "cli.json"),
                            "--csv-dir", str(OUT / "cli-csv")], check=True)
            cli = json.loads((OUT / "cli.json").read_text())
            assert cli["raw_sha256"] == result["raw_sha256"]
            checks.append("CLI/API shared raw hash and CSV")
            tools = StudyTools(document, OUT / "ledger", OUT)
            trusted = tools.run_experiment(document)
            trusted["metrics"] = {"current_tail_error_a": -999}
            assert tools.verify_change(document, trusted)["passed"]
            checks.append("protected tools ignore forged metrics")
            trusted["streams"]["waveforms"]["samples"][10][1] += .1
            trusted["raw_sha256"] = document_hash(trusted["streams"])
            try:
                tools.verify_change(document, trusted)
            except ValueError:
                checks.append("protected tools reject rehashed raw tampering")
            else:
                raise AssertionError("forged wave accepted")
            for kind in ("reference", "voltage", "endpoint", "binary context",
                         "position target", "actual parameters", "nominal parameters"):
                altered = copy.deepcopy(result)
                if kind == "reference":
                    altered["streams"]["control"]["samples"][100][19] += .1
                elif kind == "voltage":
                    altered["streams"]["control"]["samples"][100][15] += .1
                elif kind == "endpoint":
                    altered["streams"]["waveforms"]["samples"].pop()
                elif kind == "position target":
                    altered["streams"]["joint"]["samples"][250][3] += .001
                elif kind == "actual parameters":
                    altered["context"]["physical_parameters"]["inertia_kg_m2"] *= 2
                elif kind == "nominal parameters":
                    altered["context"]["nominal_parameters"]["flux_linkage_wb"] *= .9
                else:
                    altered["context"]["fmi_asset_hashes"]["binary_sha256"] = "0"*64
                altered["raw_sha256"] = document_hash(altered["streams"])
                try:
                    recompute(document, altered)
                except ValueError:
                    checks.append("independent audit rejects "+kind)
                else:
                    raise AssertionError("forged input accepted: "+kind)
    with zipfile.ZipFile(OUT / "oeal-servo.fmu") as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    for name, old, new in (("GUID", b"000000000020", b"000000000099"),
                            ("port unit", b'unit="A"', b'unit="V"')):
        changed = OUT / ("bad-"+name.replace(" ", "-"))
        changed.mkdir(exist_ok=True)
        with zipfile.ZipFile(changed / "oeal-servo.fmu", "w") as archive:
            for path, content in members.items():
                if path == "modelDescription.xml":
                    content = content.replace(old, new, 1)
                archive.writestr(path, content)
        try:
            load_asset(changed)
        except ValueError:
            checks.append("asset rejects "+name)
        else:
            raise AssertionError("forged descriptor accepted")
    difference = float(np.max(np.abs(trajectories["mismatch"]-trajectories["mismatch-fine"])))
    assert difference <= 1e-5
    checks.append("fixed common-time 5/2.5 us position agreement")
    report = dict(passed=True, legacy_feedback=legacy,
                  position_step_difference_rad=difference, cases=cases,
                  boundary_checks=checks, metadata=metadata,
                  evidence_level="model_simulated",
                  scope="configurable motor and external 20kHz position/current FMI servo")
    (OUT / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("fmi-servo-summary: " + json.dumps(dict(
        passed=True, position_step_difference_rad=difference, checks=checks)))


if __name__ == "__main__":
    main()
