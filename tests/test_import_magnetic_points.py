"""Checks the external point-table interchange and rejects ambiguous inputs."""
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest


spec = importlib.util.spec_from_file_location(
    "import_magnetic_points", Path(__file__).parents[1] / "benchmarks/import_magnetic_points.py"
)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def inputs(tmp_path):
    csv_path = tmp_path / "map.csv"
    meta_path = tmp_path / "meta.json"
    csv_path.write_text("id_A,iq_A,psi_d_Wb,psi_q_Wb\n-1,2,0.1,0.2\n0,3,0.3,0.4\n")
    meta_path.write_text(json.dumps(dict(
        source_software="example", source_version="1", model_id="demo", pole_pairs=2,
        temperature_c=25, dq_convention="motulator_peak_d_plus_jq",
        phase_sequence="abc", domain="two source points",
    )))
    return csv_path, meta_path


def test_round_trip_and_provenance(tmp_path):
    source, meta = inputs(tmp_path)
    output = tmp_path / "model.npz"
    adapter.convert(source, meta, output)
    with np.load(output, allow_pickle=False) as data:
        np.testing.assert_array_equal(data["i_s_dq"], [-1 + 2j, 3j])
        np.testing.assert_array_equal(data["psi_s_dq"], [0.1 + 0.2j, 0.3 + 0.4j])
        manifest = json.loads(str(data["manifest_json"]))
        assert manifest["source_csv_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        assert manifest["metadata_sha256"] == hashlib.sha256(meta.read_bytes()).hexdigest()
        assert manifest["point_count"] == 2


@pytest.mark.parametrize("rows", [
    "id_A,iq_A,psi_d_Wb,psi_q_Wb\n1,2,3,nan\n",
    "id_A,iq_A,psi_d_Wb,psi_q_Wb\n1,2,3,4\n1,2,5,6\n",
    "id_A,id_A,psi_d_Wb,psi_q_Wb\n1,2,3,4\n",
])
def test_reject_bad_data(tmp_path, rows):
    source, meta = inputs(tmp_path)
    source.write_text(rows)
    with pytest.raises(ValueError):
        adapter.convert(source, meta, tmp_path / "out.npz")


def test_reject_wrong_convention_and_input_overwrite(tmp_path):
    source, meta = inputs(tmp_path)
    data = json.loads(meta.read_text())
    data["dq_convention"] = "unknown"
    meta.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        adapter.convert(source, meta, tmp_path / "out.npz")
    original = source.read_bytes()
    with pytest.raises(ValueError):
        adapter.convert(source, meta, source)
    assert source.read_bytes() == original
