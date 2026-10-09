import json
import numpy as np
import pytest
from sonar_activaciones.processing.projection import (DirectionBasis, component_basis, fit_pca,
                                                      load_basis, save_basis)
from .test_core import probe, sample


def test_components_and_off_plane():
    basis = component_basis(probe(), [0, 1])
    np.testing.assert_allclose(basis.project([1, 2, 100]), [1, 2])
    d = np.array([0, 0, 10])
    np.testing.assert_array_equal(basis.project_delta(d), [0, 0])
    assert basis.displacement(d)["original_norm"] == 10
    assert basis.displacement(d)["omitted_norm"] == 10


def test_affine_projection_and_nonorthogonal_metrics():
    w = np.array([[1, 1], [0, 1], [2, 0]], dtype=float)
    basis = DirectionBasis("test", "test/v1", ("a", "b"), "test", w, np.array([1, 2, 3]), np.array([1, 2, 4]))
    x = np.array([3, 4, 9])
    np.testing.assert_allclose(basis.project(x), w.T @ ((x-basis.center)/basis.scale))
    assert basis.displacement(x)["omitted_norm"] is None
    assert basis.displacement(x)["metric"] == "transformed"


def test_pca_insufficient_null_and_fixed():
    with pytest.raises(ValueError):
        fit_pca([sample()], 2)
    with pytest.raises(ValueError, match="rango"):
        fit_pca([sample(i) for i in range(8)])
    samples = [sample(i, np.random.default_rng(i).normal(size=3)) for i in range(20)]
    basis = fit_pca(samples)
    np.testing.assert_allclose(basis.W.T @ basis.W, np.eye(2), atol=1e-12)
    with pytest.raises(ValueError):
        basis.W.setflags(write=True)


def test_basis_roundtrip_incompatible_and_preprocessing(tmp_path):
    basis = component_basis(probe(), [0, 2])
    path = save_basis(tmp_path/"basis.json", basis)
    loaded = load_basis(path, probe())
    np.testing.assert_array_equal(loaded.W, basis.W)
    with pytest.raises(ValueError, match="incompatible"):
        load_basis(path, probe(space_id="other"))
    metadata = json.loads(path.read_text())
    metadata["preprocessing"] = {"kind": "l2_normalization"}
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="Preprocesamiento"):
        load_basis(path)
