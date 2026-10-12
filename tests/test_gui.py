import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6 import QtWidgets

from sonar_activaciones import MonitorConfig, Observation
from sonar_activaciones.app.main import _application
from sonar_activaciones.app.window import MonitorWindow
from .test_core import probe, sample


def test_matrix_orientation_padding_reference_and_freeze(app):
    p = probe(dimension=19)
    w = MonitorWindow([p], MonitorConfig())
    w.show()
    a = Observation.create(p, np.arange(19.) - 9, 0)
    w.ingest(a)
    w.render()
    app.processEvents()
    np.testing.assert_array_equal(w.matrix.displayed.ravel()[:19], a.values)
    assert np.isnan(w.matrix.displayed.ravel()[19:]).all()
    assert w.matrix.index_at(.5, 1.5) == 16
    assert w.matrix.index_at(5, 1) is None
    w.set_reference()
    w.mode_combo.setCurrentIndex(1)
    np.testing.assert_array_equal(w.state.values(), np.zeros(19))
    w.toggle_freeze(True)
    w.ingest(Observation.create(p, np.ones(19), 1))
    assert w.state.current().sequence == 0
    w.go_live()
    assert w.state.current().sequence == 1
    w.close()


def test_qt_thread_and_empty_window(app):
    w = MonitorWindow([], MonitorConfig())
    assert w.thread() == app.thread()
    assert w.state.current() is None
    w.close()


def test_direction_controls_and_background_pca(app):
    import time
    w = MonitorWindow([probe()], MonitorConfig())
    for i in range(16):
        w.ingest(sample(i, np.random.default_rng(i).normal(size=3)))
    w.maximize_panel(1)
    w.apply_components()
    np.testing.assert_allclose(w.directions_view.projected, w.state.current().values[:2])
    previous_id = w.state.bases["p"].basis_id
    w.start_pca()
    deadline = time.monotonic() + 5
    while w.pca_future is not None and time.monotonic() < deadline:
        app.processEvents()
        w.poll_pca()
        time.sleep(.005)
    assert w.pca_future is None
    assert w.state.bases["p"].basis_id != previous_id
    assert w.state.bases["p"].axis_names == ("PC1", "PC2")
    w.close()


def test_replay_controls_and_invalid_file_preserve_window(app, tmp_path):
    from sonar_activaciones.storage.capture import Capture, save_capture
    samples = tuple(sample(i, [i, 2*i, -i], captured_at=10+i*.01) for i in range(6))
    path = save_capture(tmp_path/"capture.json", Capture((probe(),), samples, {"p": samples[0]}, snapshot=samples[3]))
    w = MonitorWindow([], MonitorConfig())
    errors = []
    w.show_error = errors.append
    assert w.open_capture(path)
    assert w.state.current().sequence == 3
    assert "t relativo" in w.status_label.text()
    w.step_replay(-1)
    assert w.state.current().sequence == 2
    w.speed_spin.setValue(16)
    w.replay_play.setChecked(True)
    import time
    deadline = time.monotonic() + 3
    while w.replay_playing and time.monotonic() < deadline:
        w.tick()
        app.processEvents()
        time.sleep(.005)
    assert w.state.current().sequence == 5
    assert not w.open_capture(tmp_path/"missing.json")
    assert errors
    assert w.state.current().sequence == 5
    w.close()


@pytest.mark.parametrize("limit", [1e-9, 1e20])
def test_visual_scale_keeps_contract_range(app, limit):
    w = MonitorWindow([probe()], MonitorConfig(visual_limit=limit))
    assert w.scale_spin.value() == pytest.approx(limit)
    assert w.limit == pytest.approx(limit)
    w.close()


def test_projection_only_selection_clears_matrix_and_survives_reception(app):
    from sonar_activaciones.processing.projection import component_basis
    p = probe(dimension=4096)
    w = MonitorWindow([p], MonitorConfig(history_bytes=60000, recent_fraction=.05))
    w.show()
    w.state.install_basis(component_basis(p, [0, 1]))
    for i in range(60):
        w.ingest(Observation.create(p, np.ones(4096)*i, i))
    w.render()
    app.processEvents()
    assert all(v.isVisible() for v in (w.matrix, w.history_view, w.directions_view.graph))
    assert not w.inspector_dock.isVisible()
    w.directions_view.selected.emit(0)
    assert w.state.selection().sequence == 0
    assert w.state.current() is None
    assert np.isnan(w.matrix.displayed).all()
    np.testing.assert_array_equal(w.directions_view.projected, [0, 0])
    assert 'Solo proyeccion' in w.availability_label.text()
    w.ingest(Observation.create(p, np.ones(4096)*60, 60))
    w.render()
    assert w.state.selection().sequence == 0
    assert np.isnan(w.matrix.displayed).all()
    w.go_live()
    assert w.state.current().sequence == 60
    np.testing.assert_array_equal(w.matrix.displayed, np.full((16, 16), 60))
    w.close()


def test_navigation_covers_union_beyond_visual_window(app):
    w = MonitorWindow([probe()], MonitorConfig())
    for i in range(700):
        w.ingest(sample(i))
    w.render()
    assert len(w.navigation) == 700
    w.history_slider.setValue(0)
    assert w.state.selection().sequence == 0
    w.close()
