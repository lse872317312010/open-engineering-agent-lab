"""FMI capability checks and optional actual FMU integration."""

import copy
import json
import os
import zipfile
from pathlib import Path

import pytest
from jsonschema import ValidationError

from oeal.backends.fmi_joint import BINARY, load_asset, subdivisions
from oeal.experiments import run_experiment
from oeal.ir import document_hash, validate_document
from oeal.studies import catalog, recompute, resolved_settings
from oeal.study_tools import StudyTools

ROOT = Path(__file__).parents[1]


def spec():
    return json.loads((ROOT / "examples/studies/fmi_joint_v1.json").read_text())


def test_fmi_registry_and_capability_rejections_before_optional_imports():
    base = spec()
    validate_document(base)
    assert catalog()["fmi_joint_v1"]["backend"] == "fmi"
    assert catalog()["fmi_joint_v1"]["motor_overrides"] == []
    assert subdivisions(resolved_settings(base))[2] == 50
    for key, value in (("control_period_s", 100e-6), ("integration_step_s", 6e-6),
                       ("vdc_v", 49), ("load_nm", 11), ("board_power_w", 1001)):
        changed = copy.deepcopy(base)
        changed["settings"][key]["value"] = value
        with pytest.raises((ValueError, ValidationError)):
            validate_document(changed)
    changed = copy.deepcopy(base)
    changed["model"]["parameters"] = {"pole_pairs": {"value": 8, "unit": "1"}}
    with pytest.raises(ValueError):
        validate_document(changed)
    changed = copy.deepcopy(base)
    changed["budget"]["solver_evaluations"] = 59999
    with pytest.raises(ValueError, match="budget"):
        validate_document(changed)
    changed = copy.deepcopy(base)
    del changed["acceptance"]["energy_balance_abs_j"]
    with pytest.raises(ValueError):
        validate_document(changed)


def test_fmi_asset_rejects_unregistered_archive_before_loading(tmp_path):
    with zipfile.ZipFile(tmp_path / "oeal-joint.fmu", "w") as z:
        z.writestr("../library.so", b"no execution")
    with pytest.raises(ValueError, match="entries"):
        load_asset(tmp_path)
    allowed = ["modelDescription.xml", BINARY, "resources/joint.c", "resources/contract.md",
               "resources/LICENSE", "resources/THIRD_PARTY.txt"]
    with zipfile.ZipFile(tmp_path / "oeal-joint.fmu", "w") as z:
        for name in allowed:
            z.writestr(name, b"<forged/>" if name.endswith(".xml") else b"forged")
    with pytest.raises(ValueError, match="binary hash"):
        load_asset(tmp_path)


@pytest.fixture
def assets():
    root = os.environ.get("OEAL_FMI_ASSET_ROOT")
    if not root:
        pytest.skip("optional compiled FMI asset")
    return root


def test_actual_fmi_ir_clocks_reference_and_energy_audit(assets):
    document = spec()
    result = run_experiment(document, assets)
    assert result["numeric_passed"] and result["goal_passed"]
    assert len(result["streams"]["waveforms"]["samples"]) == 12001
    for kind in ("reference", "command", "missing waveform", "context"):
        changed = copy.deepcopy(result)
        if kind == "reference":
            changed["streams"]["control"]["samples"][100][19] += .1
        elif kind == "command":
            changed["streams"]["control"]["samples"][100][15] += .1
        elif kind == "context":
            changed["context"]["fmi_asset_hashes"]["binary_sha256"] = "0"*64
        else:
            changed["streams"]["waveforms"]["samples"].pop()
        changed["raw_sha256"] = document_hash(changed["streams"])
        with pytest.raises(ValueError):
            recompute(document, changed)


def test_actual_fmi_agent_fixed_goal_and_metrics_binding(assets, tmp_path):
    document = spec()
    tools = StudyTools(document, tmp_path, assets)
    candidate = tools.propose_change({"bandwidth_per_s": 1200.})
    result = tools.run_experiment(candidate)
    expected = tools.verify_change(candidate, result)
    assert expected["passed"]
    result["metrics"] = {"current_tail_error_a": -999}
    result["goal_passed"] = False
    assert tools.verify_change(candidate, result) == expected
    changed = copy.deepcopy(result)
    changed["streams"]["waveforms"]["samples"][10][1] += .1
    changed["raw_sha256"] = document_hash(changed["streams"])
    with pytest.raises(ValueError, match="trusted session"):
        tools.verify_change(candidate, changed)
    with pytest.raises(ValueError):
        tools.propose_change({"vdc_v": 100.})
