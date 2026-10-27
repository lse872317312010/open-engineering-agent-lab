"""Execute generated ModelExchange equations and independently audit all endpoints."""

import ctypes
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import fmpy
import numpy as np
from fmpy import extract, read_model_description
from fmpy.fmi2 import FMU2Model
from joint_fmi_reference import balance, initial, schedule
from scipy.integrate import solve_ivp
from validate_joint_fmi import CASES, NAMES, build, oracle, simulate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/openmodelica"
POINTER = ctypes.POINTER(ctypes.c_double)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Exchange:
    def __init__(self, archive, name):
        self.description = read_model_description(str(archive), validate=True)
        md = self.description
        assert md.fmiVersion == "2.0" and md.modelExchange is not None
        assert md.numberOfContinuousStates == 12 and md.numberOfEventIndicators == 0
        self.variables = {v.name: v for v in md.modelVariables}
        for name_ in NAMES[:12]+["shaft_nm"]:
            assert self.variables[name_].causality == "output"
            assert self.variables[name_].type == "Real"
        for name_ in NAMES[12:16]:
            assert self.variables[name_].causality == "input"
            assert self.variables[name_].type == "Real"
        self.extracted = extract(str(archive))
        self.fmu = FMU2Model(guid=md.guid, unzipDirectory=self.extracted,
                            modelIdentifier=md.modelExchange.modelIdentifier, instanceName=name)
        self.fmu.instantiate()
        self.initialize()

    def initialize(self):
        m = self.fmu
        m.setupExperiment(startTime=0., stopTime=.08, tolerance=1e-11)
        m.enterInitializationMode()
        m.exitInitializationMode()
        for _ in range(10):
            event = m.newDiscreteStates()
            assert not event[1] and not event[4], event
            if not event[0]:
                break
        else:
            raise AssertionError("initialization event iteration did not converge")
        m.enterContinuousTimeMode()
        self.x = np.empty(12)
        m.getContinuousStates(self.x.ctypes.data_as(POINTER), 12)
        np.testing.assert_allclose(self.output()[:12], initial(), atol=1e-13, rtol=0)

    def output(self):
        refs = [self.variables[n].valueReference for n in NAMES[:12]+["shaft_nm"]]
        return np.asarray(self.fmu.getReal(refs))

    def advance(self, t, h, inputs):
        m = self.fmu
        m.setTime(t)
        m.setReal([self.variables[n].valueReference for n in NAMES[12:16]], inputs)

        def generated_rhs(time, values):
            values = np.ascontiguousarray(values, dtype=np.float64)
            derivative = np.empty(12)
            m.setTime(float(time))
            m.setContinuousStates(values.ctypes.data_as(POINTER), 12)
            m.getDerivatives(derivative.ctypes.data_as(POINTER), 12)
            assert np.all(np.isfinite(derivative))
            return derivative

        result = solve_ivp(generated_rhs, (t, t+h), self.x, method="DOP853",
                           rtol=2e-12, atol=2e-13)
        assert result.success, result.message
        self.x = np.ascontiguousarray(result.y[:, -1])
        m.setTime(t+h)
        m.setContinuousStates(self.x.ctypes.data_as(POINTER), 12)
        assert m.completedIntegratorStep() == (False, False)
        return self.output()

    def close(self):
        import shutil
        try:
            self.fmu.terminate()
        finally:
            self.fmu.freeInstance()
            shutil.rmtree(self.extracted)


def boundary_checks(archive):
    a, b = Exchange(archive, "limits"), Exchange(archive, "independent")
    checks = []
    try:
        y = a.advance(0., 1e-8, (1., 0., 0., 25.))
        assert abs(y[0]/1e-8-1250.) < .003
        assert abs((y[8]-25.)/1e-8-1.) < 1e-5
        checks.extend(["independent RL initial slope", "pure board heat initial slope"])
        np.testing.assert_array_equal(b.output()[:12], initial())
        checks.append("instance isolation")
        a.fmu.reset()
        a.initialize()
        again = a.advance(0., 1e-8, (1., 0., 0., 25.))
        np.testing.assert_array_equal(y, again)
        checks.append("bitwise reset replay")
        equilibrium = b.advance(0., .001, (0., 0., 0., 0.))
        np.testing.assert_array_equal(equilibrium[:12], initial())
        checks.append("unforced equilibrium")
    finally:
        a.close()
        b.close()
    return checks


def main():
    archive = OUT / "OEALJointExchange.fmu"
    extracted_c, metadata_c = build()
    checks = boundary_checks(archive)
    description = read_model_description(str(archive), validate=True)
    with zipfile.ZipFile(archive) as z:
        notices = [n for n in z.namelist() if
                   any(p in n.lower() for p in ("license", "copyright", "copying"))]
        source_names = [n for n in z.namelist() if n.startswith("sources/")]
        assert source_names, "retain generated/runtime source with the FMU"
        notice_sources = [n for n in source_names if n.endswith((".c", ".h"))
                          and b"Copyright" in z.read(n)]
        assert notice_sources, "missing runtime source copyright headers"
        binaries = {n: hashlib.sha256(z.read(n)).hexdigest()
                    for n in z.namelist() if n.endswith(".so")}
        assert binaries
        (OUT / "generated-modelDescription.xml").write_bytes(z.read("modelDescription.xml"))
    cases = []
    for name in CASES:
        model = Exchange(archive, name)
        try:
            rows = [model.output()]
            for t, h, u in schedule(name):
                rows.append(model.advance(t, h, u))
            actual = np.asarray(rows)
        finally:
            model.close()
        reference = oracle(name)
        native = simulate(extracted_c, name, 5e-6)
        times = np.array([0.] + [t+h for t, h, _ in schedule(name)])
        assert np.all(np.diff(times) > 0)
        errors = np.max(np.abs(actual[:, :12]-reference), axis=0)
        c_errors = np.max(np.abs(actual[:, :9]-native[:, :9]), axis=0)
        residual = balance(actual[:, :12])
        shaft = 80*(actual[:, 2]/10-actual[:, 4])+.15*(actual[:, 3]/10-actual[:, 5])
        shaft_error = float(np.max(np.abs(actual[:, 12]-shaft)))
        corrupt = actual[:, :12].copy()
        corrupt[len(corrupt)//2, 9] += .001
        assert np.max(np.abs(balance(corrupt))) > 2e-6
        inputs = np.asarray([u for _, _, u in schedule(name)] + [schedule(name)[-1][2]])
        data = np.column_stack([times, actual, reference, native, inputs, residual])
        columns = ["time_s", *NAMES[:12], "shaft_nm",
                   *["reference_"+n for n in NAMES[:12]],
                   *["c_"+n for n in NAMES[:12]], *NAMES[12:16], "balance_j"]
        path = OUT / (name+".csv")
        np.savetxt(path, data, delimiter=",", header=",".join(columns), comments="")
        passed = bool(np.all(np.isfinite(data)) and np.all(errors <= 2e-5)
                      and np.all(c_errors <= 2e-5) and shaft_error <= 2e-5
                      and np.max(np.abs(residual)) <= 2e-6)
        case = dict(id=name, passed=passed, state_errors=errors.tolist(),
                    c_state_errors=c_errors.tolist(), shaft_error_nm=shaft_error,
                    max_state_error=float(max(errors)), max_c_state_error=float(max(c_errors)),
                    peak_balance_j=float(np.max(np.abs(residual))),
                    rows=len(times), csv_sha256=digest(path), columns=columns,
                    samples=data[::10].tolist())
        cases.append(case)
        print("modelica-case: "+json.dumps({k: v for k, v in case.items()
                                           if k not in {"samples", "columns"}}), flush=True)
    metadata = dict(compiler=json.loads((OUT / "compiler-image.json").read_text()),
                    source_sha256=digest(ROOT / "models/modelica/OEALJointExchange.mo"),
                    fmu_sha256=digest(archive), binary_sha256=binaries,
                    guid=description.guid, generation_tool=description.generationTool,
                    fmpy=fmpy.__version__, c_model=metadata_c,
                    source_entries=len(source_names), copyright_sources=notice_sources,
                    notice_entries=notices,
                    commit=subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                   text=True).strip())
    result = dict(passed=all(c["passed"] for c in cases), cases=cases,
                  boundary_checks=checks, metadata=metadata,
                  evidence_level="model_simulated",
                  scope="fixed synthetic model; actual ModelExchange export/import; host DOP853")
    (OUT / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print("modelica-summary: "+json.dumps(dict(passed=result["passed"],
                                              boundary_checks=checks, metadata=metadata)))
    assert result["passed"], "frozen cross-implementation gate failed"


if __name__ == "__main__":
    main()
