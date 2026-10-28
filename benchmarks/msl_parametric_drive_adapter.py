"""Fixed nonlinear MSL asset; every branch state belongs to the upstream solver."""

import csv
import ctypes
import gzip
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
from fmpy import extract, read_model_description
from fmpy.fmi2 import FMU2Model
from msl_cooling_drive_parameters import configuration
from msl_cooling_drive_reference import BRANCHES, gc_at
from msl_rc_parameters import rc_parameters

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/msl-parametric"
PTR = ctypes.POINTER(ctypes.c_double)
NODES = [f"node[{i}].T" for i in range(1, 7)]
STATES = NODES+["input_energy_j", "case_energy_j", "convection_energy_j",
                "radiation_energy_j"]
POWERS = [f"power_w[{i}]" for i in range(1, 7)]
LOG_COLUMNS = (["accepted", "time_s"]+[f"temperature_{i}_c" for i in range(6)]
               + [f"heat_{i}_w" for i in range(6)]+["input_j", "ambient_j"]
               + list(BRANCHES)+["gc_w_k"]
               + [f"rate_{i}_k_s" for i in range(6)]
               + ["input_rate_w", "ambient_rate_w", "case_w", "convection_w", "radiation_w"])


class MSLParametricDrive:
    energy_state_names = BRANCHES
    initial_temperatures_c = (80.,)*6

    def __init__(self, destination, duration, area, varying=False, *,
                 ambient_c=25., initial_temperatures_c=None, capacities_j_per_k=None,
                 link_resistances_k_per_w=None, case_resistance_k_per_w=2.):
        self.ambient_c, self.area, self.initial_temperatures_c = configuration(
            ambient_c, area, initial_temperatures_c)
        (self.capacities_j_per_k, self.link_resistances_k_per_w,
         self.case_resistance_k_per_w) = rc_parameters(
             capacities_j_per_k, link_resistances_k_per_w, case_resistance_k_per_w)
        self.varying = varying
        archive = SOURCE / "OEALMSLParametric.fmu"
        with zipfile.ZipFile(archive) as z:
            model = z.read("resources/oeal-licenses/OEALMSLParametric.mo")
            assert model == (ROOT / "models/modelica/OEALMSLParametric.mo").read_bytes()
            self.model_sha256 = hashlib.sha256(model).hexdigest()
            xml = z.read("modelDescription.xml")
            self.binary_hashes = {n: hashlib.sha256(z.read(n)).hexdigest()
                                  for n in z.namelist() if n.endswith(".so")}
        md = read_model_description(str(archive), validate=True)
        assert md.modelExchange and md.numberOfContinuousStates == 10
        assert md.numberOfEventIndicators == 0 and md.fmiVersion == "2.0"
        root = ElementTree.fromstring(xml)
        variables_xml = list(root.find("ModelVariables"))
        self.fmi_state_names = []
        for unknown in root.findall("ModelStructure/Derivatives/Unknown"):
            derivative = variables_xml[int(unknown.attrib["index"])-1]
            state_index = int(derivative.find("Real").attrib["derivative"])-1
            self.fmi_state_names.append(variables_xml[state_index].attrib["name"])
        assert len(self.fmi_state_names) == 10
        self.variables = {v.name: v for v in md.modelVariables}
        state_variables = [self.variables[n] for n in self.fmi_state_names]
        self.index, self.offsets = [], []
        for i, canonical in enumerate(STATES):
            candidates = [self.variables[canonical]]
            generated_alias = self.variables.get("_D_outputAlias_"+canonical)
            if generated_alias is not None:
                candidates.append(generated_alias)
            if i < 6:
                candidates.append(self.variables[f"temperature_c[{i+1}]"])
            matches = [(j, v.unit) for j, v in enumerate(state_variables)
                       if any(v.valueReference == c.valueReference for c in candidates)]
            assert len(matches) == 1, (canonical, self.fmi_state_names,
                                       [(v.name, v.unit, v.valueReference)
                                        for v in state_variables])
            j, unit = matches[0]
            assert unit in (("K", "degC") if i < 6 else ("J",))
            self.index.append(j)
            self.offsets.append(273.15 if unit == "K" else 0.)
        assert sorted(self.index) == list(range(10))
        print("msl-state-map: "+json.dumps(dict(states=self.fmi_state_names, index=self.index,
                                                offsets=self.offsets)), flush=True)
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
        self.fmu.setReal([self.variables["ambient_k"].valueReference,
                          self.variables["radiation_area_m2"].valueReference],
                         [self.ambient_c+273.15, self.area])
        self.fmu.setReal([self.variables[n].valueReference for n in POWERS], [0.]*6)
        self.fmu.setReal([self.variables["convection_w_per_k"].valueReference], [1/3])
        rc_names = ([f"heat_capacities_j_per_k[{i}]" for i in range(1, 7)]
                    + [f"link_resistances_k_per_w[{i}]" for i in range(1, 6)]
                    + ["case_resistance_k_per_w"])
        rc_values = [*self.capacities_j_per_k, *self.link_resistances_k_per_w,
                     self.case_resistance_k_per_w]
        for name, unit in zip(rc_names, ["J/K"]*6+["K/W"]*6, strict=True):
            assert self.variables[name].causality == "parameter"
            assert self.variables[name].unit == unit
        self.fmu.setReal([self.variables[n].valueReference for n in rc_names], rc_values)
        self.fmu.exitInitializationMode()
        np.testing.assert_array_equal(self.fmu.getReal(
            [self.variables[n].valueReference for n in rc_names]), rc_values)
        # Read the actual MSL component parameters, not only the root bindings.
        components = ([f"node[{i}].C" for i in range(1, 7)]
                      + [f"path[{i}].R" for i in range(1, 6)]+["case_path.R"])
        outputs = ([f"configured_capacity_j_per_k[{i}]" for i in range(1, 7)]
                   + [f"configured_link_r_k_per_w[{i}]" for i in range(1, 6)]
                   + ["configured_case_r_k_per_w"])
        for name, unit in zip(outputs, ["J/K"]*6+["K/W"]*6, strict=True):
            assert self.variables[name].causality == "output" and self.variables[name].unit == unit
        self.component_names, self.component_outputs = components, outputs
        self.rc_values = rc_values
        self.verified_component_parameters = {}
        event = self.fmu.newDiscreteStates()
        assert not event[0] and not event[1] and not event[4]
        self.fmu.enterContinuousTimeMode()
        initial = np.empty(10)
        self.fmu.getContinuousStates(initial.ctypes.data_as(PTR), 10)
        np.testing.assert_allclose(initial[self.index],
                                   np.r_[[self.ambient_c]*6, np.zeros(4)]+self.offsets, atol=1e-12)
        # Project synthetic hot initial state; all energy integrals remain zero.
        initial[self.index] = np.r_[self.initial_temperatures_c, np.zeros(4)]+self.offsets
        self.fmu.setContinuousStates(initial.ctypes.data_as(PTR), 10)
        self.file = gzip.open(destination, "wt", compresslevel=1)
        self.writer = csv.writer(self.file)
        self.writer.writerow(LOG_COLUMNS)
        self.calls = self.checkpoints = 0
        self.last_checkpoint = -1.
        self.projection_temperature_k = self.projection_energy_j = 0.

    def evaluate(self, t, temperatures, heat, input_j, ambient_j, *,
                 branch_energy_j, accepted=False):
        values = np.empty(10)
        values[self.index] = np.r_[temperatures, input_j, branch_energy_j]+self.offsets
        m = self.fmu
        m.setTime(float(t))
        m.setContinuousStates(values.ctypes.data_as(PTR), 10)
        m.setReal([self.variables[n].valueReference for n in POWERS], heat)
        gc = gc_at(t, self.varying)
        m.setReal([self.variables["convection_w_per_k"].valueReference], [gc])
        derivative = np.empty(10)
        m.getDerivatives(derivative.ctypes.data_as(PTR), 10)
        canonical = derivative[self.index]
        ordered = np.r_[canonical[:7], sum(canonical[7:]), canonical[7:]]
        self.writer.writerow([int(accepted), t, *temperatures, *heat, input_j, ambient_j,
                              *branch_energy_j, gc, *ordered])
        if accepted:
            if t <= self.last_checkpoint:
                raise ValueError("accepted controller checkpoints must strictly increase")
            self.last_checkpoint = t
            # OMC1.25.5 refreshes algebraic/public output aliases on accepted-step completion.
            assert m.completedIntegratorStep() == (False, False)
            if not self.verified_component_parameters:
                actual_rc = m.getReal([self.variables[n].valueReference
                                       for n in self.component_outputs])
                np.testing.assert_array_equal(actual_rc, self.rc_values)
                self.verified_component_parameters = dict(zip(
                    self.component_names, actual_rc, strict=True))
            outputs = m.getReal([self.variables[f"temperature_c[{i}]"].valueReference
                                 for i in range(1, 7)]
                                + [self.variables[n].valueReference for n in STATES[6:]])
            self.projection_temperature_k = max(self.projection_temperature_k,
                                                float(max(abs(outputs[:6]-temperatures))))
            self.projection_energy_j = max(self.projection_energy_j,
                                            float(max(abs(np.asarray(outputs[6:])
                                                          - [input_j, *branch_energy_j]))))
            assert self.projection_temperature_k <= 1e-10, self.projection_temperature_k
            assert self.projection_energy_j <= 1e-8, self.projection_energy_j
            self.checkpoints += 1
        else:
            self.calls += 1
        return ordered

    def describe(self):
        return dict(kind="parametric nonlinear MSL4.0.0 ModelExchange",
                    capacities_j_per_k=list(self.capacities_j_per_k),
                    link_resistances_k_per_w=list(self.link_resistances_k_per_w),
                    case_resistance_k_per_w=self.case_resistance_k_per_w,
                    component_parameters=self.verified_component_parameters,
                    model_sha256=self.model_sha256,
                    area_m2=self.area, varying_gc=self.varying, ambient_c=self.ambient_c,
                    initial_temperatures_c=list(self.initial_temperatures_c),
                    state_names=self.fmi_state_names, canonical_indices=self.index,
                    canonical_offsets=self.offsets, binary_sha256=self.binary_hashes,
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
