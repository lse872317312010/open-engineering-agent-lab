"""One-hour nonlinear MSL cooling, independent Radau, and fan transition audit."""

import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
from fmpy import extract, read_model_description
from fmpy.fmi2 import FMU2Model
from msl_cooling_reference import (
    CASES,
    SIGMA,
    balance,
    conductance,
    flow_values,
    powers,
    rhs,
    segments,
)
from scipy.integrate import solve_ivp
from validate_msl_thermal import PTR, TEMPERATURES

from oeal.refined_thermal import ThermalNetwork

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/msl-cooling"
J_NAMES = ["input_energy_j", "ambient_energy_j", "case_energy_j",
           "convection_energy_j", "radiation_energy_j"]
FLOW_NAMES = [f"link_{i}_w" for i in range(1, 6)]+[
    "case_heat_w", "convection_heat_w", "radiation_heat_w", "heat_to_ambient_w"]
OUTPUTS = ([f"temperature_c[{i}]" for i in range(1, 7)]+J_NAMES
           + [f"link_w[{i}]" for i in range(1, 6)]+FLOW_NAMES[5:]+["sigma_w_m2_k4"])
INPUTS = [f"power_w[{i}]" for i in range(1, 7)]+["convection_w_per_k"]
CANONICAL = [0,1,2,3,4,5,6,8,9,10]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CoolingExchange:
    def __init__(self, case):
        self.case = dict(case)
        assert -10 <= case["ambient_c"] <= 60 and 0 <= case["area_m2"] <= .1
        archive = OUT / "OEALMSLCooling.fmu"
        md = read_model_description(str(archive), validate=True)
        assert md.modelExchange and md.fmiVersion == "2.0"
        assert md.numberOfContinuousStates == 10 and md.numberOfEventIndicators == 0
        self.variables = {v.name: v for v in md.modelVariables}
        for n, unit in zip(OUTPUTS[:20], ["degC"]*6+["J"]*5+["W"]*9, strict=True):
            assert self.variables[n].causality == "output" and self.variables[n].unit == unit
        for n in INPUTS:
            assert self.variables[n].causality == "input"
        self.extracted = extract(str(archive))
        self.fmu = FMU2Model(guid=md.guid, unzipDirectory=self.extracted,
                            modelIdentifier=md.modelExchange.modelIdentifier,
                            instanceName=case["id"])
        self.fmu.instantiate()
        self.initialize()

    def initialize(self):
        m = self.fmu
        c = self.case
        m.setupExperiment(startTime=0., stopTime=3600., tolerance=1e-11)
        m.enterInitializationMode()
        m.setReal([self.variables[n].valueReference for n in
                   ("ambient_k", "radiation_area_m2")], [c["ambient_c"]+273.15, c["area_m2"]])
        m.setReal([self.variables[n].valueReference for n in INPUTS], [0.]*6+[1/3])
        m.exitInitializationMode()
        for _ in range(10):
            e = m.newDiscreteStates()
            assert not e[1] and not e[4]
            if not e[0]:
                break
        else:
            raise AssertionError("initialization did not converge")
        m.enterContinuousTimeMode()
        self.x = np.empty(10)
        m.getContinuousStates(self.x.ctypes.data_as(PTR), 10)
        self.time = 0.
        np.testing.assert_allclose(self.output()[:11],
                                   [c["ambient_c"]]*6+[0.]*5, atol=1e-12, rtol=0)

    def output(self):
        return np.asarray(self.fmu.getReal([self.variables[n].valueReference for n in OUTPUTS]))

    def advance(self, t, h, power, gc):
        assert abs(t-self.time) < 1e-12 and 0 < h <= 1. and t+h <= 3600.+1e-12
        assert np.all(np.isfinite(power)) and min(power) >= 0 and 0 <= gc <= 2.
        m = self.fmu
        m.setTime(t)
        m.setReal([self.variables[n].valueReference for n in INPUTS], [*power, gc])

        def generated(time, state):
            state = np.ascontiguousarray(state, dtype=float)
            rate = np.empty(10)
            m.setTime(float(time))
            m.setContinuousStates(state.ctypes.data_as(PTR), 10)
            m.getDerivatives(rate.ctypes.data_as(PTR), 10)
            assert np.all(np.isfinite(rate))
            return rate

        solution = solve_ivp(generated, (t, t+h), self.x, method="DOP853",
                             rtol=2e-12, atol=2e-12)
        assert solution.success, solution.message
        self.x = np.ascontiguousarray(solution.y[:, -1])
        m.setTime(t+h)
        m.setContinuousStates(self.x.ctypes.data_as(PTR), 10)
        assert m.completedIntegratorStep() == (False, False)
        self.time = t+h
        return self.output()

    def point_sink(self, kelvin, gc):
        archive = OUT / "OEALMSLCooling.fmu"
        with zipfile.ZipFile(archive) as z:
            xml = ElementTree.fromstring(z.read("modelDescription.xml"))
        variables = list(xml.find("ModelVariables"))
        state_names = []
        for unknown in xml.findall("ModelStructure/Derivatives/Unknown"):
            derivative = variables[int(unknown.attrib["index"])-1]
            state_names.append(variables[int(derivative.find("Real").attrib["derivative"])-1]
                               .attrib["name"])
        target = self.variables["node[6].T"]
        matches = [i for i, n in enumerate(state_names)
                   if self.variables[n].valueReference == target.valueReference]
        assert len(matches) == 1 and target.unit == "K"
        values = self.x.copy()
        values[matches[0]] = kelvin
        self.fmu.setTime(0.)
        self.fmu.setContinuousStates(values.ctypes.data_as(PTR), 10)
        self.fmu.setReal([self.variables[n].valueReference for n in INPUTS], [0.]*6+[gc])
        return self.output()

    def close(self):
        try:
            self.fmu.terminate()
        finally:
            self.fmu.freeInstance()
            shutil.rmtree(self.extracted)


def reference(case):
    state = np.r_[np.full(6, case["ambient_c"]), np.zeros(4)]
    result = [state.copy()]
    for start, stop in segments():
        power, gc = powers(start), conductance(start, case)
        solution = solve_ivp(rhs, (start, stop), state,
                             args=(power, case["ambient_c"], case["area_m2"], gc),
                             method="Radau", rtol=1e-11, atol=1e-11, dense_output=True)
        assert solution.success, solution.message
        count = round((stop-start)/case["period_s"])
        result.extend(solution.sol(start+np.arange(1, count+1)*case["period_s"]).T)
        state = solution.y[:, -1]
    return np.asarray(result)


def limit_checks():
    c = dict(id="limits", ambient_c=26.85, area_m2=.02, period_s=1., fan=False)
    a, b = CoolingExchange(c), CoolingExchange(CASES[-1])
    checks = []
    try:
        initial = b.output()
        hot = a.point_sink(400., 1/3)
        assert abs(hot[17]-100/3) <= 1e-10
        assert abs(hot[18]-.02*SIGMA*17_500_000_000) <= 1e-10
        checks.extend(["400K/300K analytic convection", "400K/300K analytic radiation"])
        zero = a.point_sink(400., 0.)
        assert zero[17] == 0.
        checks.append("zero convection conductance")
        cold = a.point_sink(200., 1/3)
        assert cold[17] < 0 and cold[18] < 0
        checks.append("signed heat import from warmer environment")
        np.testing.assert_array_equal(b.output(), initial)
        checks.append("instance isolation and K/C initialization")
        a.fmu.reset()
        a.initialize()
        first = a.advance(0., 1., [0.,0.,0.,.5,0.,0.], 1/3)
        a.fmu.reset()
        a.initialize()
        replay = a.advance(0., 1., [0.,0.,0.,.5,0.,0.], 1/3)
        np.testing.assert_array_equal(first, replay)
        checks.append("bitwise reset replay")
        equilibrium = b.advance(0., 1., [0.]*6, 1/3)
        np.testing.assert_array_equal(equilibrium, initial)
        checks.append("unforced equilibrium")
    finally:
        a.close()
        b.close()
    return checks


def main():
    checks = limit_checks()
    reports, all_rows = [], {}
    for case in CASES:
        model = CoolingExchange(case)
        native = ThermalNetwork(period_s=case["period_s"], ambient_c=case["ambient_c"])
        actual, held = [model.output()], [[0.]*6+[1/3]]
        native_rows = [native.temperatures.copy()]
        try:
            for tick in range(round(3600/case["period_s"])):
                t = tick*case["period_s"]
                power, gc = powers(t), conductance(t, case)
                actual.append(model.advance(t, case["period_s"], power, gc))
                held.append([*power, gc])
                if case["id"] == "linear-limit":
                    native_rows.append(native.advance(power))
            actual = np.asarray(actual)
        finally:
            model.close()
        expected = reference(case)
        canonical = actual[:, CANONICAL]
        temperature_errors = np.max(abs(canonical[:, :6]-expected[:, :6]), axis=0)
        energy_errors = np.max(abs(canonical[:, 6:]-expected[:, 6:]), axis=0)
        reference_total = expected[:, 7:10].sum(axis=1)
        total_energy_error = float(max(abs(actual[:, 7]-reference_total)))
        audited = np.asarray([flow_values(r[:6], case["ambient_c"], case["area_m2"], h[6])
                              for r, h in zip(actual, held, strict=True)])
        flow_errors = np.max(abs(actual[:, 11:19]-audited), axis=0)
        residual = balance(canonical, case["ambient_c"])
        sigma_error = float(max(abs(actual[:, 20]-SIGMA)))
        omitted = canonical.copy()
        omitted[:, 9] = 0.
        missing_fault = bool(max(abs(balance(omitted, case["ambient_c"]))) > 1e-5)
        wrong_radiation = case["area_m2"]*SIGMA*(
            actual[:, 5]**4-case["ambient_c"]**4)
        celsius_fault = bool(max(abs(actual[:, 18]-wrong_radiation)) > 2e-7)
        if case["area_m2"] == 0:
            missing_fault = celsius_fault = None
        times = np.arange(len(actual))*case["period_s"]
        assert times[-1] == 3600. and np.all(np.diff(times) > 0)
        data = np.column_stack([
            times, actual[:, :20], expected[:, :6], expected[:, 6:10], reference_total,
            held, residual,
        ])
        columns = ["time_s", *TEMPERATURES, *J_NAMES, *FLOW_NAMES,
                   *["reference_"+n for n in TEMPERATURES],
                   "reference_input_j", "reference_case_j", "reference_convection_j",
                   "reference_radiation_j", "reference_ambient_j",
                   *[f"previous_power_{i}_w" for i in range(1, 7)], "previous_gc_w_k", "balance_j"]
        native_error = None
        if case["id"] == "linear-limit":
            native_error = float(np.max(abs(actual[:, :6]-np.asarray(native_rows))))
            data = np.column_stack([data, native_rows])
            columns += ["native_"+n for n in TEMPERATURES]
        path = OUT / (case["id"]+".csv")
        np.savetxt(path, data, delimiter=",", header=",".join(columns), comments="")
        passed = bool(np.all(np.isfinite(data)) and max(temperature_errors) <= 2e-7
                      and max(energy_errors) <= 1e-5 and total_energy_error <= 1e-5
                      and max(flow_errors) <= 2e-7 and max(abs(residual)) <= 1e-5
                      and max(abs(actual[:, 7]-actual[:, 8:11].sum(axis=1))) <= 1e-9
                      and max(abs(actual[:, 19]-actual[:, 16:19].sum(axis=1))) <= 1e-9
                      and np.min(actual[:, :6]) >= case["ambient_c"]-1e-9
                      and sigma_error <= 1e-20 and missing_fault is not False
                      and celsius_fault is not False
                      and (native_error is None or native_error <= 2e-7))
        stride = max(1, len(data)//240)
        indices = sorted(set(range(0, len(data), stride)) | {len(data)-1})
        report = dict(**case, passed=passed, rows=len(actual),
                      temperature_errors_k=temperature_errors.tolist(),
                      max_reference_error_k=float(max(temperature_errors)),
                      energy_errors_j=energy_errors.tolist(),
                      total_energy_error_j=total_energy_error, flow_errors_w=flow_errors.tolist(),
                      peak_balance_j=float(max(abs(residual))), sigma_error=sigma_error,
                      native_error_k=native_error, peak_sink_c=float(max(actual[:, 5])),
                      celsius_radiation_fault_detected=celsius_fault,
                      omitted_radiation_fault_detected=missing_fault, csv_sha256=digest(path),
                      columns=columns, samples=data[indices].tolist())
        reports.append(report)
        all_rows[case["id"]] = actual
        if case["area_m2"] > 0:
            np.savetxt(OUT / (case["id"]+"-faults.csv"),
                       np.column_stack([times, actual[:, 18], wrong_radiation,
                                        balance(omitted, case["ambient_c"])]), delimiter=",",
                       header="time_s,actual_radiation_w,wrong_celsius_w,omitted_balance_j",
                       comments="")
        print("msl-cooling-case: "+json.dumps({k: v for k, v in report.items()
                                              if k not in {"samples", "columns"}}), flush=True)
    linear, nominal = all_rows["linear-limit"], all_rows["radiation"]
    fine = all_rows["radiation-fine"][::2]
    fan = all_rows["fan-loss-recovery"]
    comparisons = dict(
        common_time_difference_k=float(np.max(abs(nominal[:, :6]-fine[:, :6]))),
        radiation_above_linear_k=float(np.max(nominal[:, :6]-linear[:, :6])),
        sink_peak_reduction_k=float(max(linear[:, 5])-max(nominal[:, 5])),
        fan_weakening_sink_rise_k=float(fan[2400, 5]-nominal[2400, 5]),
        recovered_sink_drop_k=float(fan[2400, 5]-fan[-1, 5]),
    )
    comparison_passed = (comparisons["common_time_difference_k"] <= 2e-7
                         and comparisons["radiation_above_linear_k"] <= 2e-7
                         and comparisons["sink_peak_reduction_k"] >= .5
                         and comparisons["fan_weakening_sink_rise_k"] >= .5
                         and comparisons["recovered_sink_drop_k"] >= .5)
    archive = OUT / "OEALMSLCooling.fmu"
    with zipfile.ZipFile(archive) as z:
        binaries = {n: hashlib.sha256(z.read(n)).hexdigest()
                    for n in z.namelist() if n.endswith(".so")}
        assert binaries and "resources/oeal-licenses/MSL-BSD3.txt" in z.namelist()
        (OUT / "generated-modelDescription.xml").write_bytes(z.read("modelDescription.xml"))
    result = dict(passed=all(c["passed"] for c in reports) and comparison_passed,
                  cases=reports, comparisons=comparisons, boundary_checks=checks, sigma=SIGMA,
                  metadata=dict(build=json.loads((OUT / "build-provenance.json").read_text()),
                                fmu_sha256=digest(archive), binary_sha256=binaries,
                                source_sha256=digest(ROOT / "models/modelica/OEALMSLCooling.mo"),
                                commit=subprocess.check_output(["git","rev-parse","HEAD"],
                                                               text=True).strip()),
                  evidence_level="model_simulated",
                  scope="one-hour prescribed-loss nonlinear cooling; no motor/robot endurance")
    (OUT / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print("msl-cooling-summary: "+json.dumps({k: v for k, v in result.items() if k != "cases"}),
          flush=True)
    assert result["passed"], "fixed nonlinear cooling gate failed"


if __name__ == "__main__":
    main()
