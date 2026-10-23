"""Allowlisted native/PathSim execution of versioned experiment documents."""

import os

from oeal.foc import FOCConfig, simulate_foc
from oeal.foc_io import COLUMNS
from oeal.ir import document_hash, motor_from_spec, validate_document
from oeal.metrics import current_step_metrics
from oeal.models import PMSMInput, PMSMState, simulate, state_derivative


def run_experiment(document, assets_root=None):
    if document.get("version") == "0.2":
        from oeal.studies import run_study

        return run_study(document, assets_root)
    validate_document(document)
    if document["kind"] != "ExperimentSpec":
        raise ValueError("ExperimentSpec required")
    model = motor_from_spec(document["model"])
    settings = FOCConfig(**document["settings"])
    command = PMSMInput(**document["input"])
    if document["mode"] == "foc":
        trace = simulate_foc(model, settings, load_torque_nm=command.load_torque_nm).samples
        columns = COLUMNS
        metrics = current_step_metrics(
            trace, settings.step_time_s, settings.iq_reference_a, settings.vdc_v / (3 ** 0.5)
        )
        samples = trace.tolist()
        semantics = "control_ticks_and_endpoint"
    else:
        if document["backend"] == "native":
            trace = simulate(
                model, command, settings.duration_s, settings.integration_step_s
            )
            final = trace.states[-1].tolist()
        else:
            from pathsim import Simulation
            from pathsim.blocks import ODE
            from pathsim.solvers import RK4

            ode = ODE(
                lambda x, u, t: state_derivative(
                    PMSMState.from_array(x), command, model
                ).as_array(), initial_value=PMSMState().as_array(),
            )
            sim = Simulation(
                blocks=[ode], dt=settings.integration_step_s, Solver=RK4, log=False
            )
            sim.run(settings.duration_s, adaptive=False)
            final = list(map(float, ode.engine.state))
        samples = [[0.0, 0.0, 0.0, 0.0, 0.0], [settings.duration_s, *final]]
        columns = COLUMNS[:5]
        metrics = {}
        semantics = "endpoints"
    result = {
        "version": "0.1", "kind": "SimulationResult",
        "experiment_sha256": document_hash(document), "evidence_level": "model_simulated",
        "backend": document["backend"], "columns": columns, "samples": samples,
        "metrics": metrics, "source_commit": os.environ.get("GITHUB_SHA", "unrecorded"),
        "sample_semantics": semantics,
    }
    return validate_document(result)
