"""Fixed self-built MSL asset adapter for continuous drive integration evidence.

This benchmark loads only outputs/msl-thermal/OEALMSLThermal.fmu. It is not an
experiment-selectable path or an IR runtime asset registration.
"""

import csv
import ctypes
import gzip
import hashlib
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
from fmpy import extract, read_model_description
from fmpy.fmi2 import FMU2Model

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/msl-thermal"
PTR = ctypes.POINTER(ctypes.c_double)
NODES = [f"node[{i}].T" for i in range(1, 7)]
STATES = NODES+["input_energy_j", "ambient_energy_j"]
POWERS = [f"power_w[{i}]" for i in range(1, 7)]
LOG_COLUMNS = (["accepted", "time_s"]+[f"temperature_{i}_c" for i in range(6)]
               + [f"heat_{i}_w" for i in range(6)]+["input_j", "ambient_j"]
               + [f"rate_{i}_k_s" for i in range(6)]+["input_rate_w", "ambient_rate_w"])


class MSLDriveThermal:
    def __init__(self, destination, duration):
        archive = SOURCE / "OEALMSLThermal.fmu"
        with zipfile.ZipFile(archive) as z:
            model = z.read("resources/oeal-licenses/OEALMSLThermal.mo")
            assert hashlib.sha256(model).hexdigest() == (
                "f781e2a36c55f5afc7788974e268abf1bf0b0c10a474db29656ac5ea23ddb62d")
            xml = z.read("modelDescription.xml")
            self.binary_hashes = {n: hashlib.sha256(z.read(n)).hexdigest()
                                  for n in z.namelist() if n.endswith(".so")}
        md = read_model_description(str(archive), validate=True)
        assert md.modelExchange and md.numberOfContinuousStates == 8
        assert md.numberOfEventIndicators == 0 and md.fmiVersion == "2.0"
        root = ElementTree.fromstring(xml)
        variables_xml = list(root.find("ModelVariables"))
        self.state_names = []
        for unknown in root.findall("ModelStructure/Derivatives/Unknown"):
            derivative = variables_xml[int(unknown.attrib["index"])-1]
            state_index = int(derivative.find("Real").attrib["derivative"])-1
            self.state_names.append(variables_xml[state_index].attrib["name"])
        assert len(self.state_names) == 8 and set(self.state_names) == set(STATES)
        self.index = [self.state_names.index(n) for n in STATES]
        self.variables = {v.name: v for v in md.modelVariables}
        for name in NODES:
            assert self.variables[name].unit == "K"
        for name in POWERS:
            assert self.variables[name].causality == "input" and self.variables[name].unit == "W"
        self.extracted = extract(str(archive))
        self.fmu = FMU2Model(guid=md.guid, unzipDirectory=self.extracted,
                            modelIdentifier=md.modelExchange.modelIdentifier, instanceName="drive")
        self.fmu.instantiate()
        self.fmu.setupExperiment(startTime=0., stopTime=duration+100e-6, tolerance=1e-11)
        self.fmu.enterInitializationMode()
        self.fmu.setReal([self.variables["ambient_k"].valueReference], [298.15])
        self.fmu.setReal([self.variables[n].valueReference for n in POWERS], [0.]*6)
        self.fmu.exitInitializationMode()
        event = self.fmu.newDiscreteStates()
        assert not event[0] and not event[1] and not event[4]
        self.fmu.enterContinuousTimeMode()
        initial = np.empty(8)
        self.fmu.getContinuousStates(initial.ctypes.data_as(PTR), 8)
        np.testing.assert_allclose(initial[self.index], [298.15]*6+[0., 0.], atol=1e-12)
        self.file = gzip.open(destination, "wt", compresslevel=1)
        self.writer = csv.writer(self.file)
        self.writer.writerow(LOG_COLUMNS)
        self.calls = self.checkpoints = 0
        self.last_checkpoint = -1.
        self.projection_temperature_k = self.projection_energy_j = 0.

    def evaluate(self, t, temperatures, heat, input_j, ambient_j, *, accepted=False):
        values = np.empty(8)
        values[self.index] = np.r_[np.asarray(temperatures)+273.15, input_j, ambient_j]
        m = self.fmu
        m.setTime(float(t))
        m.setContinuousStates(values.ctypes.data_as(PTR), 8)
        m.setReal([self.variables[n].valueReference for n in POWERS], heat)
        derivative = np.empty(8)
        m.getDerivatives(derivative.ctypes.data_as(PTR), 8)
        ordered = derivative[self.index]
        self.writer.writerow([int(accepted), t, *temperatures, *heat, input_j, ambient_j, *ordered])
        if accepted:
            if t <= self.last_checkpoint:
                raise ValueError("accepted controller checkpoints must strictly increase")
            self.last_checkpoint = t
            outputs = m.getReal([self.variables[f"temperature_c[{i}]"].valueReference
                                 for i in range(1, 7)]
                                + [self.variables[n].valueReference for n in STATES[6:]])
            self.projection_temperature_k = max(self.projection_temperature_k,
                                                float(max(abs(outputs[:6]-temperatures))))
            self.projection_energy_j = max(self.projection_energy_j,
                                            float(max(abs(np.asarray(outputs[6:])
                                                          - [input_j, ambient_j]))))
            assert m.completedIntegratorStep() == (False, False)
            self.checkpoints += 1
        else:
            self.calls += 1
        return ordered

    def describe(self):
        return dict(kind="fixed self-built MSL4.0.0 ModelExchange",
                    state_names=self.state_names, binary_sha256=self.binary_hashes,
                    rhs_calls=self.calls, accepted_checkpoints=self.checkpoints,
                    projection_temperature_k=self.projection_temperature_k,
                    projection_energy_j=self.projection_energy_j)

    def close(self):
        self.file.close()
        try:
            self.fmu.terminate()
        finally:
            self.fmu.freeInstance()
            shutil.rmtree(self.extracted)
