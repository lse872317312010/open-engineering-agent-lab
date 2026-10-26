"""Build a configurable FMI plant and verify it before trusting its binary."""

import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, parse

import fmpy
import numpy as np
from fmi_servo_reference import defaults, rhs, stored
from fmpy import extract, read_model_description
from fmpy.fmi2 import FMU2Slave
from joint_fmi_reference import initial
from scipy.integrate import solve_ivp
from validate_joint_fmi import OUT as V1_OUT
from validate_joint_fmi import build as build_v1

ROOT = Path(__file__).parents[1]
OUT = ROOT / "outputs/configurable-fmi"
GUID = "{a5505b9e-0ea1-4060-b701-000000000020}"
IDENT = "oeal_servo"
PARAMETERS = list(defaults())
UNITS = ["ohm", "H", "H", "Wb", "1", "kg*m^2", "N*m*s"]
LOW = [.15, .0004, .0004, .015, 1, 2.5e-5, 0]
HIGH = [.6, .0016, .0016, .045, 14, 2e-4, 5e-5]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    build_v1()
    stage = OUT / "package"
    stage.mkdir(parents=True, exist_ok=True)
    tree = parse(V1_OUT / "package/modelDescription.xml")
    xml = tree.getroot()
    xml.set("guid", GUID)
    xml.set("modelName", "OEALConfigurableJoint")
    xml.find("CoSimulation").set("modelIdentifier", IDENT)
    units = xml.find("UnitDefinitions")
    bases = {"ohm": dict(kg="1", m="2", s="-3", A="-2"),
             "H": dict(kg="1", m="2", s="-2", A="-2"),
             "Wb": dict(kg="1", m="2", s="-2", A="-1"),
             "1": {}, "kg*m^2": dict(kg="1", m="2"),
             "N*m*s": dict(kg="1", m="2", s="-1")}
    for unit, base in bases.items():
        SubElement(SubElement(units, "Unit", name=unit), "BaseUnit", **base)
    for i, (name, value, unit, low, high) in enumerate(zip(
        PARAMETERS, defaults().values(), UNITS, LOW, HIGH, strict=True
    )):
        node = SubElement(xml.find("ModelVariables"), "ScalarVariable", name=name,
                          valueReference=str(18+i), causality="parameter",
                          variability="fixed", initial="exact")
        SubElement(node, "Real", unit=unit, start=str(value), min=str(low), max=str(high))
    tree.write(stage / "modelDescription.xml", encoding="utf-8", xml_declaration=True)
    source = ROOT / "firmware/fmi/configurable_joint.c"
    binary = stage / "binaries/linux64/oeal_servo.so"
    binary.parent.mkdir(parents=True, exist_ok=True)
    command = ["gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
               "-shared", "-fPIC", "-I", str(Path(fmpy.__file__).parent / "c-code"),
               str(source), "-lm", "-o", str(binary)]
    subprocess.run(command, check=True)
    resources = stage / "resources"
    resources.mkdir(exist_ok=True)
    for path, name in [(source, "joint.c"), (ROOT / "docs/fmi-servo-contract.md", "contract.md"),
                       (ROOT / "LICENSE", "LICENSE"),
                       (ROOT / "research/licenses/FMPy-v0.3.26.txt", "THIRD_PARTY.txt")]:
        shutil.copyfile(path, resources / name)
    archive = OUT / "oeal-servo.fmu"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(stage))
    description = read_model_description(str(archive), validate=True)
    assert len(description.modelVariables) == 25
    extracted = extract(str(archive), unzipdir=str(OUT / "runtime"))
    metadata = dict(binary_sha256=sha(binary), source_sha256=sha(source),
                    archive_sha256=sha(archive), command=command, fmpy=fmpy.__version__,
                    code_commit=subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                        text=True).strip())
    return extracted, metadata


def instance(path, guid=GUID, ident=IDENT):
    model = FMU2Slave(guid=guid, unzipDirectory=str(path), modelIdentifier=ident,
                     instanceName="independent-plant")
    model.instantiate()
    return model


def initialize(model, parameters=None):
    model.setupExperiment(startTime=0., stopTime=.04)
    model.enterInitializationMode()
    if parameters is not None:
        model.setReal(list(range(18, 25)), [parameters[name] for name in PARAMETERS])
    model.exitInitializationMode()


def main():
    extracted, metadata = build()
    cases = []
    for name, p in [
        ("default", defaults()),
        ("mismatch", defaults() | dict(stator_resistance_ohm=.36, d_inductance_h=.00064,
                                       q_inductance_h=.00096, flux_linkage_wb=.027,
                                       inertia_kg_m2=.0001, viscous_friction_nms=.00002)),
        ("salient-pp4", defaults() | dict(stator_resistance_ohm=.15, d_inductance_h=.0016,
                                          q_inductance_h=.0004, flux_linkage_wb=.045,
                                          pole_pairs=4, inertia_kg_m2=.0002,
                                          viscous_friction_nms=0.)),
    ]:
        model = instance(extracted)
        old = instance(V1_OUT / "runtime",
                       guid="{a5505b9e-0ea1-4060-b701-000000000018}", ident="oeal_joint")
        rows, references, previous = [initial()], [initial()], [initial()]
        try:
            initialize(model, p)
            initialize(old)
            for tick in range(400):
                t, h = tick*.0001, .0001
                u = [.2, 1.5 if tick < 200 else -.5, .1, 5.]
                model.setReal([12, 13, 14, 15], u)
                old.setReal([12, 13, 14, 15], u)
                model.doStep(t, h)
                old.doStep(t, h)
                rows.append(model.getReal(list(range(12))))
                previous.append(old.getReal(list(range(12))))
                sol = solve_ivp(rhs, (t, t+h), references[-1], args=(u, p),
                                method="DOP853", rtol=2e-12, atol=2e-13)
                assert sol.success
                references.append(sol.y[:, -1])
        finally:
            model.freeInstance()
            old.freeInstance()
        data, reference = np.array(rows), np.array(references)
        errors = np.max(np.abs(data[:, :9]-reference[:, :9]), axis=0)
        residual = stored(data, p)-data[:, 9]+data[:, 10]+data[:, 11]
        old_error = float(np.max(np.abs(data-np.asarray(previous)))) if name == "default" else None
        passed = (max(errors) <= 2e-5 and np.max(np.abs(residual)) <= 2e-6
                  and (old_error is None or old_error <= 1e-9))
        item = dict(id=name, passed=bool(passed), parameters=p, state_errors=errors.tolist(),
                    max_error=float(max(errors)), balance_j=float(np.max(np.abs(residual))),
                    legacy_error=old_error)
        cases.append(item)
        np.savetxt(OUT / (name+".csv"), np.column_stack([np.arange(401)*.0001, data, reference]),
                   delimiter=",")
        print("configurable-plant-case: "+json.dumps(item))
    model = instance(extracted)
    checked = []
    try:
        model.setupExperiment(startTime=0.)
        model.enterInitializationMode()
        for vr, value in [(18, .1), (19, .002), (21, float("nan")),
                          (22, 7.5), (23, 0.), (24, -1.)]:
            before = model.getReal(list(range(25)))
            try:
                model.setReal([12, vr], [1., value])
            except Exception as error:
                assert error.__class__.__name__ == "FMICallException"
            else:
                raise AssertionError("invalid motor parameter accepted")
            assert model.getReal(list(range(25))) == before
            checked.append("atomic reject "+str(vr))
        model.setReal([18], [.36])
        model.exitInitializationMode()
        before = model.getReal(list(range(25)))
        try:
            model.setReal([18], [.3])
        except Exception as error:
            assert error.__class__.__name__ == "FMICallException"
        else:
            raise AssertionError("running fixed parameter accepted")
        assert model.getReal(list(range(25))) == before
        model.reset()
        assert model.getReal(list(range(18, 25))) == list(defaults().values())
        checked.extend(["running fixed parameter rejected", "reset restores all defaults"])
    finally:
        model.freeInstance()
    report = dict(passed=all(c["passed"] for c in cases), cases=cases,
                  checks=checked, metadata=metadata)
    (OUT / "validation.json").write_text(json.dumps(report, indent=2))
    print("configurable-plant-summary: "+json.dumps(report))
    assert report["passed"]


if __name__ == "__main__":
    main()
