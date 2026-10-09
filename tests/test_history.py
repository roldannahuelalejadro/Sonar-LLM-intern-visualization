import numpy as np
import pytest
from sonar_activaciones import MonitorConfig
from sonar_activaciones.app.state import ViewerState
from sonar_activaciones.processing.temporal import coordinates, broken_trace
from .test_core import probe, sample


def test_gaps_not_connected_and_axes():
    samples = [sample(0), sample(1), sample(4), sample(5, context={"stream_id": "new"})]
    x, y = broken_trace(samples, coordinates(samples), [1, 2, 3, 4])
    assert np.isnan(y).sum() == 2
    assert list(x[np.isfinite(x)]) == [0, 1, 4, 5]
    with pytest.raises(ValueError):
        coordinates(samples, "token")


def test_freeze_keeps_readings_and_total_history_bound():
    state = ViewerState([probe()], MonitorConfig(history_bytes=32000))
    for i in range(8):
        state.ingest(sample(i))
    state.freeze()
    frozen = state.current()
    for i in range(8, 1000):
        state.ingest(sample(i))
    assert state.current() == frozen
    assert state.history.used_bytes <= 32000
    assert state.frozen.sequence == frozen.sequence
    assert frozen.accounted_bytes < state.plan.reserves['reference_selection']
    assert state.plan.committed <= state.plan.total
    state.live()
    assert state.current().sequence == 999


def test_series_do_not_mix():
    from sonar_activaciones import Observation
    p, q = probe(), probe(probe_id="q", space_id="different-space")
    state = ViewerState([p, q], MonitorConfig())
    state.ingest(sample(0))
    state.ingest(Observation.create(q, np.zeros(3), 0))
    assert state.current().probe_id == "p"
    state.select_probe("q")
    assert state.current().probe_id == "q"
    with pytest.raises(ValueError):
        state.ingest(Observation.create(probe(space_id="changed"), np.zeros(3), 1))
