import hashlib
import json
import numpy as np
import pytest

from sonar_activaciones.storage.capture import Capture, save_capture, load_capture
from sonar_activaciones.processing.projection import component_basis
from sonar_activaciones.processing.reference import values_for
from .test_core import probe, sample


def test_roundtrip_values_reference_basis_and_gaps(tmp_path):
    p = probe()
    samples = tuple(sample(i, [i, 2*i, -i], captured_at=10+i, context={"stream_id": "A"}) for i in (0, 1, 4, 5))
    basis = component_basis(p, [0, 2])
    original = Capture((p,), samples, {"p": samples[0]}, {"p": basis}, {"p": 1}, samples[2],
                       {"mode": "reference_delta", "selected_probe": "p", "visual_limit": 7.5},
                       {"transport_dropped": 2}, 10)
    path = save_capture(tmp_path/"capture.json", original)
    restored = load_capture(path)
    assert restored.samples == original.samples
    assert restored.snapshot == original.snapshot
    assert restored.references == original.references
    assert restored.view == original.view
    for a, b in zip(original.samples, restored.samples):
        da = values_for(a, "reference_delta", original.references["p"])
        db = values_for(b, "reference_delta", restored.references["p"])
        np.testing.assert_array_equal(da, db)
        np.testing.assert_array_equal(original.bases["p"].project_delta(da), restored.bases["p"].project_delta(db))
    assert values_for(restored.samples[2], "previous_delta", previous=restored.samples[1]) is None


def test_invalid_capture_keeps_contract(tmp_path):
    original = Capture((probe(),), (sample(),))
    path = save_capture(tmp_path/"capture.json", original)
    document = json.loads(path.read_text())
    document["series"][0]["readings"].append(document["series"][0]["readings"][0])
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        load_capture(path)


def test_reader_rejects_pickle_traversal_checksum(tmp_path):
    from sonar_activaciones.storage.numeric import read_pair
    npz = tmp_path/"bad.npz"
    np.savez(npz, evil=np.array([{"never": "execute"}], dtype=object))
    path = tmp_path/"bad.json"
    metadata = {"arrays_file": npz.name, "arrays_sha256": hashlib.sha256(npz.read_bytes()).hexdigest()}
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="objeto"):
        read_pair(path)
    metadata["arrays_file"] = "../bad.npz"
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="rutas"):
        read_pair(path)
    metadata["arrays_file"] = "bad.npz"
    metadata["arrays_sha256"] = "not-the-checksum"
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="Checksum"):
        read_pair(path)
