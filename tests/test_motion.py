import numpy as np
import pytest
from PySide6 import QtCore
from sonar_activaciones import MonitorConfig
from sonar_activaciones.app.window import MonitorWindow
from sonar_activaciones.processing.projection import component_basis
from .test_core import probe, sample


def window(app):
    w = MonitorWindow([probe()], MonitorConfig())
    w.timer.stop()
    w.receive_timer.stop()
    w.show()
    w.state.install_basis(component_basis(probe(), [0, 1]))
    return w


def test_idle_skips_render_but_new_capture_is_drawn(app):
    w = window(app)
    w.ingest(sample(0))
    w.tick()
    calls = []
    original = w.render
    def render(*args):
        calls.append(w.state.selection().sequence)
        return original(*args)
    w.render = render
    w.tick()
    assert not calls
    w.ingest(sample(1, [2, 3, 4]))
    w.tick()
    assert calls == [1]
    np.testing.assert_array_equal(w.matrix.displayed.ravel()[:3], [2, 3, 4])


def test_refresh_rate_changes_only_visual_timer(app):
    w = window(app)
    gate = w.state.config.capture_hz
    w.refresh_spin.setValue(20)
    assert w.timer.interval() == 50
    assert w.timer.timerType() == QtCore.Qt.TimerType.PreciseTimer
    assert w.state.config.capture_hz == gate
    assert w.state.config.render_hz == 20


@pytest.mark.parametrize('kind', ['change', 'traces', 'heat'])
def test_graphics_objects_are_reused_and_gaps_remain(app, kind):
    w = window(app)
    w.evolution_combo.setCurrentIndex(w.evolution_combo.findData(kind))
    for i in (0, 1, 3):
        w.ingest(sample(i, [i, 2*i, i+1]))
    w.render()
    h, d = w.history_view, w.directions_view
    objects = (h.selection_line, h.availability_points, *h.curves, *h.points,
               d.path, d.scatter, d.marker, d.bars)
    ids = tuple(map(id, objects))
    scene_count = len(h.scene().items())+len(d.graph.scene().items())
    for i in range(4, 34):
        w.ingest(sample(i, [i, 2*i, i+1]))
        w.render()
    assert ids == tuple(map(id, (h.selection_line, h.availability_points, *h.curves, *h.points,
                                d.path, d.scatter, d.marker, d.bars)))
    assert len(h.scene().items())+len(d.graph.scene().items()) == scene_count
    if kind == 'change':
        assert np.isnan(h.displayed[2]).all()


def test_clipping_and_missing_notices_do_not_reflow_panels(app):
    w = window(app)
    for i in range(128):
        w.ingest(sample(i, [.2, .3, .4]))
    w.render()
    app.processEvents()
    def geometry():
        return tuple((widget.mapTo(w, QtCore.QPoint()).y(), widget.height())
                     for widget in (w.matrix, w.directions_view.graph, w.history_view))
    before = geometry()
    for i in range(128, 140):
        w.ingest(sample(i, [4, 5, 6] if i % 2 else [.2, .3, .4]))
        w.render()
        app.processEvents()
        assert geometry() == before


def test_ranges_remain_fixed_for_data_inside_bounds(app):
    w = window(app)
    for i in range(10):
        w.ingest(sample(i, [i, i, i]))
    w.render()
    before = w.directions_view.plane.viewRange()
    w.ingest(sample(10, [5, 5, 5]))
    w.render()
    assert w.directions_view.plane.viewRange() == before
