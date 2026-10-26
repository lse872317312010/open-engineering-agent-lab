"""Build and independently validate the original joint FMI 2.0 plant."""

import hashlib
import json
import math
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

import fmpy
import numpy as np
from fmpy import extract, read_model_description
from fmpy.fmi2 import FMU2Slave
from joint_fmi_reference import balance, initial, rhs, schedule
from scipy.integrate import solve_ivp

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/joint-fmi"
GUID = "{a5505b9e-0ea1-4060-b701-000000000018}"
IDENT = "oeal_joint"
NAMES = ["id_a", "iq_a", "motor_angle_rad", "motor_speed_rad_s",
         "load_angle_rad", "load_speed_rad_s", "winding_c", "case_c", "board_c",
         "input_energy_j", "load_work_j", "ambient_heat_j",
         "vd_v", "vq_v", "load_nm", "board_w", "internal_step_s", "shaft_nm"]
UNITS = ["A", "A", "rad", "rad/s", "rad", "rad/s", "degC", "degC", "degC",
         "J", "J", "J", "V", "V", "N*m", "W", "s", "N*m"]
CASES = ("no-load", "loaded-heating", "reversal", "variable-clock")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    stage = OUT / "package"
    binary = stage / "binaries/linux64/oeal_joint.so"
    binary.parent.mkdir(parents=True, exist_ok=True)
    source = ROOT / "firmware/fmi/joint.c"
    include = Path(fmpy.__file__).parent / "c-code"
    command = ["gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
               "-shared", "-fPIC", "-I", str(include), str(source), "-lm", "-o", str(binary)]
    subprocess.run(command, check=True)
    xml = Element("fmiModelDescription", fmiVersion="2.0", modelName="OEALJointPlant",
                  guid=GUID, generationTool="OEAL", variableNamingConvention="flat",
                  numberOfEventIndicators="0")
    SubElement(xml, "CoSimulation", modelIdentifier=IDENT,
               canHandleVariableCommunicationStepSize="true",
               canGetAndSetFMUstate="false", canSerializeFMUstate="false")
    definitions = SubElement(xml, "UnitDefinitions")
    bases = {"A": dict(A="1"), "rad": {}, "rad/s": dict(s="-1"), "s": dict(s="1"),
             "degC": dict(K="1", offset="273.15"), "J": dict(kg="1", m="2", s="-2"),
             "V": dict(kg="1", m="2", s="-3", A="-1"),
             "N*m": dict(kg="1", m="2", s="-2"), "W": dict(kg="1", m="2", s="-3")}
    for name, attrs in bases.items():
        SubElement(SubElement(definitions, "Unit", name=name), "BaseUnit", **attrs)
    SubElement(xml, "DefaultExperiment", startTime="0", stopTime=".08", stepSize=".00005")
    variables = SubElement(xml, "ModelVariables")
    outputs = list(range(12)) + [17]
    for i, (name, unit) in enumerate(zip(NAMES, UNITS, strict=True)):
        if i in outputs:
            attrs = dict(causality="output", variability="continuous", initial="calculated")
            real = dict(unit=unit)
        elif i == 16:
            attrs = dict(causality="parameter", variability="fixed", initial="exact")
            real = dict(unit=unit, start="0.000005", min="0.00000001", max="0.000005")
        else:
            attrs = dict(causality="input", variability="continuous")
            real = dict(unit=unit, start="0")
        node = SubElement(variables, "ScalarVariable", name=name, valueReference=str(i), **attrs)
        SubElement(node, "Real", **real)
    structure = SubElement(xml, "ModelStructure")
    for group in ("Outputs", "InitialUnknowns"):
        container = SubElement(structure, group)
        for i in outputs:
            SubElement(container, "Unknown", index=str(i+1))
    (stage / "modelDescription.xml").write_bytes(tostring(xml, encoding="utf-8",
                                                        xml_declaration=True))
    resources = stage / "resources"
    resources.mkdir(exist_ok=True)
    for source, target in [
        (ROOT / "docs/joint-fmi-contract.md", "contract.md"),
        (ROOT / "firmware/fmi/joint.c", "joint.c"),
        (ROOT / "LICENSE", "LICENSE"),
        (ROOT / "research/licenses/FMPy-v0.3.26.txt", "THIRD_PARTY.txt"),
    ]:
        shutil.copyfile(source, resources / target)
    archive = OUT / "oeal-joint.fmu"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(stage))
    description = read_model_description(str(archive), validate=True)
    assert len(description.modelVariables) == 18
    extracted = extract(str(archive), unzipdir=str(OUT / "runtime"))
    metadata = dict(command=command, fmpy=fmpy.__version__, platform="linux64",
                    compiler=subprocess.check_output(
                        ["gcc", "--version"], text=True).splitlines()[0],
                    source_sha256=digest(ROOT / "firmware/fmi/joint.c"),
                    binary_sha256=digest(binary), fmu_sha256=digest(archive),
                    code_commit=subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                        text=True).strip())
    return extracted, metadata


def slave(extracted, name="joint", guid=GUID):
    return FMU2Slave(guid=guid, unzipDirectory=extracted, modelIdentifier=IDENT,
                     instanceName=name)


def initialize(model, step=5e-6, stop=.08):
    model.setupExperiment(startTime=0., stopTime=stop)
    model.enterInitializationMode()
    model.setReal([16], [step])
    model.exitInitializationMode()


def simulate(extracted, name, step):
    model = slave(extracted, name)
    model.instantiate()
    rows = [initial()]
    try:
        initialize(model, step)
        for t, h, u in schedule(name):
            model.setReal([12, 13, 14, 15], u)
            model.doStep(currentCommunicationPoint=t, communicationStepSize=h)
            rows.append(model.getReal(list(range(12))))
        model.terminate()
    finally:
        model.freeInstance()
    return np.asarray(rows)


def oracle(name):
    x = initial()
    rows = [x.copy()]
    for t, h, u in schedule(name):
        solution = solve_ivp(rhs, (t, t+h), x, args=(u,), method="DOP853",
                             rtol=2e-12, atol=2e-13)
        assert solution.success
        x = solution.y[:, -1]
        rows.append(x.copy())
    return np.asarray(rows)


def boundaries(extracted):
    model, other = slave(extracted, "bounds"), slave(extracted, "other")
    model.instantiate()
    other.instantiate()
    checked = []

    def reject(name, call):
        before = model.getReal(list(range(18)))
        clock = model.getRealStatus(2)
        try:
            call()
        except Exception as error:
            assert error.__class__.__name__ == "FMICallException", str(error)
        else:
            raise AssertionError("accepted " + name)
        assert model.getReal(list(range(18))) == before, name
        assert model.getRealStatus(2) == clock, name
        checked.append(name)

    try:
        reject("step before initialization", lambda: model.doStep(0., 5e-5))
        reject("exit before enter", model.exitInitializationMode)
        reject("invalid stop time", lambda: model.setupExperiment(startTime=1., stopTime=0.))
        initialize(model, stop=.0001)
        reject("repeated initialization", model.enterInitializationMode)
        for label, refs, values in [
            ("output write", [0], [1.]),
            ("running fixed parameter", [16], [2.5e-6]),
            ("atomic partial write", [12, 15], [1., -1.]),
            ("NaN input", [12], [float("nan")]),
            ("Inf input", [13], [float("inf")]),
            ("voltage limit", [12, 13], [20., 20.]),
            ("load limit", [14], [11.]),
            ("board limit", [15], [1001.]),
            ("unknown reference", [99], [0.]),
        ]:
            reject(label, lambda refs=refs, values=values: model.setReal(refs, values))
        for label, t, h in [
            ("clock discontinuity", .001, .00005),
            ("negative step", 0., -.00005), ("zero step", 0., 0.),
            ("oversized step", 0., .0011), ("past stop time", 0., .0002),
            ("NaN clock", float("nan"), .00005), ("Inf step", 0., float("inf")),
        ]:
            reject(label, lambda t=t, h=h: model.doStep(t, h))
        model.setReal([13], [1.])
        model.doStep(0., .00005)
        first = model.getReal(list(range(12)))
        np.testing.assert_array_equal(other.getReal(list(range(12))), initial())
        checked.append("instance isolation")
        model.reset()
        initialize(model, stop=.0001)
        model.setReal([13], [1.])
        model.doStep(0., .00005)
        assert model.getReal(list(range(12))) == first
        checked.append("bitwise reset replay")
        model.terminate()
        reject("step after terminate", lambda: model.doStep(.00005, .00005))
        reject("write after terminate", lambda: model.setReal([13], [0.]))
        model.reset()
        initialize(model)
        model.doStep(0., .001)
        np.testing.assert_array_equal(model.getReal(list(range(12))), initial())
        checked.append("unforced equilibrium")
        model.reset()
        initialize(model)
        model.setReal([12, 15], [1., 25.])
        model.doStep(0., 1e-6)
        point = model.getReal([0, 8])
        rl_exact = -math.expm1(-.3/.0008*1e-6)/.3
        assert abs(point[0]-rl_exact) < 1e-12
        assert abs(point[1]-(25.+1e-6)) < 1e-12
        checked.extend(["independent RL limit", "pure board heat initial slope"])
    finally:
        model.freeInstance()
        other.freeInstance()
    bad = slave(extracted, "bad-guid", "{invalid}")
    try:
        bad.instantiate()
    except Exception:
        checked.append("invalid GUID rejected")
    else:
        bad.freeInstance()
        raise AssertionError("invalid GUID accepted")
    return checked


def main():
    extracted, metadata = build()
    checks = boundaries(extracted)
    cases = []
    for name in CASES:
        coarse = simulate(extracted, name, 5e-6)
        fine = simulate(extracted, name, 2.5e-6)
        reference = oracle(name)
        errors = np.max(np.abs(coarse[:, :9]-reference[:, :9]), axis=0)
        fine_errors = np.max(np.abs(fine[:, :9]-reference[:, :9]), axis=0)
        residual = balance(coarse)
        steps = schedule(name)
        times = np.array([0.] + [t+h for t, h, _ in steps])
        inputs = np.asarray([u for _, _, u in steps] + [steps[-1][2]])
        path = OUT / (name + ".csv")
        data = np.column_stack([times, coarse, reference[:, :9], inputs, residual])
        columns = ["time_s", *NAMES[:12], *["reference_"+n for n in NAMES[:9]],
                   *NAMES[12:16], "balance_j"]
        np.savetxt(path, data, delimiter=",", header=",".join(columns), comments="")
        max_error, fine_error = float(max(errors)), float(max(fine_errors))
        difference = float(np.max(np.abs(coarse[-1, :9]-fine[-1, :9])))
        peak_balance = float(np.max(np.abs(residual)))
        passed = (np.all(np.isfinite(data)) and max_error <= 2e-5
                  and peak_balance <= 2e-6 and difference <= 2e-5
                  and fine_error <= 1.2*max_error+1e-10)
        corrupted = coarse.copy()
        corrupted[len(corrupted)//2, 9] += .001
        assert np.max(np.abs(balance(corrupted))) > 2e-6
        case = dict(id=name, passed=bool(passed), state_errors=errors.tolist(),
                    max_state_error=max_error, fine_state_error=fine_error,
                    step_difference=difference, peak_balance_j=peak_balance,
                    csv_sha256=digest(path), rows=len(times), columns=columns,
                    samples=data[::10].tolist())
        cases.append(case)
        print("joint-fmi-case: " + json.dumps({k: v for k, v in case.items()
                                              if k not in {"samples", "columns"}}))
    report = dict(passed=all(c["passed"] for c in cases), cases=cases, boundary_checks=checks,
                  metadata=metadata, evidence_level="model_simulated",
                  source="fixed synthetic research parameters",
                  scope="nine-state joint plant; rotating dq ZOH; no controller/MuJoCo/PWM")
    (OUT / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("joint-fmi-summary: " + json.dumps(dict(passed=report["passed"],
                                                 boundary_checks=checks, metadata=metadata)))
    if not report["passed"]:
        raise AssertionError("predeclared joint FMI gate failed")


if __name__ == "__main__":
    main()
