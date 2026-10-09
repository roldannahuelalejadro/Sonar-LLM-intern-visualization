from dataclasses import replace
import json
import numpy as np
import pytest
from sonar_activaciones import MonitorConfig, Observation
from sonar_activaciones.app.state import ViewerState
from sonar_activaciones.processing.projection import component_basis
from sonar_activaciones.processing.memory import WorkAdmission
from sonar_activaciones.storage.mixed import save_state, load_state
from sonar_activaciones.storage.capture import Capture, save_capture
from .test_core import probe, sample


def fixture():
    p = probe(dimension=4096)
    config = MonitorConfig(history_bytes=60000, work_bytes=8*1024**2, recent_fraction=.05)
    state = ViewerState([p], config)
    state.install_basis(component_basis(p, [0, 1]))
    for i in range(80):
        state.ingest(Observation.create(p, np.arange(p.dimension, dtype=np.float32)+i, i))
    state.set_reference()
    state.freeze_sequence(0)
    return state


def test_mixed_roundtrip_and_missing_vector(tmp_path):
    state = fixture()
    assert state.selection().availability == 'projection'
    path = save_state(tmp_path/'mixed.json', state)
    restored, _, _ = load_state(path, state.config, state.work)
    assert restored.selection().availability == 'projection'
    assert restored.values() is None
    assert restored.history.session_id == state.history.session_id
    assert restored.references['p'].sequence == 79
    a, b = state.history.rings['p'], restored.history.rings['p']
    assert a.raw_bytes == b.raw_bytes and a.projected_bytes == b.projected_bytes
    for seq in a.frames:
        assert a.frames[seq].payload == b.frames[seq].payload
        assert a.frames[seq].projections == b.frames[seq].projections
    assert state.work.active is None


def test_v1_load_and_rejected_file_leave_budget_intact(tmp_path):
    old = save_capture(tmp_path/'old.json', Capture((probe(),), tuple(sample(i) for i in range(10)), snapshot=sample(3)))
    budget = WorkAdmission(8*1024**2)
    state, _, _ = load_state(old, MonitorConfig(), budget)
    assert state.current().sequence == 3
    assert not state.selection().projections
    assert budget.active is None


def test_import_rejects_before_np_load(tmp_path, monkeypatch):
    state = fixture()
    path = save_state(tmp_path/'mixed.json', state)
    def forbidden(*args, **kwargs):
        raise AssertionError('np.load called before admission')
    monkeypatch.setattr(np, 'load', forbidden)
    with pytest.raises(ValueError):
        load_state(path, state.config, WorkAdmission(1200000))


def test_invalid_availability_and_foreign_segment(tmp_path):
    state = fixture()
    path = save_state(tmp_path/'mixed.json', state)
    document = json.loads(path.read_text())
    document['series'][0]['frames'][0]['availability'] = 'both'
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='Disponibilidad'):
        load_state(path, state.config, state.work)
    assert state.work.active is None


def test_export_rejected_before_stack(tmp_path, monkeypatch):
    state = fixture()
    state.work.capacity = 1024
    with pytest.raises(ValueError, match='reserva'):
        save_state(tmp_path/'no.json', state)
    assert not (tmp_path/'no.json').exists()


def test_shrink_preview_matches_real_evictions():
    state = fixture()
    state.live()
    config = replace(state.config, history_bytes=30000, recent_fraction=.5)
    _, impact = state.preview_config(config)
    ring = state.history.rings['p']
    before = (len(ring.raw), len(ring.frames), len(ring.projected))
    state.reconfigure(config)
    assert impact == {'detail_lost': before[0]-len(ring.raw), 'captures_retired': before[1]-len(ring.frames),
                      'projections_lost': before[2]-len(ring.projected)}


def test_install_other_probe_keeps_selection_and_roundtrip(tmp_path):
    p, q = probe(), probe(probe_id='q', dimension=70, space_id='other')
    state = ViewerState([p, q], MonitorConfig())
    state.install_basis(component_basis(p, [0, 1]), 'p')
    original = state.selected_segment
    state.install_basis(component_basis(q, [0, 1]), 'q')
    assert state.selected_segment == original
    for i in range(10):
        state.ingest(sample(i))
        state.ingest(Observation.create(q, np.ones(70), i))
    path = save_state(tmp_path/'multi.json', state)
    restored, _, _ = load_state(path, state.config, state.work)
    assert restored.selected_probe == 'p' and restored.selected_segment == original
    assert len(restored.segments) == 2


def test_v1_multiple_references_require_explicit_choice(tmp_path):
    p, q = probe(), probe(probe_id='q', space_id='other')
    a, b = sample(0), Observation.create(q, np.ones(3), 0)
    path = save_capture(tmp_path/'old-many.json', Capture((p, q), (a, b), {'p': a, 'q': b}))
    work = WorkAdmission(8*1024**2)
    with pytest.raises(ValueError, match='elegir'):
        load_state(path, MonitorConfig(), work)
    state, _, _ = load_state(path, MonitorConfig(), work, choose_reference=lambda ids: 'q')
    assert set(state.references) == {'q'}
    assert state.history.rings['p'].frames[0].payload == a.payload
