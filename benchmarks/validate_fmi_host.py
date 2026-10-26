"""Validate the shared FMI host against separate plant and sampled PI equations."""

import copy
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
from fmi_host_reference import command, stored
from joint_fmi_reference import initial, rhs
from scipy.integrate import solve_ivp
from validate_joint_fmi import OUT as PLANT_OUT
from validate_joint_fmi import build

from oeal.backends.fmi_joint import load_asset
from oeal.experiments import run_experiment
from oeal.ir import document_hash
from oeal.studies import export_streams, recompute, resolved_settings
from oeal.study_tools import StudyTools

ROOT = Path(__file__).parents[1]
OUT = ROOT / "outputs/fmi-host"


def specs():
    base = json.loads((ROOT / "examples/studies/fmi_joint_v1.json").read_text())
    result = {}
    for name in ("nominal", "reverse", "loaded-board", "delayed", "unreachable"):
        item = copy.deepcopy(base)
        item["id"] = name
        if name == "reverse":
            item["settings"]["iq_reference_a"]["value"] = -1.
        if name == "loaded-board":
            item["settings"]["load_nm"]["value"] = .2
            item["settings"]["board_power_w"]["value"] = 20.
        if name == "delayed":
            item["settings"]["delay_samples"]["value"] = 1
        if name == "unreachable":
            item["settings"]["vdc_v"]["value"] = 2.
            item["settings"]["iq_reference_a"]["value"] = 5.
        result[name] = item
    return result


def independent(document, result):
    s = resolved_settings(document)
    rows = np.asarray(result["streams"]["control"]["samples"])
    waves = np.asarray(result["streams"]["waveforms"]["samples"])
    count = (len(waves)-1)//(len(rows)-1)
    reference = [initial()]
    x, integral, previous = initial(), np.zeros(2), np.zeros(2)
    voltage_error = 0.
    for tick, row in enumerate(rows[:-1]):
        applied, integral, previous, _ = command(s, x, tick, integral, previous)
        voltage_error = max(voltage_error, float(np.max(np.abs(applied-row[14:16]))))
        t, end = row[0], rows[tick+1, 0]
        solution = solve_ivp(rhs, (t, end), x, args=(row[14:18],), method="DOP853",
                             rtol=2e-12, atol=2e-13, dense_output=True)
        assert solution.success
        points = waves[tick*count+1:(tick+1)*count+1, 0]
        values = solution.sol(points).T
        reference.extend(values)
        x = values[-1]
    reference = np.asarray(reference)
    errors = np.max(np.abs(waves[:, 1:10]-reference[:, :9]), axis=0)
    energy = stored(waves[:, 1:13])
    residual = energy-energy[0]-waves[:, 10]+waves[:, 11]+waves[:, 12]
    assert np.max(np.abs(residual)) <= 2e-6
    assert np.max(errors) <= 2e-5
    assert voltage_error <= 2e-5
    return reference, errors, voltage_error


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    _, metadata = build()
    shutil.copyfile(PLANT_OUT / "oeal-joint.fmu", OUT / "oeal-joint.fmu")
    cases = []
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
        residual = stored(x)-x[:, 9]+x[:, 10]+x[:, 11]
        columns = [*result["streams"]["control"]["columns"],
                   *["reference_"+n for n in result["streams"]["control"]["columns"][1:10]],
                   "balance_j"]
        data = np.column_stack([rows, reference[::count, :9], residual])
        np.savetxt(OUT / (name+".csv"), data, delimiter=",", header=",".join(columns), comments="")
        expected = name != "unreachable"
        assert result["numeric_passed"] and result["goal_passed"] == expected
        case = dict(id=name, passed=result["goal_passed"], expected_passed=expected,
                    metrics=result["metrics"], max_state_error=float(max(errors)),
                    state_errors=errors.tolist(), voltage_error_v=voltage_error,
                    peak_balance_j=result["metrics"]["energy_balance_abs_j"],
                    columns=columns, samples=data[::10].tolist(), rows=len(rows),
                    waveform_rows=len(waves), raw_sha256=result["raw_sha256"],
                    limited_ticks=int(np.sum(rows[:-1, -2])))
        cases.append(case)
        print("fmi-host-case: " + json.dumps({k: v for k, v in case.items()
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
            for kind in ("reference", "voltage", "endpoint", "binary context"):
                altered = copy.deepcopy(result)
                if kind == "reference":
                    altered["streams"]["control"]["samples"][100][19] += .1
                elif kind == "voltage":
                    altered["streams"]["control"]["samples"][100][15] += .1
                elif kind == "endpoint":
                    altered["streams"]["waveforms"]["samples"].pop()
                else:
                    altered["context"]["fmi_asset_hashes"]["binary_sha256"] = "0"*64
                altered["raw_sha256"] = document_hash(altered["streams"])
                try:
                    recompute(document, altered)
                except ValueError:
                    checks.append("independent audit rejects "+kind)
                else:
                    raise AssertionError("forged input accepted: "+kind)
    with zipfile.ZipFile(OUT / "oeal-joint.fmu") as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    for name, old, new in (("GUID", b"000000000018", b"000000000099"),
                            ("port unit", b'unit="A"', b'unit="V"')):
        changed = OUT / ("bad-"+name.replace(" ", "-"))
        changed.mkdir(exist_ok=True)
        with zipfile.ZipFile(changed / "oeal-joint.fmu", "w") as archive:
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
    report = dict(passed=True, cases=cases, boundary_checks=checks, metadata=metadata,
                  evidence_level="model_simulated",
                  scope="external 20kHz dq PI and pinned nine-state FMI plant")
    (OUT / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("fmi-host-summary: " + json.dumps(dict(passed=True, checks=checks)))


if __name__ == "__main__":
    main()
