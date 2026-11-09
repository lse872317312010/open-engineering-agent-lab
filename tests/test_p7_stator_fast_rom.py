"""Independent small-chain solves and integrity rejection for ROM enrichment."""
import importlib
from pathlib import Path

import numpy as np
import pytest

from oeal.stator_rom import StatorThermalROM


@pytest.fixture
def study(monkeypatch):
    for package in ("gmsh", "meshio", "skfem", "scipy", "matplotlib"):
        pytest.importorskip(package)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "benchmarks"))
    return importlib.import_module("p7_stator_fast_rom")


def chain():
    from scipy.sparse import csr_matrix

    mass = np.array([2., 3., 4., 5.])
    bulk = np.array([[1., -1., 0., 0.], [-1., 2., -1., 0.],
                     [0., -1., 2., -1.], [0., 0., -1., 1.]])
    convection = np.diag([0., 0., 0., 1.])
    forcing = np.array([1., 0., 0., 0.])
    observations = np.array([[1., 0., 0., 0.], [0., 0., 0., 1.], mass,
                             [0., 0., 0., 1.]])
    weighted = np.column_stack((np.sqrt(mass), forcing/np.sqrt(mass)))
    original = np.linalg.qr(weighted)[0]/np.sqrt(mass)[:, None]
    fom = dict(mass=mass, bulk=csr_matrix(bulk), convection=csr_matrix(convection),
               forcing=forcing, observations=observations)
    return fom, original


def projected(fom, basis):
    return dict(format_version=1, mass=basis.T@(fom["mass"][:, None]*basis),
                bulk=basis.T@(fom["bulk"]@basis),
                convection=basis.T@(fom["convection"]@basis),
                forcing=basis.T@fom["forcing"], observations=fom["observations"]@basis,
                h_bounds=[5., 80.], power_bounds_w=[0., 2.], ambient_c=25.)


def test_enrichment_preserves_space_and_matches_independent_dense_chain(study):
    fom, original = chain()
    basis, audit, orthogonal, inclusion = study.enrich_basis(fom, original)
    assert basis.shape == (4, 4)
    assert len(audit) == 15
    assert orthogonal < 1e-12 and inclusion < 1e-12
    model = StatorThermalROM(projected(fom, basis), h_w_m2_k=30., dt_s=study.DT)
    old = StatorThermalROM(projected(fom, original), h_w_m2_k=30., dt_s=study.DT)
    power = study.holdout_powers("alternating", .2)
    metrics, arrays = study.compare(fom, basis, model, original, old, power, 30.)
    state = np.zeros(4)
    matrix = np.diag(fom["mass"])+study.DT*(fom["bulk"]+30*fom["convection"]).toarray()
    energy = out_j = 0.
    for tick, p in enumerate(power, 1):
        state = np.linalg.solve(matrix, fom["mass"]*state+study.DT*fom["forcing"]*p)
        np.testing.assert_allclose(arrays["rom_fields"][tick], state, atol=1e-14)
        energy += study.DT*p
        out_j += study.DT*30*state[-1]
        assert abs(energy-out_j-fom["mass"]@state) < 1e-14
    assert metrics["passed"]
    assert metrics["relative_field_error"] < 1e-10
    assert metrics["baseline_relative_field_error"] > 1e-6


def test_zero_rise_cannot_pass_relative_accuracy_gate(study):
    fom, basis = chain()
    model = StatorThermalROM(projected(fom, basis), h_w_m2_k=30., dt_s=study.DT)
    old = StatorThermalROM(projected(fom, basis), h_w_m2_k=30., dt_s=study.DT)
    metrics, _ = study.compare(fom, basis, model, basis, old, np.zeros(20), 30.)
    assert not metrics["passed"]


def test_modified_frozen_bytes_are_rejected(study, tmp_path):
    path = tmp_path / "inference.npz"
    np.savez(path, forcing=[1., 0.])
    hashes = {path.name: study.digest(path)}
    study.check_files(tmp_path, hashes)
    np.savez(path, forcing=[0., 1.])
    with pytest.raises(ValueError, match="frozen artifact changed"):
        study.check_files(tmp_path, hashes)


@pytest.mark.parametrize("name", ["pulse", "alternating", "triangle"])
def test_holdout_windows_have_fixed_duration_and_valid_domain(study, name):
    values = study.holdout_powers(name, .2)
    assert values.shape == (50,)
    assert np.isfinite(values).all() and np.min(values) >= 0 and np.max(values) <= .4
    assert len(values)*study.DT == .125
