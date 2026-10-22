"""Reproduce P1 mathematics, backend probes and timing evidence without hardware."""

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import resource
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from scipy.integrate import solve_ivp

from oeal.foc import FOCConfig, simulate_foc
from oeal.metrics import b1_passes, current_step_metrics
from oeal.models import MotorParameters, PMSMInput, PMSMState, simulate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "p1"
OUT.mkdir(parents=True, exist_ok=True)


def save(name, value):
    text = json.dumps(value, indent=2, allow_nan=False) + "\n"
    (OUT / name).write_text(text, encoding="utf-8")
    print(name + ": " + json.dumps(value, allow_nan=False), flush=True)


def independent_rhs(m, u):
    # Independent transcription: no state_derivative or RK4 imported here.
    def rhs(t, x):
        d, q, w, _ = x
        we = m["pole_pairs"] * w
        torque = 1.5 * m["pole_pairs"] * (
            m["flux_linkage_wb"] * q
            + (m["d_inductance_h"] - m["q_inductance_h"]) * d * q
        )
        return np.array([
            (u["vd_v"] - m["stator_resistance_ohm"] * d
             + we * m["q_inductance_h"] * q) / m["d_inductance_h"],
            (u["vq_v"] - m["stator_resistance_ohm"] * q
             - we * (m["d_inductance_h"] * d + m["flux_linkage_wb"]))
            / m["q_inductance_h"],
            (torque - u["load_torque_nm"] - m["viscous_friction_nms"] * w)
            / m["inertia_kg_m2"],
            w,
        ])
    return rhs


def b0():
    path = ROOT / "examples/pmsm_step.json"
    config = json.loads(path.read_text())
    motor = MotorParameters(**config["model"])
    command = PMSMInput(**config["input"])
    rhs = independent_rhs(config["model"], config["input"])
    duration = config["simulation"]["duration_s"]
    errors = []
    for step in (4e-5, 2e-5, 1e-5):
        trace = simulate(motor, command, duration, step)
        reference = solve_ivp(
            rhs, (0, duration), np.zeros(4), method="DOP853",
            t_eval=trace.times_s, rtol=1e-12, atol=1e-13,
        )
        if not reference.success:
            raise RuntimeError(reference.message)
        errors.append(float(np.max(np.abs(trace.states - reference.y.T))))
    result = {
        "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "steps_s": [4e-5, 2e-5, 1e-5], "max_state_errors": errors,
        "reference": "independent equations + DOP853 rtol=1e-12 atol=1e-13",
        "passed": errors[-1] < 1e-5 and errors[-1] < errors[0] / 8,
    }
    save("b0.json", result)
    if not result["passed"]:
        raise AssertionError("B0 accuracy/convergence failed")
    return config, rhs, trace.states[-1]


def pathsim_probe(config, rhs, expected):
    from pathsim import Simulation
    from pathsim.blocks import ODE
    from pathsim.events import Schedule
    from pathsim.solvers import RK4

    ode = ODE(lambda x, u, t: rhs(t, x), initial_value=np.zeros(4))
    duration = config["simulation"]["duration_s"]
    sim = Simulation(blocks=[ode], dt=1e-5, Solver=RK4, log=False)
    sim.run(duration, adaptive=False)
    first = np.asarray(ode.engine.state).copy()
    sim.reset()
    sim.run(duration, adaptive=False)
    reset_error = float(np.max(np.abs(first - ode.engine.state)))
    error = float(np.max(np.abs(first - expected)))
    ticks = []
    fast = []
    events = [
        Schedule(t_start=50e-6, t_end=0.001, t_period=50e-6,
                 func_act=lambda t: ticks.append(t)),
        Schedule(t_start=1 / 120000, t_end=0.001, t_period=1 / 120000,
                 func_act=lambda t: fast.append(t)),
    ]
    event_sim = Simulation(blocks=[ODE()], events=events, dt=1e-6, Solver=RK4, log=False)
    event_sim.run(0.001, adaptive=False)
    timing_error = float(np.max(np.abs(np.asarray(ticks) - np.arange(1, 21) * 50e-6)))
    passed = error < 1e-5 and reset_error < 1e-12 and len(fast) == 120 and timing_error < 1e-12
    result = {
        "b0_final_error": error, "reset_error": reset_error,
        "control_ticks": len(ticks), "pwm_grid_ticks": len(fast),
        "control_tick_error_s": timing_error, "passed": passed,
        "not_tested": ["zero-crossing", "algebraic loops", "untrusted model import"],
    }
    save("pathsim.json", result)
    if not passed:
        raise AssertionError("PathSim B0/reset/schedule probe failed")


def motulator_probe():
    from motulator.drive.model import SynchronousMachine, SynchronousMachinePars

    par = SynchronousMachinePars(n_p=7, R_s=0.3, L_d=0.0008, L_q=0.001, psi_f=0.03)
    machine = SynchronousMachine(par)
    errors = []
    for d, q, speed in ((0, 0, 0), (2, 3, 20), (-2, 4, -30)):
        machine.state.psi_s_dq = par.psi_f + par.L_d * d + 1j * par.L_q * q
        machine.state.theta_m = 0.7
        machine.inp.u_s_ab = (3 + 5j) * np.exp(0.7j)
        machine.inp.w_M = speed
        machine.set_outputs(0)
        derivative = machine.rhs(0)[0]
        we = 7 * speed
        reference = complex(3 - 0.3 * d + we * 0.001 * q,
                            5 - 0.3 * q - we * (0.0008 * d + 0.03))
        errors.append(abs(derivative - reference))
        expected_torque = 1.5 * 7 * (0.03 * q + (0.0008 - 0.001) * d * q)
        errors.append(abs(machine.out.tau_M - expected_torque))
    # Integrate actual motulator RHS with SciPy and compare a locked-rotor RL solution.
    machine.state.theta_m = 0.0
    machine.inp.w_M = 0.0
    machine.inp.u_s_ab = 5j

    def rhs(t, x):
        machine.state.psi_s_dq = complex(x[0], x[1])
        machine.set_outputs(t)
        derivative = machine.rhs(t)[0]
        return [derivative.real, derivative.imag]

    sol = solve_ivp(rhs, (0, 0.003), [0.03, 0], rtol=1e-11, atol=1e-13)
    iq = sol.y[1, -1] / 0.001
    analytic = 5 / 0.3 * (1 - math.exp(-0.3 * 0.003 / 0.001))
    rl_error = abs(iq - analytic)
    passed = max(errors) < 1e-10 and rl_error < 1e-7 and sol.success
    save("motulator.json", {
        "max_equation_torque_error": float(max(errors)), "rl_error_a": float(rl_error),
        "passed": bool(passed), "not_tested": ["full upstream drive/control runner"],
    })
    if not passed:
        raise AssertionError("motulator model probe failed")


def interface_probes():
    from ael.schemas import export_schemas
    from mavrith import PortSpec, SignalSpec

    paths = export_schemas(OUT / "ael-schemas")
    names = {path.name for path in paths}
    ael_passed = {"experiment-spec.schema.json", "evidence-bundle.schema.json"} <= names
    # Exercise typed API headlessly; no imported Python or shell text from JSON.
    port = PortSpec.output("current", spec=SignalSpec(dtype="float", shape=(2,)))
    mavrith_passed = port.signal_spec.shape == (2,)
    save("interfaces.json", {
        "ael_schema_count": len(paths), "ael_export_passed": ael_passed,
        "mavrith_typed_port_passed": mavrith_passed,
        "not_tested": ["AEL workers/backends", "Mavrith scheduling/solver"],
    })
    if not ael_passed or not mavrith_passed:
        raise AssertionError("interface probes failed")


def b1():
    motor = MotorParameters(0.3, 0.0008, 0.0008, 0.03, 7, 0.002, 1e-5)
    config = FOCConfig()
    runs = []
    for name, initial, plant, settings in (
        ("nominal", PMSMState(), motor, config),
        ("positive-speed", PMSMState(mechanical_speed_rad_s=20), motor, config),
        ("negative-speed", PMSMState(mechanical_speed_rad_s=-20), motor, config),
        ("parameter-mismatch", PMSMState(),
         replace(motor, stator_resistance_ohm=0.36, q_inductance_h=0.00096), config),
        ("one-cycle-delay", PMSMState(), motor, replace(config, delay_samples=1)),
    ):
        trace = simulate_foc(plant, settings, initial, controller_motor=motor).samples
        np.savetxt(OUT / (name + ".csv"), trace, delimiter=",")
        metrics = current_step_metrics(trace, config.step_time_s, 5, 48 / math.sqrt(3))
        passed = b1_passes(metrics)
        runs.append({"case": name, "metrics": metrics, "passed": passed})
    trace = simulate_foc(motor, config).samples
    fine = simulate_foc(motor, replace(config, integration_step_s=2.5e-6)).samples
    convergence = float(np.max(np.abs(trace[:, 1:5] - fine[:, 1:5])))
    save("b1.json", {
        "motor": asdict(motor), "config": asdict(config), "cases": runs,
        "halved_step_max_difference": convergence,
        "passed": all(r["passed"] for r in runs) and convergence < 1e-5,
    })
    if not all(r["passed"] for r in runs) or convergence >= 1e-5:
        raise AssertionError("B1 acceptance failed")
    # Infeasible low bus case must be reported as failure, not tuned out.
    low_bus = replace(config, vdc_v=1.0)
    trace = simulate_foc(motor, low_bus).samples
    metrics = current_step_metrics(trace, config.step_time_s, 5, 1 / math.sqrt(3))
    save("b1-infeasible.json", {"metrics": metrics, "passed": b1_passes(metrics),
                              "expected": "failed target due to insufficient bus voltage"})
    if b1_passes(metrics):
        raise AssertionError("negative acceptance unexpectedly passed")


def main():
    start = time.perf_counter()
    versions = {
        name: importlib.metadata.version(name)
        for name in ("numpy", "scipy", "pathsim", "motulator", "agentic-embedded-lab", "mavrith")
    }
    save("environment.json", {
        "python": sys.version, "os": platform.platform(), "cpu": platform.processor(),
        "commit": os.environ.get("GITHUB_SHA") or subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, cwd=ROOT
        ).strip(),
        "versions": versions, "command": "python benchmarks/validate_p1.py",
        "evidence_level": "model_simulated",
    })
    (OUT / "pip-freeze.txt").write_text(
        subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
    )
    config, rhs, expected = b0()
    pathsim_probe(config, rhs, expected)
    motulator_probe()
    interface_probes()
    b1()
    save("run.json", {
        "passed": True, "elapsed_s": time.perf_counter() - start,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "limitations": "Host runtime/RSS is not MCU timing or RAM. No hardware accessed.",
    })


if __name__ == "__main__":
    main()
