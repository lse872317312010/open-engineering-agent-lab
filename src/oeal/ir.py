"""IR v0.1: schema validation and fixed, non-executable model semantics."""

import hashlib
import json
import math
from importlib.resources import files

from jsonschema import Draft202012Validator

from oeal.foc import FOCConfig
from oeal.models import MotorParameters

SCHEMA = json.loads(files("oeal").joinpath("schemas/ir-0.1.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA)


def canonical(document):
    """Stable serialization; reject NaN/Inf and non-JSON values."""
    return json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)


def document_hash(document):
    return hashlib.sha256(canonical(document).encode()).hexdigest()


def motor_from_spec(model):
    return MotorParameters(**{name: q["value"] for name, q in model["parameters"].items()})


def validate_document(document):
    if document.get("version") == "0.2":
        from oeal.studies import validate_study

        return validate_study(document)
    canonical(document)
    VALIDATOR.validate(document)
    kind = document["kind"]
    model = document if kind == "ModelSpec" else document.get("model")
    if model:
        motor_from_spec(model)
        tc = model["clocks"]["control"]["value"]
        tp = model["clocks"]["pwm"]["value"]
        ratio = tc / tp
        if not math.isfinite(ratio) or not math.isclose(
            ratio, round(ratio), rel_tol=0, abs_tol=1e-9
        ):
            raise ValueError("control period must be an integer multiple of PWM period")
    if kind == "ExperimentSpec":
        settings = FOCConfig(**document["settings"])
        if settings.control_period_s != model["clocks"]["control"]["value"]:
            raise ValueError("control period differs from model clock")
        count = (
            round(settings.duration_s / settings.control_period_s)
            * math.ceil(settings.control_period_s / settings.integration_step_s)
        )
        if count > document["budget_steps"]:
            raise ValueError("experiment exceeds integration budget")
        if document["backend"] == "pathsim" and document["mode"] != "open_loop":
            raise ValueError("PathSim adapter currently supports open_loop only")
        if document["seed"] != 0:
            raise ValueError("v0.1 deterministic models require seed=0")
    if kind == "SimulationResult":
        columns, samples = document["columns"], document["samples"]
        if len(set(columns)) != len(columns):
            raise ValueError("duplicate signal columns")
        if any(len(row) != len(columns) for row in samples):
            raise ValueError("sample width differs from columns")
        if any(b[0] <= a[0] for a, b in zip(samples[:-1], samples[1:], strict=True)):
            raise ValueError("result time must strictly increase")
    return document
