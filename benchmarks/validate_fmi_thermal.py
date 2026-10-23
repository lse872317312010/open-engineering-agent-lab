"""Build an original thermal RC FMU and exercise the FMI 2.0 transport via FMPy."""

import json
import math
import shutil
import subprocess
import zipfile
from pathlib import Path

import fmpy
import numpy as np
from fmpy import extract, read_model_description
from fmpy.fmi2 import FMU2Slave

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p6"
GUID = "{a5505b9e-0ea1-4060-b701-000000000006}"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stage = OUT / "fmu-package"
    binary = stage / "binaries/linux64/oeal_thermal_rc.so"
    binary.parent.mkdir(parents=True, exist_ok=True)
    include = Path(fmpy.__file__).parent / "c-code"
    source = ROOT / "firmware/fmi/thermal_rc.c"
    command = ["gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
               "-shared", "-fPIC", "-I", str(include), str(source), "-lm", "-o", str(binary)]
    subprocess.run(command, check=True)
    variables = [
        '<ScalarVariable name="temperature" valueReference="0" causality="output" '
        'variability="continuous" initial="exact"><Real start="25" unit="degC"/></ScalarVariable>',
        '<ScalarVariable name="power" valueReference="1" causality="input" '
        'variability="continuous"><Real start="0" unit="W"/></ScalarVariable>',
        '<ScalarVariable name="resistance" valueReference="2" causality="parameter" '
        'variability="fixed" initial="exact"><Real start="1.5" unit="K/W"/></ScalarVariable>',
        '<ScalarVariable name="capacity" valueReference="3" causality="parameter" '
        'variability="fixed" initial="exact"><Real start="80" unit="J/K"/></ScalarVariable>',
        '<ScalarVariable name="ambient" valueReference="4" causality="parameter" '
        'variability="fixed" initial="exact"><Real start="25" unit="degC"/></ScalarVariable>',
    ]
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<fmiModelDescription fmiVersion="2.0" modelName="OEALThermalRC" guid="{GUID}" '
        'generationTool="OEAL" variableNamingConvention="flat" numberOfEventIndicators="0">'
        '<CoSimulation modelIdentifier="oeal_thermal_rc" '
        'canHandleVariableCommunicationStepSize="true" '
        'canGetAndSetFMUstate="false" canSerializeFMUstate="false"/>'
        '<UnitDefinitions><Unit name="degC"><BaseUnit K="1" offset="273.15"/></Unit>'
        '<Unit name="W"><BaseUnit kg="1" m="2" s="-3"/></Unit>'
        '<Unit name="K/W"><BaseUnit K="1" kg="-1" m="-2" s="3"/></Unit>'
        '<Unit name="J/K"><BaseUnit kg="1" m="2" s="-2" K="-1"/></Unit></UnitDefinitions>'
        '<ModelVariables>' + "".join(variables) + '</ModelVariables>'
        '<ModelStructure><Outputs><Unknown index="1"/></Outputs>'
        '</ModelStructure></fmiModelDescription>'
    )
    (stage / "modelDescription.xml").write_text(xml)
    resources = stage / "resources"
    resources.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "research/licenses/FMPy-v0.3.26.txt", resources / "THIRD_PARTY.txt")
    archive = OUT / "oeal-thermal-rc.fmu"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(stage))
    description = read_model_description(str(archive), validate=True)
    unzip = extract(str(archive), unzipdir=str(OUT / "fmu-runtime"))
    model = FMU2Slave(
        guid=description.guid, unzipDirectory=unzip,
        modelIdentifier=description.coSimulation.modelIdentifier, instanceName="thermal",
    )
    errors = []
    reset_errors = []
    rejected = 0
    try:
        model.instantiate()
        for repetition in range(2):
            if repetition:
                model.reset()
            model.setupExperiment(startTime=0)
            model.enterInitializationMode()
            model.setReal([0, 2, 3, 4], [25, 1.5, 80, 25])
            model.exitInitializationMode()
            # Invalid variable writes must not corrupt the existing parameter.
            try:
                model.setReal([2], [-1])
            except Exception as error:
                if error.__class__.__name__ != "FMICallException":
                    raise
                rejected += 1
            if model.getReal([2])[0] != 1.5:
                raise AssertionError("invalid FMI write mutated parameters")
            expected = 25.0
            trajectory = []
            for tick in range(400):
                power = 10.0 if tick < 200 else 3.0
                model.setReal([1], [power])
                model.doStep(currentCommunicationPoint=tick * 0.5, communicationStepSize=0.5)
                expected = 25 + (expected - 25) * math.exp(-0.5 / 120) + (
                    1.5 * power * (1 - math.exp(-0.5 / 120))
                )
                actual = model.getReal([0])[0]
                errors.append(abs(actual - expected))
                trajectory.append(actual)
            reset_errors.append(trajectory)
        model.terminate()
    finally:
        model.freeInstance()
    repeated_error = float(np.max(np.abs(np.array(reset_errors[0]) - reset_errors[1])))
    report = {
        "passed": max(errors) < 1e-6 and repeated_error < 1e-12 and rejected == 2,
        "backend": "original FMI 2.0 CoSimulation RC + FMPy 0.3.26",
        "scope": "single-node RC only; no full joint FMU or OpenModelica",
        "max_error_k": max(errors), "reset_error_k": repeated_error,
        "invalid_writes_rejected": rejected, "command": command,
        "fmpy_license": "BSD-2-Clause plus bundled FMI/SUNDIALS notices",
    }
    (OUT / "fmi.json").write_text(json.dumps(report, indent=2))
    print("fmi.json: " + json.dumps(report))
    if not report["passed"]:
        raise AssertionError("FMI thermal reference failed")


if __name__ == "__main__":
    main()
