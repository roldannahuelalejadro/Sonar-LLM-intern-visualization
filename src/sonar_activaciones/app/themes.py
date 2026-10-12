"""Window-scoped palettes; scientific data colors are deliberately unchanged."""
from dataclasses import dataclass

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets


@dataclass(frozen=True)
class Theme:
    name: str
    background: str
    surface: str
    text: str
    muted: str
    border: str
    hover: str
    accent: str
    warning: str
    empty: str


THEMES = {
    'laboratorio': Theme('Laboratorio', '#F3F5F7', '#FFFFFF', '#20262D',
                         '#56616D', '#CDD4DB', '#E2F0F2', '#167D8D', '#805510', '#DCE2E5'),
    'grafito': Theme('Grafito', '#191C20', '#24282E', '#E9EDF2',
                    '#A9B3BF', '#454D57', '#303D40', '#55C5BD', '#F0C477', '#343B44'),
}


def settings():
    return QtCore.QSettings('SONAR', 'Activaciones')


def saved_theme():
    value = settings().value('appearance/theme', 'laboratorio')
    return value if value in THEMES else 'laboratorio'


def standard_icon(window, symbol):
    sp = QtWidgets.QStyle.StandardPixmap
    neutral = (sp.SP_MediaPause, sp.SP_MediaPlay, sp.SP_MediaSkipBackward,
               sp.SP_MediaSkipForward, sp.SP_TitleBarMaxButton)
    if symbol in neutral:
        theme = THEMES[getattr(window, 'theme_key', None) or saved_theme()]
        if not hasattr(window, '_standard_theme_icons'):
            window._standard_theme_icons = {}
        cache_key = (theme.name, symbol)
        if cache_key in window._standard_theme_icons:
            return window._standard_theme_icons[cache_key]
        icon = window.style().standardIcon(symbol)
        tinted = QtGui.QIcon()
        for size in (16, 24, 32, 48):
            pixmap = icon.pixmap(size, size)
            painter = QtGui.QPainter(pixmap)
            painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), QtGui.QColor(theme.text))
            painter.end()
            tinted.addPixmap(pixmap)
        icon = tinted
        if not hasattr(window, '_theme_icons'):
            window._theme_icons = {}
        window._theme_icons[icon.cacheKey()] = symbol
        window._standard_theme_icons[cache_key] = icon
        return icon
    return window.style().standardIcon(symbol)


def palette(theme):
    result = QtGui.QPalette()
    role = QtGui.QPalette.ColorRole
    colors = {
        role.Window: theme.background, role.WindowText: theme.text,
        role.Base: theme.surface, role.AlternateBase: theme.background,
        role.Text: theme.text, role.Button: theme.surface, role.ButtonText: theme.text,
        role.ToolTipBase: theme.surface, role.ToolTipText: theme.text,
        role.Highlight: theme.accent,
        role.HighlightedText: '#191C20' if theme.name == 'Grafito' else '#FFFFFF',
        role.Link: theme.accent, role.PlaceholderText: theme.muted,
        role.Light: theme.border, role.Mid: theme.border, role.Dark: theme.border,
    }
    for key, value in colors.items():
        result.setColor(key, QtGui.QColor(value))
    for key in (role.Text, role.WindowText, role.ButtonText):
        result.setColor(QtGui.QPalette.ColorGroup.Disabled, key, QtGui.QColor(theme.muted))
    return result


def stylesheet(t):
    return f"""
        QMainWindow, QWidget {{ background: {t.background}; color: {t.text}; font-size: 13px; }}
        QToolBar {{ spacing: 5px; padding: 2px; border-bottom: 1px solid {t.border}; }}
        QComboBox, QSpinBox, QDoubleSpinBox {{ background: {t.surface}; padding: 4px; min-height: 21px; }}
        QLineEdit, QTextEdit, QPlainTextEdit, QAbstractItemView {{ background: {t.surface}; color: {t.text}; }}
        QAbstractItemView {{ selection-background-color: {t.accent}; }}
        QPushButton, QToolButton {{ padding: 3px; border-radius: 3px; }}
        QPushButton {{ background: {t.surface}; border: 1px solid {t.border}; }}
        QPushButton:hover, QToolButton:hover {{ background: {t.hover}; }}
        QToolButton:checked {{ background: {t.hover}; border: 1px solid {t.accent}; }}
        QWidget:disabled {{ color: {t.muted}; }}
        QSplitter::handle {{ background: {t.border}; }}
        QTabWidget::pane {{ border: 1px solid {t.border}; }}
        QTabBar::tab {{ padding: 9px 18px; background: {t.background}; }}
        QTabBar::tab:selected {{ background: {t.surface}; border-top: 2px solid {t.accent}; }}
        QStatusBar {{ border-top: 1px solid {t.border}; }}
        QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; }}
    """


def apply_plot(plot, theme, *, empty=False):
    plot.getViewBox().setBackgroundColor(theme.empty if empty else theme.surface)
    for entry in plot.axes.values():
        axis = entry['item']
        axis.setPen(pg.mkPen(theme.muted))
        axis.setTextPen(pg.mkPen(theme.text))
        axis.setLabel(**{'color': theme.text})
    plot.titleLabel.setText(plot.titleLabel.text, color=theme.text)
    if plot.legend is not None:
        plot.legend.setLabelTextColor(theme.text)


def apply_window(window, key, *, persist=True):
    theme = THEMES[key]
    window.theme_key = key
    window.setPalette(palette(theme))
    window.setStyleSheet(stylesheet(theme))
    for item in window.findChildren(QtGui.QAction) + window.findChildren(QtWidgets.QAbstractButton):
        symbol = getattr(window, '_theme_icons', {}).get(item.icon().cacheKey())
        if symbol is not None:
            item.setIcon(standard_icon(window, symbol))
    window.source_badge.setStyleSheet(f'color: {theme.warning}; padding: 8px; font-weight: 600;')
    h, d, m = window.history_view, window.directions_view, window.matrix
    for graph in (m, h, d.graph):
        graph.setBackground(theme.surface)
    for plot in (h.availability, h.trace, d.scores, d.plane):
        apply_plot(plot, theme)
    for plot in (m.plot, h.heat):
        apply_plot(plot, theme, empty=True)
    apply_plot(m.colorbar, theme)
    with QtCore.QSignalBlocker(window.theme_combo):
        window.theme_combo.setCurrentIndex(window.theme_combo.findData(key))
    if persist:
        settings().setValue('appearance/theme', key)
