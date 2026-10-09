import hashlib
import io
import json
import zipfile

import numpy as np
import pytest

from sonar_activaciones.processing.projection import DirectionBasis, load_basis, component_basis, save_basis
from sonar_activaciones.storage.capture import Capture, save_capture, load_capture
from sonar_activaciones.storage.numeric import read_pair
from .test_core import probe, sample


def test_spoofed_numpy_shape_rejected_before_allocation(tmp_path):
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(stream, {"descr": "<f8", "fortran_order": False, "shape": (2**40,)})
    archive = tmp_path/"shape.npz"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("W.npy", stream.getvalue())
    path = tmp_path/"shape.json"
    path.write_text(json.dumps({"arrays_file": archive.name, "arrays_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}))
    with pytest.raises(ValueError, match="Forma NPY"):
        read_pair(path)


def test_basis_declared_huge_dimension_rejected(tmp_path):
    path = save_basis(tmp_path/"basis.json", component_basis(probe(), [0, 1]))
    document = json.loads(path.read_text())
    document["dimension"] = 2**50
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="Dimension"):
        load_basis(path)


@pytest.mark.parametrize("view", [{"component": "invalid"}, {"page": -1}, {"trace_indices": [123]},
                                  {"visual_limit": float("nan")}, {"window": 9999999}])
def test_invalid_view_rejected(tmp_path, view):
    with pytest.raises(ValueError):
        save_capture(tmp_path/"capture.json", Capture((probe(),), (sample(),), view=view))


def test_unicode_filename_roundtrip(tmp_path):
    path = save_capture(tmp_path/"captura-\u00f1.json", Capture((probe(),), (sample(),)))
    assert load_capture(path).samples[0] == load_capture(path).samples[0]


def test_projection_overflow_is_explicit():
    b = DirectionBasis("test", "test/v1", ("x",), "test", np.ones((3, 1)), np.zeros(3), np.full(3, 1e-300))
    with pytest.raises(ValueError, match="finita"):
        b.project(np.ones(3)*1e30)


def test_duplicate_sequence_file_rejected(tmp_path):
    path = save_capture(tmp_path/"capture.json", Capture((probe(),), (sample(0), sample(1))))
    data = json.loads(path.read_text())
    data["series"][0]["readings"][1]["sequence"] = 0
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Secuencia"):
        load_capture(path)
