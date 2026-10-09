import subprocess
import sys

import numpy as np
import pytest

from sonar_activaciones import MonitorConfig, Observation, ProbeDescriptor
from sonar_activaciones.processing.history import History
from sonar_activaciones.processing.reference import difference, magnitude, values_for


def probe(dimension=3, **kwargs):
    args = dict(probe_id="p", name="P", source_id="test", capture_point="cpu",
                dimension=dimension, selection_rule="all", space_id="test/v1")
    args.update(kwargs)
    return ProbeDescriptor(**args)


def sample(seq=0, values=None, **kwargs):
    return Observation.create(probe(), np.array([1., -2., 3.] if values is None else values), seq, **kwargs)


def test_sdk_import_is_lightweight():
    result = subprocess.run([sys.executable, "-c", "import sonar_activaciones, sys; "
                             "assert not any(n.startswith(('PySide6', 'pyqtgraph', 'torch')) for n in sys.modules)"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_immutable_snapshot_and_roundtrip():
    original = np.arange(3.)
    s = sample(values=original, context={"stream_id": "A"})
    original[:] = 99
    np.testing.assert_array_equal(s.values, [0, 1, 2])
    with pytest.raises(ValueError):
        s.values.setflags(write=True)
    assert Observation.unpack(s.pack()) == s


def test_reference_and_gaps():
    a, b = sample(0), sample(1, [3, 0, 3])
    np.testing.assert_array_equal(difference(a, a), [0, 0, 0])
    np.testing.assert_array_equal(values_for(b, "previous_delta", previous=a), [2, 2, 0])
    assert values_for(sample(2), "previous_delta", previous=a) is None
    assert values_for(sample(1, context={"stream_id": "new"}), "previous_delta", previous=a) is None
    other = Observation.create(probe(space_id="other"), np.zeros(3), 1)
    with pytest.raises(ValueError, match="incompatible"):
        difference(a, other)


@pytest.mark.parametrize("values", [np.array([1, np.nan, 3]), np.array([np.inf, 0, 0]),
                                   np.zeros((1, 3)), np.zeros(2), np.array([1j, 2j, 3j]),
                                   np.array([1e300, 0, 0]), [1, 2, 3]])
def test_invalid_vectors(values):
    with pytest.raises(ValueError):
        Observation.create(probe(), values, 0)


def test_metadata_and_budget():
    with pytest.raises(ValueError):
        sample(context={"text": "a"*10000})
    with pytest.raises(ValueError):
        sample(max_bytes=1)
    with pytest.raises(ValueError):
        MonitorConfig(queue_capacity=256, max_sample_bytes=16*1024**2)
    h = History(14000)
    for i in range(1000):
        h.append(sample(i))
        assert h.used_bytes <= h.budget_bytes
    assert h.evicted > 0
    h.resize(4096)
    assert h.used_bytes <= 4096
    assert h.samples()[-1].sequence == 999


def test_norm():
    n, rms = magnitude([3, 4])
    assert n == 5
    assert rms == pytest.approx(5 / np.sqrt(2))


def test_metadata_snapshot_and_descriptor_validation():
    from dataclasses import FrozenInstanceError
    meta = {"checkpoint": "test-revision"}
    p = probe(metadata=meta)
    meta["checkpoint"] = "changed"
    assert p.metadata["checkpoint"] == "test-revision"
    with pytest.raises(FrozenInstanceError):
        p.dimension = 5
    with pytest.raises(ValueError):
        probe(dimension=True)
    with pytest.raises(ValueError):
        sample(context={"processed_position": -1})
