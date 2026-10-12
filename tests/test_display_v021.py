from concurrent.futures import Future
from dataclasses import replace
import numpy as np
import pytest

from sonar_activaciones import MonitorConfig, Observation
from sonar_activaciones.app.state import ViewerState
from sonar_activaciones.processing.display import projected_series, component_series, change_series
from sonar_activaciones.processing.projection import DirectionBasis, component_basis, fit_pca
from sonar_activaciones.storage.mixed import save_state, load_state, validate_view
from .test_core import probe, sample


def affine(p):
    return DirectionBasis('offset', p.space_id, ('X', 'Y'), 'synthetic affine',
                          np.eye(p.dimension)[:, :2], np.arange(p.dimension)+10., np.arange(p.dimension)+2.)


@pytest.mark.parametrize('mode', ['raw', 'reference_delta', 'previous_delta'])
def test_affine_map_and_component_modes(mode):
    p = probe()
    state = ViewerState([p], MonitorConfig())
    basis = affine(p)
    state.install_basis(basis)
    for i in range(5):
        state.ingest(sample(i, [i+2, 2*i-3, i*i], context={'stream_id': 'A'}))
        if i == 0:
            state.set_reference()
    frames = state.viewport_frames()
    ref = state.references['p']
    z = np.array([basis.project(f.observation().values) for f in frames])
    expected = z if mode == 'raw' else z-z[0] if mode == 'reference_delta' else np.vstack([np.full(2, np.nan), np.diff(z, axis=0)])
    np.testing.assert_allclose(projected_series(frames, basis, mode, ref), expected, atol=2e-6)
    if mode == 'reference_delta':
        np.testing.assert_array_equal(component_series(frames, [0, 1], mode, ref)[0], [0, 0])


def test_gaps_streams_projection_only_and_incompatible_bases():
    p = probe()
    s = ViewerState([p], MonitorConfig())
    a, b = component_basis(p, [0, 1]), component_basis(p, [1, 2])
    s.install_basis(a)
    for i, stream in ((0, 'A'), (1, 'A'), (3, 'A'), (4, 'B')):
        s.ingest(sample(i, [i, 2*i, 3*i], context={'stream_id': stream}))
    frames = [f.pin() for f in s.viewport_frames()]
    for f in frames:
        f.payload = None
    z = projected_series(frames, a, 'previous_delta')
    np.testing.assert_allclose(z[1], [1, 2])
    assert np.isnan(z[[0, 2, 3]]).all()
    assert np.isnan(projected_series(frames, b)).all()
    assert np.isnan(change_series(frames, 'full')).all()
    assert change_series(frames, 'projected', a)[1] == pytest.approx(np.sqrt(5))


def test_detail_mode_projects_without_retaining_coordinates():
    p = probe()
    s = ViewerState([p], MonitorConfig(retention_mode='detail'))
    basis = component_basis(p, [0, 1])
    s.install_basis(basis)
    s.ingest(sample(0, [1, 2, 3]))
    frames = s.viewport_frames()
    assert not frames[0].projections
    np.testing.assert_array_equal(projected_series(frames, basis), [[1, 2]])


def test_pca_insufficient_and_constant():
    with pytest.raises(ValueError, match='muestras'):
        fit_pca([sample(i) for i in range(2)], 2)
    with pytest.raises(ValueError, match='rango'):
        fit_pca([sample(i, [1, 1, 1]) for i in range(8)], 2)


def make_window(app, dimension=3, config=None):
    from sonar_activaciones.app.window import MonitorWindow
    w = MonitorWindow([probe(dimension=dimension)], config or MonitorConfig())
    w.timer.stop()
    w.receive_timer.stop()
    w.show_error = lambda message: w.errors.append(message)
    w.errors = []
    return w


def test_full_window_all_modes_and_no_graph_item_growth(app):
    w = make_window(app)
    for i in range(160):
        w.ingest(sample(i, [i, 2*i, -i]))
    w.window_spin.setValue(128)
    for kind in ('change', 'traces', 'heat'):
        w.evolution_combo.setCurrentIndex(w.evolution_combo.findData(kind))
        w.render()
        np.testing.assert_array_equal(w.history_view.displayed_x, np.arange(32, 160))
        before = len(w.history_view.heat.items)
        for _ in range(8):
            w.render()
        assert len(w.history_view.heat.items) == before
    w.select_sequence(120)
    chosen = w.state.selection()
    settings = w.view_settings()
    w.maximize_panel(2)
    w.maximize_panel(2)
    assert w.state.selection() is chosen
    assert w.view_settings() == settings
    w.close()


def test_own_change_definition_independent_of_global_mode(app):
    w = make_window(app)
    for i in range(5):
        w.ingest(sample(i, [i, 2*i, 3*i]))
    w.set_reference()
    w.render()
    baseline = w.history_view.displayed.copy()
    for mode in ('reference_delta', 'previous_delta'):
        w.mode_combo.setCurrentIndex(w.mode_combo.findData(mode))
        np.testing.assert_allclose(w.history_view.displayed, baseline, equal_nan=True)
    w.close()


def test_no_base_one_axis_constant_and_distinct_selectors(app):
    w = make_window(app)
    w.render()
    assert not w.map_axes[0].isEnabled()
    assert not w.directions_view.graph.isVisible()
    assert w.pca_button.text() == 'Crear mapa PCA'
    w.state.install_basis(component_basis(probe(), [0]))
    w.ingest(sample(0))
    w.render()
    assert 'un eje' in w.directions_view.metric_label.text()
    w.state.install_basis(component_basis(probe(), [0, 1]))
    for i in range(1, 4):
        w.ingest(sample(i, [1, 1, 1]))
    w.map_axes[1].setCurrentIndex(1)
    w.render()
    assert w.directions_view.projected is not None
    w.map_axes[1].setCurrentIndex(0)
    assert 'distintos' in w.directions_view.metric_label.text()
    w.close()


def test_pca_origin_survives_probe_change_and_rejects_invalid_context(app):
    from sonar_activaciones.app.window import MonitorWindow
    p, other = probe(), probe(probe_id='other', space_id='other-space')
    w = MonitorWindow([p, other], MonitorConfig())
    w.timer.stop()
    w.receive_timer.stop()
    errors = []
    w.show_error = errors.append
    for i in range(6):
        w.ingest(sample(i, np.random.default_rng(i).normal(size=3)))
    samples = w.state.pca_snapshot(6, 2)
    future = Future()
    future.set_result(fit_pca(samples))
    w.pca_probe, w.pca_descriptor, w.pca_state, w.pca_future = 'p', p, w.state, future
    w.probe_combo.setCurrentIndex(1)
    w.poll_pca()
    assert 'p' in w.state.bases and 'other' not in w.state.bases
    assert w.state.selected_probe == 'other'
    assert not errors
    old = w.state
    old.work.acquire('fixture', 0)
    future = Future()
    future.set_result(component_basis(p, [0, 1]))
    w.pca_future, w.pca_state = future, old
    w.state = ViewerState([p, other], MonitorConfig())
    w.poll_pca()
    assert errors and not old.work.active and not w.state.bases
    w.close()


def test_projection_only_map_deltas_and_old_segment(app):
    w = make_window(app, 4096, MonitorConfig(history_bytes=60000, recent_fraction=.05))
    p = w.state.probes['p']
    a, b = component_basis(p, [0, 1]), component_basis(p, [2, 3])
    w.state.install_basis(a)
    for i in range(60):
        w.ingest(Observation.create(p, np.ones(4096)*i, i))
        if i == 0:
            w.set_reference()
    w.state.install_basis(b, reproject=False)
    w.select_sequence(1)
    assert w.state.selected_segment == a.basis_id
    w.mode_combo.setCurrentIndex(w.mode_combo.findData('reference_delta'))
    assert np.isnan(w.matrix.displayed).all()
    np.testing.assert_array_equal(w.directions_view.projected, [1, 1])
    assert not w.ref_action.isEnabled()
    w.mode_combo.setCurrentIndex(w.mode_combo.findData('previous_delta'))
    np.testing.assert_array_equal(w.directions_view.projected, [1, 1])
    w.close()


def test_mixed_view_roundtrip_and_replay_navigation(app, tmp_path):
    w = make_window(app)
    for i in range(8):
        w.ingest(sample(i, [i, i*i, -i]))
    w.apply_components()
    w.set_reference()
    w.mode_combo.setCurrentIndex(1)
    w.evolution_combo.setCurrentIndex(1)
    w.trace_spins[0].setValue(2)
    path = save_state(tmp_path/'view.json', w.state, view=w.view_settings())
    assert w.open_capture(path)
    assert w.state.mode == 'reference_delta'
    assert w.evolution_combo.currentData() == 'traces'
    assert w.trace_spins[0].value() == 2
    np.testing.assert_array_equal(w.state.current().values, [7, 49, -7])
    np.testing.assert_array_equal(w.state.values(), [0, 0, 0])
    w.select_sequence(3)
    assert w.replay_index == 3 and not w.replay_playing
    w.go_live()
    assert w.state.selection().sequence == 7
    assert w.live_action.text() == 'Ir al final de la captura'
    w.close()


@pytest.mark.parametrize('view', [{'map_axes': 'bad'}, {'map_axes': [0]}, {'window': 900},
                                 {'evolution': 'unknown'}, {'trace_indices': [999]}])
def test_invalid_view_is_rejected(view):
    s = ViewerState([probe()], MonitorConfig())
    with pytest.raises(ValueError):
        validate_view(view, s)
