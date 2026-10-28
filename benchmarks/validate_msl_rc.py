"""Actual drive with real configurable MSL RC, parameter faults and legacy-asset pairing."""
import hashlib
import json
from pathlib import Path

import numpy as np
import validate_msl_cooling_drive as suite
from msl_cooling_drive_adapter import MSLCoolingDrive
from msl_cooling_drive_reference import BASE, CASES
from msl_parametric_drive_adapter import MSLParametricDrive
from msl_rc_drive_reference import ParametricPython
from msl_rc_reference import CAPACITY, RESISTANCE

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/msl-rc"
PARAMETERS = {name:dict(capacities_j_per_k=CAPACITY.tolist(),
                        link_resistances_k_per_w=RESISTANCE.tolist(),
                        case_resistance_k_per_w=2.) for name, *_ in CASES}
PARAMETERS["linear-limit"].update(
    capacities_j_per_k=(2*CAPACITY).tolist(),
    link_resistances_k_per_w=(2*RESISTANCE).tolist(), case_resistance_k_per_w=4.)
PARAMETERS["fan-varying"].update(
    capacities_j_per_k=[90.,80.,250.,1.,35.,180.],
    link_resistances_k_per_w=[.3,.8,1.5,.6,2.], case_resistance_k_per_w=1.,
    initial_temperatures_c=[80.,70.,60.,100.,65.,50.])
PARAMETERS["pwm-feedback"].update(
    capacities_j_per_k=(.5*CAPACITY).tolist(),
    link_resistances_k_per_w=(.75*RESISTANCE).tolist(), case_resistance_k_per_w=1.5,
    ambient_c=-10.)
PARAMETERS["regeneration"].update(
    capacities_j_per_k=(.9*CAPACITY).tolist(),
    link_resistances_k_per_w=(1.25*RESISTANCE).tolist(), case_resistance_k_per_w=2.5,
    ambient_c=60.)


def main():
    suite.main(destination=OUT, parameters=PARAMETERS,
               provider_factory=MSLParametricDrive, reference_factory=ParametricPython,
               build_provenance=ROOT / "outputs/msl-parametric/build-provenance.json",
               scope="configured C/R, 0.02-0.1s actual drive; independent 4-8s zero-input limits")
    path = OUT / "validation.json"
    report = json.loads(path.read_text())
    # Default new FMU must match the original fixed real MSL FMU under the same real drive.
    provider = MSLCoolingDrive(OUT / "fixed-asset-rhs.csv.gz", BASE["duration_s"], .02)
    try:
        control, energy, fine = suite.old.simulate(BASE, provider)
        fixed_metadata = provider.describe()
    finally:
        provider.close()
    suite.save(OUT / "fixed-control.csv", suite.CONTROL_COLUMNS, control)
    suite.save(OUT / "fixed-energy.csv", suite.ENERGY_COLUMNS, energy)
    suite.save(OUT / "fixed-waveforms.csv.gz", suite.old.FINE_COLUMNS, fine)
    actual_c = np.loadtxt(OUT / "radiation-feedback/control.csv", delimiter=",", skiprows=1)
    actual_e = np.loadtxt(OUT / "radiation-feedback/energy.csv", delimiter=",", skiprows=1)
    temperature = max(float(max(abs(suite.col(actual_e, suite.ENERGY_COLUMNS, n)
                                   -suite.col(energy, suite.ENERGY_COLUMNS, n))))
                      for n in suite.TEMPERATURES)
    electric = {n:float(max(abs(suite.col(actual_c, suite.CONTROL_COLUMNS, n)
                                -suite.col(control, suite.CONTROL_COLUMNS, n))))
                for n in ("id_a", "iq_a", "motor_speed_rad_s", "vd_command_v", "vq_command_v")}
    fixed_audit, accepted = suite.audit_rhs(OUT / "fixed-asset-rhs.csv.gz", .02, False)
    preview = np.genfromtxt(OUT / "radiation-feedback/coupling.csv", delimiter=",", names=True)
    branch_error = float(np.max(abs(np.column_stack([
        preview[n] for n in ("case_out_j", "convection_out_j", "radiation_out_j")])
        -accepted[:, 16:19])))
    ambient_error = float(max(abs(suite.col(actual_e, suite.ENERGY_COLUMNS, "ambient_j")
                                  -suite.col(energy, suite.ENERGY_COLUMNS, "ambient_j"))))
    paired = dict(passed=bool(temperature <= 2e-7 and max(electric.values()) <= 2e-5
                              and branch_error <= 1e-7 and ambient_error <= 1e-7
                              and fixed_audit["passed"]),
                  branch_error_j=branch_error, ambient_error_j=ambient_error,
                  fixed_rhs_audit=fixed_audit,
                  temperature_error_k=temperature, electric_errors=electric,
                  fixed_fmu=fixed_metadata)
    faults = []
    for c in report["cases"]:
        target = OUT / c["id"]
        e = np.loadtxt(target / "energy.csv", delimiter=",", skiprows=1)
        temperatures = np.column_stack([suite.col(e, suite.ENERGY_COLUMNS, n)
                                        for n in suite.TEMPERATURES])
        heat = sum(suite.col(e, suite.ENERGY_COLUMNS, n) for n in
                   ("copper_j", "conduction_j", "auxiliary_device_j", "rotor_friction_j"))
        ambient = suite.col(e, suite.ENERGY_COLUMNS, "ambient_j")
        wrong = heat-(temperatures-temperatures[0]) @ CAPACITY-ambient
        configured = np.asarray(c["capacities_j_per_k"])
        applicable = not np.array_equal(configured, CAPACITY)
        detected = bool(max(abs(wrong)) > 1e-7) if applicable else None
        suite.save(target / "fault-default-capacity.csv", ["time_s", "wrong_balance_j"],
                   np.column_stack([e[:, 0], wrong]))
        # At actual temperatures and port inputs, default R must fail for changed R.
        reference = ParametricPython(c["area_m2"], c["varying_gc"], **PARAMETERS[c["id"]])
        t = np.asarray(c["initial_temperatures_c"])
        q = np.zeros(6)
        correct = reference.independent_rates(t, q, 1/3, c["area_m2"], c["ambient_c"])
        wrong_reference = ParametricPython(c["area_m2"], c["varying_gc"],
                                           ambient_c=c["ambient_c"],
                                           capacities_j_per_k=configured)
        wrong_r = wrong_reference.independent_rates(t, q, 1/3, c["area_m2"], c["ambient_c"])
        r_applicable = (not np.array_equal(PARAMETERS[c["id"]]["link_resistances_k_per_w"],
                                          RESISTANCE)
                        or PARAMETERS[c["id"]]["case_resistance_k_per_w"] != 2.)
        r_detected = bool(np.max(abs(correct-wrong_r)) > 2e-7) if r_applicable else None
        faults.append(dict(id=c["id"], wrong_capacity_detected=detected,
                           wrong_resistance_detected=r_detected))
    limits = json.loads((OUT / "linear-limits.json").read_text())
    for source in ("benchmarks/msl_parametric_drive_adapter.py", "benchmarks/msl_rc_parameters.py",
                   "benchmarks/msl_rc_reference.py", "benchmarks/msl_rc_drive_reference.py",
                   "benchmarks/validate_msl_rc.py", "models/modelica/OEALMSLParametric.mo",
                   "docs/msl-rc-contract.md"):
        report["metadata"]["source_sha256"][source] = hashlib.sha256(
            (ROOT / source).read_bytes()).hexdigest()
    report.update(linear_limits=limits, fixed_asset_pairing=paired, rc_faults=faults)
    report["passed"] = bool(report["passed"] and limits["passed"] and paired["passed"]
                            and all(f["wrong_capacity_detected"] is not False
                                    and f["wrong_resistance_detected"] is not False
                                    for f in faults))
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("msl-rc-summary: "+json.dumps({k:v for k,v in report.items() if k != "cases"}),
          flush=True)
    assert report["passed"], "fixed RC parameter and actual-energy gate failed"


if __name__ == "__main__":
    main()
