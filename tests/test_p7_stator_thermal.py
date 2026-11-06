"""Independent manufactured and insulated heating references; optional FE environment."""
import hashlib
import importlib
import json
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def thermal(monkeypatch):
    for package in ("gmsh", "meshio", "skfem"):
        pytest.importorskip(package)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "benchmarks"))
    return importlib.import_module("p7_stator_thermal")


def test_uniform_insulated_heating_matches_capacity_reference(thermal):
    from scipy.sparse import diags
    from scipy.sparse.linalg import spsolve
    from skfem import MeshTri

    mesh = MeshTri.init_tensor(np.linspace(0, 1, 4), np.linspace(0, 1, 4))
    tags = np.ones(mesh.nelements, dtype=int)
    _, mass, stiffness, inputs, out, area = thermal.assemble(mesh, tags, np.array([], dtype=int))
    assert sum(area) == pytest.approx(1.)
    assert sum(mass) == pytest.approx(.05*3.5e6)
    assert inputs[:, 0].sum() == pytest.approx(.05)
    assert np.max(abs(stiffness@np.ones(mesh.nvertices))) < 1e-12
    assert np.max(abs(out)) == 0
    dt, density = .1, 7000.
    load = inputs@np.r_[density, np.zeros(24)]
    rise = spsolve(diags(mass)+dt*stiffness, dt*load)
    np.testing.assert_allclose(rise, density*dt/3.5e6, atol=1e-15, rtol=1e-12)
    assert mass@rise == pytest.approx(density*.05*dt, abs=1e-12)


def test_quadratic_manufactured_error_decreases_on_independent_square(thermal):
    from skfem import Basis, ElementTriP1, MeshTri

    errors = []
    for n in (4, 8, 16):
        mesh = MeshTri.init_tensor(np.linspace(0, 1, n+1), np.linspace(0, 1, n+1))
        result = thermal.manufactured(Basis(mesh, ElementTriP1(), intorder=4))
        errors.append(result["relative_l2"])
        assert result["affine_max_error"] < 1e-12
    assert errors[0]/errors[1] > 3.5
    assert errors[1]/errors[2] > 3.5


def test_corrupt_spatial_source_csv_is_rejected(thermal, tmp_path, monkeypatch):
    data = b"original source"
    (tmp_path / "regions.csv").write_bytes(data+b"corrupt")
    (tmp_path / "summary.json").write_text(json.dumps(dict(
        passed=True, thermal_solve=False,
        output_sha256={"regions.csv": hashlib.sha256(data).hexdigest()})), encoding="utf-8")
    monkeypatch.setattr(thermal, "SOURCE_DIR", tmp_path)
    with pytest.raises(ValueError, match="integrity"):
        thermal.read_sources()


def test_missing_annular_sector_creates_rejected_exposed_interface(thermal):
    from skfem import MeshTri

    angle = np.arange(4)*np.pi/2
    points = np.hstack([radius*np.array([np.cos(angle), np.sin(angle)])
                       for radius in (.02785, .05)])
    triangles = []
    for i in range(4):
        j = (i+1) % 4
        triangles.extend([[i, i+4, j+4], [i, j+4, j]])

    def exterior(mesh):
        r = np.linalg.norm(mesh.p[:, mesh.facets], axis=0)
        return np.flatnonzero(np.all(abs(r-.05) < 1e-12, axis=0))

    full = MeshTri(points, np.array(triangles).T)
    thermal.validate_exposed_boundary(full, exterior(full))
    missing = MeshTri(points, np.array(triangles[2:]).T)
    with pytest.raises(ValueError, match="exposed slot"):
        thermal.validate_exposed_boundary(missing, exterior(missing))


def test_rom_rmse_gate_does_not_average_away_one_bad_channel(thermal):
    study = importlib.import_module("p7_stator_rom_study")
    errors = np.array([[0., 25e-6], [0., 25e-6]])
    assert np.sqrt(np.mean(errors**2)) < 20e-6
    assert study.max_channel_rmse(errors) == pytest.approx(25e-6)
    assert study.max_channel_rmse(errors) > 20e-6


@pytest.mark.parametrize("errors", [[], [[1.]], [[1., float("nan")]], [[1., float("inf")]]])
def test_rom_rmse_rejects_missing_or_nonfinite_channels(thermal, errors):
    study = importlib.import_module("p7_stator_rom_study")
    with pytest.raises(ValueError):
        study.max_channel_rmse(errors)
