"""Capabilities, actual parameter binding, outer-loop scope and waveform integrity."""

import copy
import json
import os
from pathlib import Path

import pytest
from jsonschema import ValidationError

from oeal.experiments import run_experiment
from oeal.ir import document_hash, validate_document
from oeal.studies import catalog, recompute
from oeal.study_tools import StudyTools

ROOT = Path(__file__).parents[1]


def spec():
    return json.loads((ROOT / "examples/studies/fmi_servo_v2.json").read_text())


def test_servo_parameter_ranges_clocks_and_registered_profile():
    item = spec()
    validate_document(item)
    assert len(catalog()) == 7
    assert catalog()["fmi_servo_v2"]["motor_overrides"]
    for field, value, unit in [
        ("stator_resistance_ohm", .1, "ohm"), ("d_inductance_h", .002, "H"),
        ("flux_linkage_wb", .05, "Wb"), ("inertia_kg_m2", .001, "kg*m^2"),
        ("viscous_friction_nms", .001, "N*m*s/rad"), ("pole_pairs", 7.5, "1"),
    ]:
        changed = copy.deepcopy(item)
        changed["model"]["parameters"][field] = dict(value=value, unit=unit)
        with pytest.raises((ValueError, ValidationError)):
            validate_document(changed)
    changed = copy.deepcopy(item)
    changed["settings"]["position_start_s"]["value"] = .010001
    with pytest.raises(ValueError, match="align"):
        validate_document(changed)
    changed = copy.deepcopy(item)
    changed["settings"]["iq_reference_a"] = dict(value=1, unit="A")
    with pytest.raises(ValueError, match="unsupported"):
        validate_document(changed)


def test_servo_tools_freeze_current_gains_actual_parameters_and_goals(tmp_path):
    tools = StudyTools(spec(), tmp_path)
    for patch in ({"bandwidth_per_s": 1200}, {"position_step_rad": .01},
                  {"outer_kd_nms_per_rad": .1}):
        with pytest.raises(ValueError):
            tools.propose_change(patch)
    changed = tools.propose_change({"outer_kp_nm_per_rad": 80, "outer_kd_nms_per_rad": 3})
    assert changed["settings"]["outer_kp_nm_per_rad"]["value"] == 80


def test_actual_servo_audit_rejects_parameter_reference_and_state_tampering():
    assets = os.environ.get("OEAL_SERVO_ASSET_ROOT")
    if not assets:
        pytest.skip("optional compiled configurable FMI asset")
    document = spec()
    result = run_experiment(document, assets)
    assert result["goal_passed"]
    for kind in ("motor", "nominal", "reference velocity", "joint state", "waveform"):
        changed = copy.deepcopy(result)
        if kind == "motor":
            changed["context"]["physical_parameters"]["inertia_kg_m2"] *= 2
        elif kind == "nominal":
            changed["context"]["nominal_parameters"]["flux_linkage_wb"] *= .9
        elif kind == "reference velocity":
            changed["streams"]["joint"]["samples"][200][4] += .1
        elif kind == "joint state":
            changed["streams"]["joint"]["samples"][200][1] += .01
        else:
            changed["streams"]["waveforms"]["samples"].pop()
        changed["raw_sha256"] = document_hash(changed["streams"])
        with pytest.raises(ValueError):
            recompute(document, changed)
