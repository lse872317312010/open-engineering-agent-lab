"""Audit a real MSL thermal FMU over complete one-hour trajectories."""

import ctypes
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import numpy as np
from fmpy import extract, read_model_description
from fmpy.fmi2 import FMU2Model
from msl_thermal_reference import BLOCKS, CAPACITY, balance, flows, rhs
from scipy.integrate import solve_ivp

from oeal.refined_thermal import ThermalNetwork

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/msl-thermal"
PTR = ctypes.POINTER(ctypes.c_double)
TEMPERATURES = ["winding_c", "core_c", "case_c", "junction_c", "board_c", "sink_c"]
FMI_OUTPUTS = ([f"temperature_c[{i}]" for i in range(1, 7)]
               + ["input_energy_j", "ambient_energy_j"]
               + [f"link_w[{i}]" for i in range(1, 6)]+["heat_to_ambient_w"])
POWERS = [f"power_w[{i}]" for i in range(1, 7)]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ThermalExchange:
    def __init__(self, ambient_c, name):
        if not np.isfinite(ambient_c) or not -10 <= ambient_c <= 60:
            raise ValueError("ambient outside frozen synthetic range")
        self.ambient = ambient_c
        archive = OUT / "OEALMSLThermal.fmu"
        md = read_model_description(str(archive), validate=True)
        assert md.fmiVersion == "2.0" and md.modelExchange is not None
        assert md.numberOfContinuousStates == 8 and md.numberOfEventIndicators == 0
        self.variables = {v.name: v for v in md.modelVariables}
        expected_units = ["degC"]*6+["J"]*2+["W"]*6
        for n, unit in zip(FMI_OUTPUTS, expected_units, strict=True):
            v = self.variables[n]
            assert v.causality == "output" and v.type == "Real" and v.unit == unit
        for n in POWERS:
            v = self.variables[n]
            assert v.causality == "input" and v.type == "Real" and v.unit == "W"
        v = self.variables["ambient_k"]
        assert v.causality == "parameter" and v.variability == "fixed" and v.unit == "K"
        self.extracted = extract(str(archive))
        self.fmu = FMU2Model(guid=md.guid, unzipDirectory=self.extracted,
                            modelIdentifier=md.modelExchange.modelIdentifier, instanceName=name)
        self.fmu.instantiate()
        self.initialize()

    def initialize(self):
        m = self.fmu
        m.setupExperiment(startTime=0., stopTime=3600., tolerance=1e-11)
        m.enterInitializationMode()
        m.setReal([self.variables["ambient_k"].valueReference], [self.ambient+273.15])
        m.setReal([self.variables[n].valueReference for n in POWERS], [0.]*6)
        m.exitInitializationMode()
        for _ in range(10):
            event = m.newDiscreteStates()
            assert not event[1] and not event[4], event
            if not event[0]:
                break
        else:
            raise AssertionError("initialization did not converge")
        m.enterContinuousTimeMode()
        self.x = np.empty(8)
        m.getContinuousStates(self.x.ctypes.data_as(PTR), 8)
        self.time = 0.
        np.testing.assert_allclose(self.output()[:8],
                                   np.r_[np.full(6, self.ambient), 0., 0.], atol=1e-12, rtol=0)

    def output(self):
        return np.asarray(self.fmu.getReal([self.variables[n].valueReference
                                           for n in FMI_OUTPUTS]))

    def advance(self, t, h, powers):
        if abs(t-self.time) > 1e-12 or h <= 0 or t+h > 3600.+1e-12:
            raise ValueError("invalid exchange clock")
        powers = np.asarray(powers, dtype=float)
        if powers.shape != (6,) or not np.all(np.isfinite(powers)) or np.any(powers < 0):
            raise ValueError("six finite nonnegative prescribed powers required")
        m = self.fmu
        m.setTime(t)
        m.setReal([self.variables[n].valueReference for n in POWERS], powers)

        def generated(_time, y):
            y = np.ascontiguousarray(y, dtype=np.float64)
            derivative = np.empty(8)
            m.setTime(float(_time))
            m.setContinuousStates(y.ctypes.data_as(PTR), 8)
            m.getDerivatives(derivative.ctypes.data_as(PTR), 8)
            assert np.all(np.isfinite(derivative))
            return derivative

        solution = solve_ivp(generated, (t, t+h), self.x, method="DOP853",
                             rtol=2e-12, atol=2e-12)
        assert solution.success, solution.message
        self.x = np.ascontiguousarray(solution.y[:, -1])
        m.setTime(t+h)
        m.setContinuousStates(self.x.ctypes.data_as(PTR), 8)
        assert m.completedIntegratorStep() == (False, False)
        self.time = t+h
        return self.output()

    def close(self):
        try:
            self.fmu.terminate()
        finally:
            self.fmu.freeInstance()
            shutil.rmtree(self.extracted)


def reference(ambient, period):
    state = np.r_[np.full(6, ambient), 0., 0.]
    values = [state.copy()]
    for duration, power in BLOCKS:
        solution = solve_ivp(rhs, (0., float(duration)), state, args=(power, ambient),
                             method="Radau", rtol=1e-11, atol=1e-11, dense_output=True)
        assert solution.success, solution.message
        local_times = np.arange(1, round(duration/period)+1)*period
        values.extend(solution.sol(local_times).T)
        state = solution.y[:, -1]
    return np.asarray(values)


def limits():
    a, b = ThermalExchange(25., "limits"), ThermalExchange(-10., "isolation")
    checks = []
    try:
        initial_b = b.output()
        first = a.advance(0., 1e-6, [0., 0., 0., .5, 0., 0.])
        assert abs((first[3]-25.)/1e-6-1.) <= 1e-4
        checks.append("independent junction initial slope 1 K/s")
        np.testing.assert_array_equal(b.output(), initial_b)
        checks.append("instance isolation and K/C initialization")
        a.fmu.reset()
        a.initialize()
        replay = a.advance(0., 1e-6, [0., 0., 0., .5, 0., 0.])
        np.testing.assert_array_equal(first, replay)
        checks.append("bitwise reset replay")
        equilibrium = b.advance(0., 1., [0.]*6)
        np.testing.assert_array_equal(equilibrium, initial_b)
        checks.append("unforced equilibrium")
    finally:
        a.close()
        b.close()
    return checks


def main():
    checks = limits()
    cases, pairs = [], {}
    for ambient in (-10., 25., 60.):
        for period in (1., .5):
            name = f"ambient-{ambient:g}-step-{period:g}"
            model = ThermalExchange(ambient, name)
            native = ThermalNetwork(period_s=period, ambient_c=ambient)
            rows = [model.output()]
            native_rows, powers_rows = [native.temperatures.copy()], [[0.]*6]
            t = 0.
            try:
                for duration, powers in BLOCKS:
                    for _ in range(round(duration/period)):
                        rows.append(model.advance(t, period, powers))
                        native_rows.append(native.advance(powers))
                        powers_rows.append(powers)
                        t += period
                actual = np.asarray(rows)
            finally:
                model.close()
            expected = reference(ambient, period)
            native_rows = np.asarray(native_rows)
            times = np.arange(len(actual))*period
            assert times[-1] == 3600. and np.all(np.diff(times) > 0)
            errors = np.max(np.abs(actual[:, :6]-expected[:, :6]), axis=0)
            native_errors = np.max(np.abs(actual[:, :6]-native_rows), axis=0)
            energy_errors = np.max(np.abs(actual[:, 6:8]-expected[:, 6:8]), axis=0)
            residual = balance(actual[:, :8], ambient)
            audited_flows = np.asarray([flows(row[:6], ambient) for row in actual])
            flow_errors = np.max(np.abs(actual[:, 8:14]-audited_flows), axis=0)
            corrupted = actual[:, :8].copy()
            corrupted[len(actual)//2, 6] += 10.
            assert np.max(np.abs(balance(corrupted, ambient))) > 1e-5
            data = np.column_stack([times, actual, native_rows, expected, powers_rows, residual])
            columns = ["time_s", *TEMPERATURES, "input_energy_j", "ambient_energy_j",
                       *[f"link_{i}_w" for i in range(1, 6)], "heat_to_ambient_w",
                       *["native_"+n for n in TEMPERATURES],
                       *["reference_"+n for n in TEMPERATURES],
                       "reference_input_energy_j", "reference_ambient_energy_j",
                       *[f"previous_power_{i}_w" for i in range(1, 7)], "balance_j"]
            path = OUT / (name+".csv")
            np.savetxt(path, data, delimiter=",", header=",".join(columns), comments="")
            passed = bool(np.all(np.isfinite(data)) and np.max(errors) <= 2e-7
                          and np.max(native_errors) <= 2e-7 and np.max(energy_errors) <= 1e-5
                          and np.max(flow_errors) <= 2e-7
                          and np.max(np.abs(residual)) <= 1e-5
                          and np.min(actual[:, :6]) >= ambient-1e-9)
            sample_indices = list(range(0, len(data), max(1, len(data)//240)))
            if sample_indices[-1] != len(data)-1:
                sample_indices.append(len(data)-1)
            case = dict(id=name, ambient_c=ambient, period_s=period, rows=len(data),
                        passed=passed, reference_errors_k=errors.tolist(),
                        native_errors_k=native_errors.tolist(),
                        energy_errors_j=energy_errors.tolist(),
                        flow_errors_w=flow_errors.tolist(),
                        max_reference_error_k=float(max(errors)),
                        max_native_error_k=float(max(native_errors)),
                        peak_balance_j=float(np.max(np.abs(residual))),
                        peak_temperatures_c=np.max(actual[:, :6], axis=0).tolist(),
                        csv_sha256=digest(path), columns=columns,
                        samples=data[sample_indices].tolist())
            cases.append(case)
            pairs[(ambient, period)] = actual[:, :6]
            print("msl-case: "+json.dumps({k: v for k, v in case.items()
                                         if k not in {"samples", "columns"}}), flush=True)
    differences = {str(a): float(np.max(np.abs(pairs[(a, 1.)]-pairs[(a, .5)][::2])))
                   for a in (-10., 25., 60.)}
    archive = OUT / "OEALMSLThermal.fmu"
    with zipfile.ZipFile(archive) as z:
        assert "resources/oeal-licenses/MSL-BSD3.txt" in z.namelist()
        assert "resources/oeal-licenses/compiler-package-copyright.txt" in z.namelist()
        binaries = {n: hashlib.sha256(z.read(n)).hexdigest()
                    for n in z.namelist() if n.endswith(".so")}
        assert binaries and any(n.startswith("sources/") for n in z.namelist())
        (OUT / "generated-modelDescription.xml").write_bytes(z.read("modelDescription.xml"))
    metadata = dict(build=json.loads((OUT / "build-provenance.json").read_text()),
                    source_sha256=digest(ROOT / "models/modelica/OEALMSLThermal.mo"),
                    fmu_sha256=digest(archive), binary_sha256=binaries,
                    commit=subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                   text=True).strip(),
                    command="python benchmarks/validate_msl_thermal.py")
    result = dict(passed=all(c["passed"] for c in cases) and max(differences.values()) <= 2e-7,
                  cases=cases, boundary_checks=checks, common_time_difference_k=differences,
                  metadata=metadata, evidence_level="model_simulated", duration_s=3600,
                  blocks=BLOCKS, capacities_j_per_k=CAPACITY.tolist(),
                  source="fixed synthetic prescribed loss replay; actual MSL components")
    (OUT / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print("msl-summary: "+json.dumps({k: v for k, v in result.items() if k != "cases"}), flush=True)
    assert result["passed"], "frozen MSL thermal gate failed"


if __name__ == "__main__":
    main()
