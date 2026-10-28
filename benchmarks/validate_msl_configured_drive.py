"""Configured one-second actual-drive cases and independent initial-boundary checks."""
import hashlib
import json
from pathlib import Path

import numpy as np
import validate_msl_cooling_drive as suite
from msl_cooling_configuration_reference import boundary
from msl_cooling_drive_adapter import MSLCoolingDrive
from msl_cooling_drive_reference import BASE, CASES

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/msl-configured-drive"
CONFIGURED_CASES = [
    (name, changes | (dict(duration_s=.2) if name in {"linear-limit", "fan-varying"} else {}),
     area, varying) for name, changes, area, varying in CASES
]
PARAMETERS = {name:dict(initial_temperatures_c=[25.]*6) for name in
              ("radiation-feedback", "linear-limit", "radiation-frozen", "radiation-fine")}
PARAMETERS.update({
    "fan-varying":dict(initial_temperatures_c=[80.,70.,60.,100.,65.,50.]),
    "pwm-feedback":dict(ambient_c=-10.),
    "regeneration":dict(ambient_c=60.),
})


def initial_checks():
    checks = []
    for name, ambient, initial in (("heat-import", 60., 25.), ("equilibrium", 60., 60.)):
        provider = MSLCoolingDrive(OUT / (name+".csv.gz"), .001, .02,
                                   ambient_c=ambient, initial_temperatures_c=[initial]*6)
        try:
            rate = provider.evaluate(0., np.full(6, initial), np.zeros(6), 0., 0.,
                                     branch_energy_j=[0.]*3, accepted=True)
            expected = boundary([initial]*6, ambient, 1/3, .02)
            np.testing.assert_allclose(rate[8:], expected, atol=2e-7, rtol=0)
            if name == "heat-import":
                assert np.all(rate[8:] < 0) and rate[2] > 0 and rate[5] > 0
            else:
                np.testing.assert_array_equal(rate, np.zeros(11))
            checks.append(dict(name=name, ambient_c=ambient, initial_c=initial,
                               branch_w=rate[8:].tolist(), passed=True))
        finally:
            provider.close()
    return checks


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = initial_checks()
    suite.main(cases=CONFIGURED_CASES, base=BASE | dict(duration_s=1.),
               destination=OUT, parameters=PARAMETERS,
               scope="configured ambient/initial states, 0.02-1s actual drive; no endurance")
    path = OUT / "validation.json"
    report = json.loads(path.read_text())
    cold = [c for c in report["cases"] if c["id"] in
            {"radiation-feedback", "radiation-fine"}]
    growth = all(c["winding_rise_k"] >= .05 and c["resistance_growth_ohm"] >= 1e-5
                 for c in cold)
    initial_errors = {}
    for c in report["cases"]:
        data = np.genfromtxt(OUT / c["id"] / "coupling.csv", delimiter=",", names=True)
        first = data[0]
        actual = [first[n] for n in ("case_w", "convection_w", "radiation_w")]
        expected = boundary(c["initial_temperatures_c"], c["ambient_c"], 1/3, c["area_m2"])
        initial_errors[c["id"]] = float(np.max(abs(np.asarray(actual)-expected)))
    for name in ("benchmarks/validate_msl_configured_drive.py",
                 "benchmarks/msl_cooling_configuration_reference.py",
                 "docs/msl-configured-drive-contract.md"):
        report["metadata"]["source_sha256"][name] = hashlib.sha256(
            (ROOT / name).read_bytes()).hexdigest()
    report["configured_initial_checks"] = checks
    report["configured_initial_flow_errors_w"] = initial_errors
    report["cold_start_growth_passed"] = bool(growth)
    report["passed"] = bool(report["passed"] and growth and max(initial_errors.values()) <= 2e-7)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("configured-drive-summary: "+json.dumps(
        {k:v for k,v in report.items() if k != "cases"}), flush=True)
    assert report["passed"], "fixed configurable one-second coupling gate failed"


if __name__ == "__main__":
    main()
