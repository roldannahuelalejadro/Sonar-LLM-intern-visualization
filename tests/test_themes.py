import numpy as np
import pytest
from PySide6 import QtCore, QtGui

from sonar_activaciones import MonitorConfig
from sonar_activaciones.app import themes
from sonar_activaciones.app.window import MonitorWindow
from sonar_activaciones.processing.projection import component_basis
from .test_core import probe, sample


@pytest.fixture
def appearance_settings(tmp_path, monkeypatch):
    local = QtCore.QSettings(str(tmp_path/'appearance.ini'), QtCore.QSettings.Format.IniFormat)
    monkeypatch.setattr(themes, 'settings', lambda: local)
    return local


def populated(app):
    w = MonitorWindow([probe()], MonitorConfig())
    w.timer.stop()
    w.receive_timer.stop()
    w.state.install_basis(component_basis(probe(), [0, 1]))
    for i in range(12):
        w.ingest(sample(i, [i/20, i/30, i/40]))
    w.render()
    w.show()
    app.processEvents()
    return w


def test_theme_persists_and_invalid_preference_falls_back(app, appearance_settings):
    appearance_settings.setValue('appearance/theme', 'unknown')
    w = populated(app)
    assert w.theme_key == 'laboratorio'
    w.theme_combo.setCurrentIndex(w.theme_combo.findData('grafito'))
    assert appearance_settings.value('appearance/theme') == 'grafito'
    next_window = MonitorWindow([probe()], MonitorConfig())
    assert next_window.theme_key == 'grafito'
    assert next_window.theme_combo.currentData() == 'grafito'


def test_switch_preserves_data_objects_limits_and_panel_geometry(app, appearance_settings):
    w = populated(app)
    w.resize(900, 650)
    app.processEvents()
    h, d, m = w.history_view, w.directions_view, w.matrix
    objects = (m.image, m.colorbar, h.mesh, h.selection_line, *h.curves, d.path, d.marker)
    data = m.displayed.copy()
    lut = m.image.lut.copy()
    levels = m.image.getLevels().copy()
    ranges = [plot.viewRange() for plot in (m.plot, h.trace, d.plane)]
    panels = (m, h, d.graph)
    geometry = [widget.geometry() for widget in panels]
    selection = w.state.selection()
    for key in ('grafito', 'laboratorio', 'grafito'):
        w.theme_combo.setCurrentIndex(w.theme_combo.findData(key))
        w.render()
        app.processEvents()
        assert objects == (m.image, m.colorbar, h.mesh, h.selection_line, *h.curves, d.path, d.marker)
        np.testing.assert_array_equal(m.displayed, data)
        np.testing.assert_array_equal(m.image.lut, lut)
        np.testing.assert_array_equal(m.image.getLevels(), levels)
        assert [plot.viewRange() for plot in (m.plot, h.trace, d.plane)] == ranges
        assert [widget.geometry() for widget in panels] == geometry
        assert w.state.selection() is selection


@pytest.mark.parametrize('key', ['laboratorio', 'grafito'])
def test_axes_titles_legend_and_hidden_heat_follow_theme(app, appearance_settings, key):
    w = populated(app)
    themes.apply_window(w, key)
    color = QtGui.QColor(themes.THEMES[key].text)
    w.evolution_combo.setCurrentIndex(w.evolution_combo.findData('traces'))
    w.mode_combo.setCurrentIndex(w.mode_combo.findData('previous_delta'))
    w.render()
    plots = (w.matrix.plot, w.matrix.colorbar, w.history_view.trace,
             w.history_view.heat, w.directions_view.plane, w.directions_view.scores)
    for plot in plots:
        assert plot.getAxis('left').textPen().color() == color
        assert plot.titleLabel.opts['color'] == themes.THEMES[key].text
        assert plot.getAxis('left').labelStyle['color'] == themes.THEMES[key].text
    assert w.history_view.trace.legend.opts['labelTextColor'] == themes.THEMES[key].text
    dialog = w.pca_dialog
    assert dialog.palette().color(QtGui.QPalette.ColorRole.Text) == color
    icon = w.freeze_action.icon().pixmap(24, 24).toImage()
    visible = [icon.pixelColor(x, y) for x in range(icon.width()) for y in range(icon.height())
               if icon.pixelColor(x, y).alpha() > 200]
    assert visible and all(abs(c.red()-color.red()) <= 1 for c in visible)
    cache_count = len(w._standard_theme_icons)
    for _ in range(5):
        themes.apply_window(w, key, persist=False)
    assert len(w._standard_theme_icons) == cache_count
