import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import sys
import math
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from ..contracts import Observation, MIB
from ..processing.memory import rss_bytes, pca_known_peak, header_cost
from ..storage.mixed import save_state, load_state
from ..processing.reference import magnitude
from ..processing.display import MODE_NAMES, unavailable_reason, projected_values
from .state import ViewerState
from .views.matrix import MatrixView
from .views.history import HistoryView
from ..processing.temporal import coordinates
from ..processing.projection import component_basis, fit_pca, load_basis, save_basis, MAX_PCA_BYTES
from .views.directions import DirectionsView
from .views.timing import NoticeLabel
from .themes import THEMES, saved_theme, apply_window, standard_icon
from ..storage.capture import Capture, save_capture, load_capture


def label(text="", *, wrap=False):
    widget = QtWidgets.QLabel(text)
    widget.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    return widget


class ScientificSpinBox(QtWidgets.QDoubleSpinBox):
    def textFromValue(self, value):
        return f"{value:.6g}"

    def valueFromText(self, text):
        return float(text.replace(",", "."))

    def validate(self, text, position):
        state = QtGui.QValidator.State
        try:
            value = self.valueFromText(text)
            valid = math.isfinite(value) and self.minimum() <= value <= self.maximum()
            return (state.Acceptable if valid else state.Intermediate, text, position)
        except ValueError:
            return (state.Intermediate if all(c in "0123456789eE+-,." for c in text) else state.Invalid, text, position)


class ComponentRangeSpinBox(QtWidgets.QSpinBox):
    dimension = 256

    def textFromValue(self, value):
        return f"{value*256}..{min(self.dimension-1, value*256+255)}"


class MonitorWindow(QtWidgets.QMainWindow):
    def __init__(self, probes, config, channel=None):
        super().__init__()
        self.config = config
        self.channel = channel
        self.state = ViewerState(probes, config)
        self.synthetic = bool(probes) and all(p.metadata.get("synthetic", False) for p in probes)
        self.limit = config.visual_limit
        self.inspected_index = 0
        self.last_drawn_key = None
        self.pending_live = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="SONAR-PCA")
        self.pca_future = None
        self.pca_probe = None
        self.pca_state = None
        self.source_closed = False
        self._tick_signature = None
        self._last_render_at = 0.
        self._rendered_probe = None
        self.replay = None
        self.replay_index = -1
        self.replay_positions = {}
        self.replay_playing = False
        self.replay_due = 0.0
        self.setWindowTitle("SONAR | DEMO SINTETICA" if self.synthetic else "SONAR | Activaciones")
        self.resize(1220, 800)
        self.setMinimumSize(860, 600)
        self._build()
        self._unify()
        apply_window(self, saved_theme(), persist=False)
        for button in self.findChildren(QtWidgets.QToolButton):
            button.setAccessibleName(button.toolTip() or button.text())
        self.timer = QtCore.QTimer(self)
        self.timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.timer.start(round(1000 / config.render_hz))
        self.receive_timer = QtCore.QTimer(self)
        self.receive_timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self.receive_timer.timeout.connect(self.receive)
        self.receive_timer.start(10)
        self.render()

    def change_theme(self):
        apply_window(self, self.theme_combo.currentData())

    def standard_icon(self, symbol):
        return standard_icon(self, symbol)

    def tool(self, name, icon, callback, checkable=False):
        action = QtGui.QAction(self.standard_icon(icon), name, self)
        action.setToolTip(name)
        action.setCheckable(checkable)
        action.triggered.connect(callback)
        return action

    def _build(self):
        top = self.addToolBar("Controles")
        top.setMovable(False)
        top.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        brand = label("SONAR")
        brand.setStyleSheet("font-size: 20px; font-weight: 700; padding-right: 12px;")
        top.addWidget(brand)
        self.probe_combo = QtWidgets.QComboBox()
        self.probe_combo.setMinimumWidth(180)
        for p in self.state.probes.values():
            self.probe_combo.addItem(p.name, p.probe_id)
        self.probe_combo.currentIndexChanged.connect(self.change_probe)
        top.addWidget(self.probe_combo)
        self.source_badge = label("DEMO SINTETICA" if self.synthetic else "SIN FUENTE" if not self.state.probes else "CONECTADO")
        self.source_badge.setStyleSheet("color: #815619; padding: 8px; font-weight: 600;")
        self.source_badge.setMaximumWidth(300)
        top.addWidget(self.source_badge)
        self.refresh_spin = QtWidgets.QDoubleSpinBox()
        self.refresh_spin.setRange(.5, 60)
        self.refresh_spin.setDecimals(1)
        self.refresh_spin.setValue(self.config.render_hz)
        self.refresh_spin.setPrefix('Vista ')
        self.refresh_spin.setSuffix(' Hz')
        self.refresh_spin.setMaximumWidth(125)
        self.refresh_spin.setToolTip('Frecuencia solicitada de dibujo; no cambia la captura ni inventa muestras')
        self.refresh_spin.valueChanged.connect(self.set_render_rate)
        top.addWidget(self.refresh_spin)
        self.theme_combo = QtWidgets.QComboBox()
        for key, theme in THEMES.items():
            self.theme_combo.addItem(theme.name, key)
        self.theme_combo.setFixedWidth(120)
        self.theme_combo.setAccessibleName('Tema de interfaz')
        self.theme_combo.setToolTip('Tema de interfaz: claro u oscuro; conserva los colores de los datos')
        self.theme_combo.currentIndexChanged.connect(self.change_theme)
        top.addWidget(self.theme_combo)
        self.addToolBarBreak()
        actions = self.addToolBar('Acciones')
        actions.setMovable(False)
        actions.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        sp = QtWidgets.QStyle.StandardPixmap
        self.freeze_action = self.tool("Pausar vista", sp.SP_MediaPause, self.toggle_freeze, True)
        self.live_action = self.tool("Volver al presente", sp.SP_MediaPlay, self.go_live)
        self.ref_action = self.tool("Fijar referencia", sp.SP_DialogApplyButton, self.set_reference)
        for action in (self.freeze_action, self.live_action, self.ref_action):
            actions.addAction(action)
        actions.addSeparator()
        self.save_action = self.tool("Guardar captura", sp.SP_DialogSaveButton, self.save_current_capture)
        self.open_action = self.tool("Abrir captura", sp.SP_DialogOpenButton, self.choose_capture)
        for action in (self.save_action, self.open_action):
            actions.addAction(action)
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        vertical = QtWidgets.QVBoxLayout(root)
        controls = QtWidgets.QHBoxLayout()
        self.mode_combo = QtWidgets.QComboBox()
        for value, text in MODE_NAMES.items():
            self.mode_combo.addItem(text, value)
        self.mode_combo.currentIndexChanged.connect(self.change_mode)
        controls.addWidget(self.mode_combo)
        controls.addWidget(label("Escala +/-"))
        self.scale_spin = ScientificSpinBox()
        self.scale_spin.setDecimals(12)
        self.scale_spin.setRange(1e-9, 1e30)
        self.scale_spin.setValue(self.limit)
        self.scale_spin.setMaximumWidth(125)
        self.scale_spin.valueChanged.connect(self.change_scale)
        controls.addWidget(self.scale_spin)
        self.auto_scale = QtWidgets.QToolButton()
        self.auto_scale.setIcon(self.style().standardIcon(sp.SP_DesktopIcon))
        self.auto_scale.setToolTip('Ajustar escala a seleccion')
        self.auto_scale.clicked.connect(self.fit_scale)
        controls.addWidget(self.auto_scale)
        controls.addWidget(label("Rango de componentes"))
        self.page_spin = ComponentRangeSpinBox()
        self.page_spin.setToolTip('Indices del vector; no es una capa del modelo')
        self.page_spin.valueChanged.connect(self.render)
        controls.addWidget(self.page_spin)
        controls.addStretch()
        self.frame_label = label()
        vertical.addLayout(controls)
        split = QtWidgets.QSplitter()
        vertical.addWidget(split, 1)
        self.tabs = QtWidgets.QTabWidget()
        self.matrix = MatrixView()
        self.matrix.inspected.connect(self.inspect)
        self.tabs.addTab(self.matrix, "Matriz")
        self.history_page = QtWidgets.QWidget()
        h_layout = QtWidgets.QVBoxLayout(self.history_page)
        h_controls = QtWidgets.QHBoxLayout()
        self.axis_combo = QtWidgets.QComboBox()
        for name, key in (("Secuencia", "sequence"), ("Tiempo", "time"), ("Posicion procesada", "token")):
            self.axis_combo.addItem(name, key)
        self.axis_combo.currentIndexChanged.connect(self.render)
        h_controls.addWidget(self.axis_combo)
        h_controls.addWidget(label("Ventana"))
        self.window_spin = QtWidgets.QSpinBox()
        self.window_spin.setRange(4, 512)
        self.window_spin.setValue(128)
        self.window_spin.valueChanged.connect(self.render)
        h_controls.addWidget(self.window_spin)
        self.traces_label = label("Componentes")
        h_controls.addWidget(self.traces_label)
        self.trace_spins = []
        for index in range(3):
            spin = QtWidgets.QSpinBox()
            spin.setValue(index)
            spin.valueChanged.connect(self.render)
            self.trace_spins.append(spin)
            h_controls.addWidget(spin)
        h_controls.addStretch()
        h_layout.addLayout(h_controls)
        self.history_view = HistoryView()
        h_layout.addWidget(self.history_view, 1)
        self.history_notice = NoticeLabel()
        h_layout.addWidget(self.history_notice)
        self.tabs.addTab(self.history_page, "Historia y trazas")
        self.directions_page = QtWidgets.QWidget()
        d_layout = QtWidgets.QVBoxLayout(self.directions_page)
        d_controls = QtWidgets.QHBoxLayout()
        d_controls.addWidget(label("Ejes"))
        self.axis_spins = []
        for index in (0, 1):
            spin = QtWidgets.QSpinBox()
            spin.setValue(index)
            self.axis_spins.append(spin)
            d_controls.addWidget(spin)
        apply_axes = QtWidgets.QPushButton("Aplicar componentes")
        apply_axes.setIcon(self.style().standardIcon(sp.SP_DialogApplyButton))
        apply_axes.clicked.connect(self.apply_components)
        d_controls.addWidget(apply_axes)
        self.import_basis_button = QtWidgets.QPushButton(self.style().standardIcon(sp.SP_DialogOpenButton), "Importar base")
        self.import_basis_button.clicked.connect(self.import_basis)
        d_controls.addWidget(self.import_basis_button)
        export_base = QtWidgets.QToolButton()
        export_base.setIcon(self.style().standardIcon(sp.SP_DialogSaveButton))
        export_base.setToolTip("Exportar base fija")
        export_base.clicked.connect(self.export_basis)
        d_controls.addWidget(export_base)
        d_controls.addStretch()
        d_layout.addLayout(d_controls)
        pca_controls = QtWidgets.QHBoxLayout()
        pca_controls.addWidget(label("Ventana PCA"))
        self.pca_count = QtWidgets.QSpinBox()
        self.pca_count.setRange(3, 512)
        self.pca_count.setValue(64)
        self.pca_count.setSuffix(' capturas')
        pca_controls.addWidget(self.pca_count)
        self.pca_button = QtWidgets.QPushButton("Calcular y fijar PCA (2D)")
        self.pca_button.setIcon(self.style().standardIcon(sp.SP_BrowserReload))
        self.pca_button.clicked.connect(self.start_pca)
        pca_controls.addWidget(self.pca_button)
        pca_controls.addStretch()
        d_layout.addLayout(pca_controls)
        self.basis_label = label("Sin base", wrap=True)
        d_layout.addWidget(self.basis_label)
        self.directions_view = DirectionsView()
        d_layout.addWidget(self.directions_view, 1)
        self.tabs.addTab(self.directions_page, "Direcciones")
        self.tabs.currentChanged.connect(self.render)
        for view in (self.matrix, self.history_view, self.directions_view.graph):
            view.painted.connect(self.on_painted)
        split.addWidget(self.tabs)
        sidebar = QtWidgets.QWidget()
        sidebar.setMaximumWidth(285)
        side = QtWidgets.QVBoxLayout(sidebar)
        self.descriptor_label = label(wrap=True)
        side.addWidget(self.descriptor_label)
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        side.addWidget(line)
        side.addWidget(label("COMPONENTE"))
        self.component_spin = QtWidgets.QSpinBox()
        self.component_spin.valueChanged.connect(self.inspect)
        side.addWidget(self.component_spin)
        self.inspector = label(wrap=True)
        self.inspector.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        side.addWidget(self.inspector)
        self.context_label = label(wrap=True)
        side.addWidget(self.context_label)
        self.stats_label = label(wrap=True)
        side.addWidget(self.stats_label)
        side.addStretch()
        self.memory_label = label(wrap=True)
        side.addWidget(self.memory_label)
        side_scroll = QtWidgets.QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        side_scroll.setWidget(sidebar)
        side_scroll.setMaximumWidth(290)
        split.addWidget(side_scroll)
        split.setSizes([870, 265])
        navigation = QtWidgets.QHBoxLayout()
        navigation.addWidget(label("Lectura"))
        self.history_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.history_slider.valueChanged.connect(self.navigate)
        self.navigation = []
        navigation.addWidget(self.history_slider, 1)
        self.navigation_label = label("-")
        navigation.addWidget(self.navigation_label)
        navigation.addWidget(label("Historial MiB"))
        self.budget_spin = QtWidgets.QSpinBox()
        self.budget_spin.setRange(1, 512)
        self.budget_spin.setValue(max(1, math.ceil(self.state.plan.total/MIB)))
        navigation.addWidget(self.budget_spin)
        vertical.addLayout(navigation)
        self.replay_controls = QtWidgets.QWidget()
        replay_layout = QtWidgets.QHBoxLayout(self.replay_controls)
        replay_layout.setContentsMargins(0, 0, 0, 0)
        for name, icon, callback in (("Anterior", sp.SP_MediaSkipBackward, lambda: self.step_replay(-1)),
                                      ("Siguiente", sp.SP_MediaSkipForward, lambda: self.step_replay(1))):
            button = QtWidgets.QToolButton()
            button.setIcon(self.standard_icon(icon))
            button.setToolTip(name)
            button.clicked.connect(callback)
            replay_layout.addWidget(button)
        self.replay_play = QtWidgets.QToolButton()
        self.replay_play.setIcon(self.standard_icon(sp.SP_MediaPlay))
        self.replay_play.setToolTip("Reproducir / pausar captura")
        self.replay_play.setCheckable(True)
        self.replay_play.toggled.connect(self.toggle_replay)
        replay_layout.addWidget(self.replay_play)
        replay_layout.addWidget(label("Velocidad"))
        self.speed_spin = QtWidgets.QDoubleSpinBox()
        self.speed_spin.setRange(.1, 16)
        self.speed_spin.setValue(1)
        self.speed_spin.setSuffix("x")
        replay_layout.addWidget(self.speed_spin)
        self.replay_label = label("Captura parcial")
        replay_layout.addWidget(self.replay_label, 1)
        self.replay_controls.hide()
        vertical.addWidget(self.replay_controls)
        self.status_label = label("Sin muestras")
        self.statusBar().addWidget(self.status_label, 1)
        self.counter_label = label()
        self.statusBar().addPermanentWidget(self.counter_label)

    def _unify(self):
        """Reuse the existing scientific views, with one selection and no tabs."""
        root = self.centralWidget().layout()
        split = self.tabs.parentWidget()
        side_scroll = split.widget(1)
        side_scroll.setParent(None)
        side_scroll.setMaximumWidth(16777215)
        self.inspector_dock = QtWidgets.QDockWidget("Inspector tecnico", self)
        self.inspector_dock.setWidget(side_scroll)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_dock)
        self.inspector_dock.hide()
        toolbar = self.findChildren(QtWidgets.QToolBar)[0]
        toolbar.addAction(self.inspector_dock.toggleViewAction())
        self.probe_combo.setMinimumWidth(120)
        self.probe_combo.setMaximumWidth(230)
        self.panels = []
        self.panel_titles = []
        self.tabs.blockSignals(True)
        self.matrix_page = QtWidgets.QWidget()
        matrix_layout = QtWidgets.QVBoxLayout(self.matrix_page)
        matrix_layout.setContentsMargins(0, 0, 0, 0)
        self.matrix_notice = NoticeLabel()
        matrix_layout.addWidget(self.matrix_notice)
        self.matrix.setParent(self.matrix_page)
        matrix_layout.addWidget(self.matrix, 1)
        self.matrix.show()
        self.trace_selected_button = QtWidgets.QPushButton('Usar componente seleccionada en trazas')
        self.trace_selected_button.clicked.connect(self.trace_inspected)
        matrix_layout.addWidget(self.trace_selected_button)
        for title, widget in (("Matriz", self.matrix_page), ("Mapa representacional", self.directions_page),
                              ("Historial de capturas", self.history_page)):
            widget.setParent(None)
            panel = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 0, 0)
            bar = QtWidgets.QHBoxLayout()
            title_label = label(title)
            self.panel_titles.append(title_label)
            bar.addWidget(title_label)
            bar.addStretch()
            button = QtWidgets.QToolButton()
            button.setIcon(self.standard_icon(QtWidgets.QStyle.StandardPixmap.SP_TitleBarMaxButton))
            button.setToolTip("Maximizar / restaurar panel")
            button.clicked.connect(lambda checked=False, n=len(self.panels): self.maximize_panel(n))
            bar.addWidget(button)
            layout.addLayout(bar)
            layout.addWidget(widget, 1)
            widget.show()
            self.panels.append(panel)
        upper = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        upper.addWidget(self.panels[0])
        upper.addWidget(self.panels[1])
        upper.setSizes([500, 650])
        self.visual_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.visual_split.addWidget(upper)
        self.visual_split.addWidget(self.panels[2])
        self.visual_split.setSizes([350, 270])
        self.maximized_panel = None
        root.replaceWidget(split, self.visual_split)
        self.tabs.blockSignals(True)
        split.hide()
        split.deleteLater()
        # Remove the immediate legacy quota control; new settings require Apply.
        navigation = root.itemAt(2).layout()
        while navigation.count() > 3:
            item = navigation.takeAt(3)
            if item.widget():
                item.widget().hide()
        self.memory_box = QtWidgets.QGroupBox("Presupuesto de datos de SONAR")
        memory_layout = QtWidgets.QVBoxLayout(self.memory_box)
        row = QtWidgets.QHBoxLayout()
        self.budget_spin.setRange(1, 2048)
        self.budget_spin.setSuffix(" MiB")
        self.budget_spin.show()
        row.addWidget(self.budget_spin)
        self.retention_combo = QtWidgets.QComboBox()
        self.retention_combo.addItem("Combinado", "combined")
        self.retention_combo.addItem("Detalle", "detail")
        self.retention_combo.setCurrentIndex(0 if self.config.retention_mode == "combined" else 1)
        row.addWidget(self.retention_combo)
        self.fraction_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.fraction_slider.setRange(5, 95)
        self.fraction_slider.setValue(round(100*self.config.recent_fraction))
        self.fraction_slider.setToolTip("Porcentaje del remanente para vectores recientes")
        row.addWidget(label("Detalle"))
        row.addWidget(self.fraction_slider, 1)
        self.fraction_label = label()
        row.addWidget(self.fraction_label)
        self.work_spin = QtWidgets.QSpinBox()
        self.work_spin.setRange(0, 512)
        self.work_spin.setValue(self.config.work_bytes//MIB)
        self.work_spin.setSuffix(" MiB trabajo")
        self.work_spin.setToolTip("Reserva para PCA y archivos; no incluye workspace opaco de bibliotecas")
        row.addWidget(self.work_spin)
        apply_button = QtWidgets.QPushButton(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogApplyButton), "Aplicar")
        apply_button.clicked.connect(self.apply_memory)
        row.addWidget(apply_button)
        memory_layout.addLayout(row)
        self.memory_preview = label(wrap=True)
        memory_layout.addWidget(self.memory_preview)
        self.weights_edit = QtWidgets.QLineEdit()
        self.weights_edit.setPlaceholderText("Pesos por sonda en orden de registro, separados por coma (vacio = iguales)")
        self.weights_edit.setText(",".join(map(str, self.config.probe_weights)))
        memory_layout.addWidget(self.weights_edit)
        self.memory_box.hide()
        root.insertWidget(1, self.memory_box)
        memory_action = toolbar.addAction("Memoria")
        memory_action.setCheckable(True)
        memory_action.toggled.connect(self.memory_box.setVisible)
        memory_action.toggled.connect(self.preview_memory)
        for signal in (self.budget_spin.valueChanged, self.work_spin.valueChanged, self.fraction_slider.valueChanged,
                       self.retention_combo.currentIndexChanged, self.weights_edit.textChanged):
            signal.connect(self.preview_memory)
        self.pca_button.setText("Crear mapa PCA")
        self.pca_button.setToolTip("PCA fija sobre ventana retenida; workspace LAPACK externo al presupuesto")
        self.pca_axes = QtWidgets.QSpinBox()
        self.pca_axes.setRange(1, 32)
        self.pca_axes.setValue(2)
        self.pca_axes.setPrefix("k=")
        self.directions_page.layout().itemAt(1).layout().insertWidget(2, self.pca_axes)
        segment_row = QtWidgets.QHBoxLayout()
        self.segment_combo = QtWidgets.QComboBox()
        self.segment_combo.setMinimumContentsLength(12)
        self.segment_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.segment_combo.currentIndexChanged.connect(self.choose_segment)
        segment_row.addWidget(self.segment_combo, 1)
        self.map_axes = []
        for index in (0, 1):
            combo = QtWidgets.QComboBox()
            combo.setMinimumContentsLength(4)
            combo.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setToolTip('Horizontal' if index == 0 else 'Vertical')
            combo.currentIndexChanged.connect(self.render)
            self.map_axes.append(combo)
        retire = QtWidgets.QToolButton()
        retire.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_TrashIcon))
        retire.setToolTip("Retirar segmento seleccionado y sus coordenadas")
        retire.clicked.connect(self.retire_segment)
        segment_row.addWidget(retire)
        self.directions_page.layout().insertLayout(2, segment_row)
        self.map_settings = QtWidgets.QWidget()
        settings_layout = QtWidgets.QVBoxLayout(self.map_settings)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        for _ in range(2):
            settings_layout.addLayout(self.directions_page.layout().takeAt(0).layout())
        self.directions_page.layout().insertWidget(1, self.map_settings)
        self.map_settings.hide()
        self.pca_estimate = label(wrap=True)
        settings_layout.addWidget(self.pca_estimate)
        settings_button = QtWidgets.QToolButton()
        settings_button.setIcon(self.standard_icon(QtWidgets.QStyle.StandardPixmap.SP_FileDialogDetailedView))
        settings_button.setToolTip('Bases, componentes y PCA')
        settings_button.setCheckable(True)
        settings_button.toggled.connect(self.map_settings.setVisible)
        segment_row.addWidget(settings_button)
        # Keep the base selector available in advanced settings, without taking
        # an entire row away from the plane in the combined view.
        settings_layout.insertWidget(0, self.segment_combo)
        settings_layout.insertWidget(1, retire)
        axes_row = QtWidgets.QHBoxLayout()
        for name, combo in zip(('Horizontal', 'Vertical'), self.map_axes):
            axes_row.addWidget(label(name))
            axes_row.addWidget(combo, 1)
        self.directions_page.layout().insertLayout(1, axes_row)
        actions_row = QtWidgets.QHBoxLayout()
        actions_row.addWidget(self.pca_button)
        self.import_basis_button.setText('Cargar base')
        actions_row.addWidget(self.import_basis_button)
        actions_row.addWidget(settings_button)
        actions_row.addStretch()
        self.directions_page.layout().insertLayout(0, actions_row)
        settings_layout.addWidget(label('Componentes directas: coordenadas originales, no resumen del vector completo.', wrap=True))
        self.pca_dialog = QtWidgets.QDialog(self)
        self.pca_dialog.setWindowTitle('Preparar base PCA')
        self.pca_dialog.resize(470, 230)
        pca_layout = QtWidgets.QVBoxLayout(self.pca_dialog)
        pca_row = QtWidgets.QHBoxLayout()
        pca_row.addWidget(label('Ventana PCA'))
        pca_row.addWidget(self.pca_count)
        pca_row.addWidget(label('Ejes'))
        pca_row.addWidget(self.pca_axes)
        pca_layout.addLayout(pca_row)
        pca_layout.addWidget(self.pca_estimate)
        self.pca_start_button = QtWidgets.QPushButton('Calcular base fija')
        self.pca_start_button.clicked.connect(self.start_pca)
        pca_layout.addWidget(self.pca_start_button)
        self.pca_button.clicked.disconnect(self.start_pca)
        self.pca_button.clicked.connect(self.prepare_pca)
        self.pca_count.valueChanged.connect(self.render_directions)
        self.pca_axes.valueChanged.connect(self.render_directions)
        self.evolution_combo = QtWidgets.QComboBox()
        for name, key in (('Cambio entre capturas', 'change'), ('Trazas de componentes', 'traces'), ('Mapa de calor', 'heat')):
            self.evolution_combo.addItem(name, key)
        self.change_space = QtWidgets.QComboBox()
        self.change_space.addItem('Espacio completo', 'full')
        self.change_space.addItem('Espacio proyectado', 'projected')
        for combo in (self.evolution_combo, self.change_space):
            combo.currentIndexChanged.connect(self.render)
        history_controls = self.history_page.layout().itemAt(0).layout()
        history_controls.insertWidget(0, self.change_space)
        history_controls.insertWidget(0, self.evolution_combo)
        self.evolution_combo.setMaximumWidth(185)
        self.change_space.setMaximumWidth(150)
        self.axis_combo.setMaximumWidth(140)
        self.window_spin.setMaximumWidth(78)
        for spin in self.trace_spins:
            spin.setMaximumWidth(65)
        self.history_view.set_compact(True)
        self.directions_view.set_compact(True)
        self.history_page.layout().setContentsMargins(0, 0, 0, 0)
        self.directions_page.layout().setContentsMargins(0, 0, 0, 0)
        self.directions_view.selected.connect(self.select_sequence)
        self.history_view.selected.connect(self.select_sequence)
        self.availability_label = label(wrap=True)
        header = QtWidgets.QWidget()
        header_row = QtWidgets.QHBoxLayout(header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.addWidget(self.frame_label, 1)
        self.availability_label.setMaximumWidth(245)
        self.availability_label.setWordWrap(False)
        header_row.addWidget(self.availability_label)
        root.insertWidget(1, header)
        self.empty_source = QtWidgets.QWidget()
        empty_row = QtWidgets.QHBoxLayout(self.empty_source)
        empty_row.addWidget(label('Sin fuente'))
        for text, callback in (('Abrir captura', self.choose_capture), ('Demo sintetica', self.launch_demo), ('Ejemplo SDK', self.open_sdk_example)):
            button = QtWidgets.QPushButton(text)
            button.clicked.connect(callback)
            empty_row.addWidget(button)
        empty_row.addStretch()
        root.insertWidget(1, self.empty_source)
        self.preview_memory()
        for layout in self.findChildren(QtWidgets.QVBoxLayout):
            layout.setSpacing(3)
        for layout in self.findChildren(QtWidgets.QHBoxLayout):
            layout.setSpacing(4)
        self.visual_split.setSizes([260, 210])
        self.history_view.setMinimumHeight(140)
        self.directions_view.graph.setMinimumHeight(110)
        self.history_notice.setFixedHeight(self.history_notice.fontMetrics().height()+6)
        self.history_notice.setWordWrap(False)
        self.history_notice.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)

    def maximize_panel(self, index=None):
        self.maximized_panel = None if index == self.maximized_panel else index
        for i, panel in enumerate(self.panels):
            panel.setVisible(self.maximized_panel is None or i == self.maximized_panel)
        self.visual_split.widget(0).setVisible(self.maximized_panel != 2)
        self.history_view.set_compact(self.maximized_panel != 2)
        self.directions_view.set_compact(self.maximized_panel != 1)
        self.render()

    def set_history_controls(self, detailed):
        traces = self.evolution_combo.currentData() == 'traces'
        self.traces_label.setVisible(traces)
        for spin in self.trace_spins:
            spin.setVisible(traces)
        self.change_space.setVisible(self.evolution_combo.currentData() == 'change')

    def proposed_config(self):
        weights = tuple(float(x.strip()) for x in self.weights_edit.text().split(",") if x.strip())
        return replace(self.state.config, history_bytes=None, data_budget_bytes=self.budget_spin.value()*MIB,
                       recent_fraction=self.fraction_slider.value()/100, retention_mode=self.retention_combo.currentData(),
                       work_bytes=self.work_spin.value()*MIB, probe_weights=weights)

    def preview_memory(self, *_):
        self.fraction_label.setText(f"{self.fraction_slider.value()}%")
        try:
            plan, impact = self.state.preview_config(self.proposed_config())
            capacities = plan.capacities(self.state.probes.values())
            text = f"Reservas {plan.reserved/MIB:.2f} MiB; vectores {sum(plan.recent.values())/MIB:.2f} MiB; "
            text += f"proyecciones {sum(plan.projected.values())/MIB:.2f} MiB. "
            text += f"Al aplicar: {impact['detail_lost']} pierden detalle, {impact['captures_retired']} desaparecen.\n"
            text += " | ".join(f"{pid}: ~{v['recent_approx']} vectores / ~{v['projected_approx']} proyecciones (k=2, contexto vacio)"
                                for pid, v in capacities.items())
            self.memory_preview.setText(text)
        except ValueError as exc:
            self.memory_preview.setText(str(exc))

    def apply_memory(self):
        try:
            self.state.reconfigure(self.proposed_config())
            self.config = self.state.config
            self.render()
            self.preview_memory()
        except ValueError as exc:
            self.show_error(str(exc))

    def select_sequence(self, sequence):
        try:
            if self.replay is not None:
                self.replay_play.setChecked(False)
            self.state.freeze_sequence(int(sequence))
            if self.replay is not None:
                self.replay_index = next(i for i, f in enumerate(self.state.navigation_samples(limit=None)) if f.sequence == int(sequence))
            self.freeze_action.setChecked(True)
            self.render()
        except ValueError as exc:
            self.show_error(str(exc))

    def choose_segment(self):
        self.state.selected_segment = self.segment_combo.currentData()
        self.render()

    def retire_segment(self):
        sid = self.state.selected_segment
        if sid is not None:
            try:
                self.state.retire_segment(sid)
                self.render()
            except ValueError as exc:
                self.show_error(str(exc))

    def change_probe(self):
        probe_id = self.probe_combo.currentData()
        if probe_id:
            self.state.select_probe(probe_id)
            self.freeze_action.setChecked(False)
            self.page_spin.setValue(0)
            self.render()

    def navigate(self, index):
        if index < len(self.navigation):
            try:
                if self.replay is not None:
                    self.replay_play.setChecked(False)
                    self.seek_replay(index)
                    return
                self.state.freeze_sequence(self.navigation[index].sequence, self.window_spin.value())
                self.freeze_action.setChecked(True)
                self.render()
            except ValueError as exc:
                self.show_error(str(exc))

    def resize_history(self, mib):
        self.state.resize_history(mib * 1024**2)
        self.freeze_action.setChecked(False)
        self.render()

    def capture_state(self):
        by_key = {(s.probe_id, s.sequence): s for s in self.state.history.samples()}
        if self.state.frozen and self.state.frozen.payload is not None:
            s = self.state.frozen.observation()
            by_key[(s.probe_id, s.sequence)] = s
        samples = tuple(sorted(by_key.values(), key=lambda s: (s.captured_at, s.probe_id, s.sequence)))
        counters = self.channel.snapshot() if self.channel else {}
        view = {"mode": self.state.mode, "selected_probe": self.state.selected_probe, "visual_limit": self.limit,
                "component": self.component_spin.value(), "page": self.page_spin.value(),
                "window": self.window_spin.value(), "axis": self.axis_combo.currentData(),
                "trace_indices": [s.value() for s in self.trace_spins]}
        return Capture(tuple(self.state.probes.values()), samples, dict(self.state.references), dict(self.state.bases),
                       dict(self.state.basis_starts), self.state.current(), view, counters, self.state.history.evicted)

    def save_current_capture(self):
        if self.state.selection() is None:
            self.show_error("No hay lecturas para guardar")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Guardar ventana retenida", "captura.json", "SONAR JSON (*.json)")
        if path:
            try:
                save_state(path, self.state, limit=self.window_spin.value(),
                           view=self.view_settings(),
                           counters=self.channel.snapshot() if self.channel else {})
                self.statusBar().showMessage("Captura parcial guardada (JSON + NPZ)", 6000)
            except (ValueError, OSError) as exc:
                self.show_error(str(exc))

    def choose_capture(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Abrir captura", "", "SONAR JSON (*.json)")
        if path:
            self.open_capture(path)

    def open_capture(self, path):
        try:
            if self.channel is not None:
                # A live producer stays attached only to its original viewer.
                started, _ = QtCore.QProcess.startDetached(sys.executable, ["-m", "sonar_activaciones", "replay", str(path)])
                if not started:
                    raise OSError("No se pudo abrir el visor de reproduccion independiente")
                return True
            if self.pca_future is not None:
                raise ValueError("Esperar a que termine la PCA antes de cambiar de captura")
            def choose_reference(ids):
                chosen, ok = QtWidgets.QInputDialog.getItem(self, 'Referencia de captura anterior',
                    'SONAR 0.2 conserva una referencia. Elegir la sonda cuya referencia se importara:', ids, 0, False)
                return chosen if ok else None
            state, view, counters = load_state(path, self.config, self.state.work, choose_reference=choose_reference)
            mode = view.get("mode", "raw")
            if mode not in ("raw", "reference_delta", "previous_delta"):
                raise ValueError("Modo de captura invalido")
            limit = view.get("visual_limit", 1.)
            if not isinstance(limit, (int, float)) or not math.isfinite(limit) or not 1e-9 <= limit <= 1e30:
                raise ValueError("Escala de captura invalida")
            self.replay_play.setChecked(False)
            self.replay = True
            self.state = state
            self.synthetic = all(p.metadata.get("synthetic", False) for p in state.probes.values())
            self.probe_combo.blockSignals(True)
            self.probe_combo.clear()
            for p in state.probes.values():
                self.probe_combo.addItem(p.name, p.probe_id)
            selected = state.selected_probe
            self.probe_combo.setCurrentIndex(self.probe_combo.findData(selected))
            self.probe_combo.blockSignals(False)
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(self.mode_combo.findData(mode))
            self.state.mode = self.mode_combo.currentData()
            self.mode_combo.blockSignals(False)
            self.limit = limit
            self.scale_spin.setValue(self.limit)
            self.source_badge.setText("REPRODUCCION" + (" | SINTETICA" if self.synthetic else ""))
            self.setWindowTitle("SONAR | Reproduccion" + (" sintetica" if self.synthetic else ""))
            self.replay_controls.show()
            self.replay_label.setText("Captura parcial: solo datos retenidos; sin reconstruccion")
            self.counter_label.setText(f"Perdidas originales: {counters.get('transport_dropped', 0)}")
            self.component_spin.setValue(view.get("component", 0))
            self.page_spin.setValue(view.get("page", 0))
            self.window_spin.setValue(view.get("window", 128))
            self.axis_combo.setCurrentIndex(max(0, self.axis_combo.findData(view.get("axis", "sequence"))))
            for spin, value in zip(self.trace_spins, view.get("trace_indices", [0, 1, 2])):
                spin.setValue(value)
            self.evolution_combo.setCurrentIndex(max(0, self.evolution_combo.findData(view.get('evolution', 'change'))))
            self.change_space.setCurrentIndex(max(0, self.change_space.findData(view.get('change_space', 'full'))))
            self._restore_axes = view.get('map_axes', [0, 1])
            self.render()
            selection = self.state.selection()
            self.replay_index = next((i for i, f in enumerate(self.navigation) if selection and f.sequence == selection.sequence), 0)
            return True
        except (ValueError, OSError) as exc:
            self.show_error(str(exc))
            return False

    def seek_replay(self, index):
        if self.replay is None:
            return
        frames = self.state.navigation_samples(limit=None)
        if not frames:
            return
        index = min(max(0, index), len(frames)-1)
        self.state.freeze_sequence(frames[index].sequence)
        self.replay_index = index
        self.render()

    def step_replay(self, direction):
        if self.replay is None:
            return
        self.replay_play.setChecked(False)
        self.seek_replay(self.replay_index+direction)

    def toggle_replay(self, playing):
        if self.replay is None:
            return
        self.replay_playing = playing
        icon = QtWidgets.QStyle.StandardPixmap.SP_MediaPause if playing else QtWidgets.QStyle.StandardPixmap.SP_MediaPlay
        self.replay_play.setIcon(self.standard_icon(icon))
        if playing:
            if self.replay_index >= len(self.navigation)-1:
                self.seek_replay(0)
            self.replay_due = time.monotonic() + self.replay_interval()

    def replay_interval(self):
        samples = self.state.navigation_samples(limit=None)
        if self.replay_index >= len(samples)-1:
            return 0
        return max(0, samples[self.replay_index+1].captured_at-samples[self.replay_index].captured_at) / self.speed_spin.value()

    def advance_replay(self):
        steps = 0
        while self.replay_playing and time.monotonic() >= self.replay_due and steps < self.config.max_receive_per_tick:
            if self.replay_index >= len(self.navigation)-1:
                self.replay_play.setChecked(False)
                break
            self.replay_index += 1
            self.state.freeze_sequence(self.navigation[self.replay_index].sequence)
            self.replay_due += self.replay_interval()
            steps += 1

    def change_mode(self):
        self.state.mode = self.mode_combo.currentData()
        self.render()

    def apply_components(self):
        probe = self.state.probes.get(self.state.selected_probe)
        if probe is None:
            return
        try:
            indices = list(dict.fromkeys(s.value() for s in self.axis_spins))
            self.state.work.acquire("Base por componentes", probe.dimension*(len(indices)+2)*8*4+65536)
            try:
                self.state.install_basis(component_basis(probe, indices))
                self.state.process_reprojections()
            finally:
                self.state.work.release()
            self.render()
        except ValueError as exc:
            self.show_error(str(exc))

    def import_basis(self):
        if not self.state.selected_probe:
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Importar base", "", "SONAR JSON (*.json)")
        if path:
            try:
                def admit(document, shapes, json_size):
                    self.state.work.acquire('Importar base', 3*sum(s[2] for s in shapes.values())+32*json_size+MIB)
                if self.state.work.active:
                    raise ValueError('Esperar al trabajo en curso')
                try:
                    basis = load_basis(path, self.state.probes[self.state.selected_probe], admission=admit)
                    self.state.install_basis(basis)
                finally:
                    self.state.work.release()
                self.render()
            except (ValueError, OSError) as exc:
                self.show_error(str(exc))

    def export_basis(self):
        segment = self.state.segments.get(self.state.selected_segment)
        basis = segment['basis'] if segment else None
        if basis is None:
            self.show_error("No hay una base aplicada")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Exportar base", "base.json", "SONAR JSON (*.json)")
        if path:
            try:
                self.state.work.acquire('Exportar base', basis.nbytes*2+MIB)
                try:
                    save_basis(path, basis)
                finally:
                    self.state.work.release()
            except (ValueError, OSError) as exc:
                self.show_error(str(exc))

    def start_pca(self):
        if self.pca_future is not None or not self.state.selected_probe:
            return
        try:
            samples = self.state.pca_snapshot(self.pca_count.value(), self.pca_axes.value())
        except ValueError as exc:
            self.show_error(str(exc))
            return
        self.pca_probe = self.state.selected_probe
        self.pca_state = self.state
        self.pca_descriptor = self.state.probes[self.pca_probe]
        self.pca_future = self.executor.submit(fit_pca, samples, self.pca_axes.value())
        self.pca_dialog.hide()
        self.pca_button.setEnabled(False)
        self.pca_button.setText("Calculando PCA...")

    def poll_pca(self):
        if self.pca_future is not None and self.pca_future.done():
            future, self.pca_future = self.pca_future, None
            self.pca_button.setEnabled(True)
            self.pca_button.setText("Crear nueva base PCA")
            try:
                if self.state is not self.pca_state or self.state.probes.get(self.pca_probe) != self.pca_descriptor:
                    raise ValueError('Resultado PCA descartado: el contexto de origen ya no es valido')
                self.state.install_basis(future.result(), self.pca_probe)
            except (ValueError, KeyError, np.linalg.LinAlgError) as exc:
                self.show_error(str(exc))
            finally:
                self.pca_state.work.release()
                self.pca_state = None
            self.render()

    def prepare_pca(self):
        self.render_directions()
        self.pca_dialog.show()
        self.pca_dialog.raise_()

    def fit_scale(self):
        values = self.state.values()
        if values is not None:
            self.scale_spin.setValue(max(1e-9, float(np.max(np.abs(values)))))

    def trace_inspected(self):
        self.trace_spins[0].setValue(self.inspected_index)
        self.evolution_combo.setCurrentIndex(self.evolution_combo.findData('traces'))

    def launch_demo(self):
        started, _ = QtCore.QProcess.startDetached(sys.executable, ['-m', 'sonar_activaciones', 'demo'])
        if not started:
            self.show_error('No se pudo iniciar la demo sintetica')

    def open_sdk_example(self):
        from pathlib import Path
        path = Path(__file__).resolve().parents[3] / 'examples' / 'manual.py'
        if not path.exists() or not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path))):
            self.show_error('Ejemplo SDK: consultar examples/manual.py y docs/INTEGRATION.md en el repositorio')

    def view_settings(self):
        return {'mode': self.state.mode, 'visual_limit': self.limit, 'component': self.component_spin.value(),
                'page': self.page_spin.value(), 'window': self.window_spin.value(), 'axis': self.axis_combo.currentData(),
                'trace_indices': [s.value() for s in self.trace_spins], 'evolution': self.evolution_combo.currentData(),
                'change_space': self.change_space.currentData(), 'map_axes': [max(0, s.currentIndex()) for s in self.map_axes]}

    def change_scale(self, value):
        self.limit = value
        self.render()

    def inspect(self, index):
        self.inspected_index = index
        self.component_spin.blockSignals(True)
        self.component_spin.setValue(index)
        self.component_spin.blockSignals(False)
        self.render_inspector()

    def set_reference(self):
        try:
            self.state.set_reference()
            self.render()
        except ValueError as exc:
            self.show_error(str(exc))

    def toggle_freeze(self, checked):
        if self.replay is not None:
            self.replay_play.setChecked(not checked)
            self.render()
            return
        if checked:
            try:
                self.state.freeze()
            except ValueError as exc:
                self.show_error(str(exc))
        else:
            self.state.live()
        self.freeze_action.setChecked(self.state.frozen is not None)
        self.render()

    def go_live(self):
        if self.replay is not None:
            self.replay_play.setChecked(False)
            self.seek_replay(len(self.navigation)-1)
            return
        self.state.live()
        self.freeze_action.setChecked(False)
        self.render()

    def show_error(self, message):
        QtWidgets.QMessageBox.warning(self, "SONAR", message)

    def ingest(self, sample):
        self.state.ingest(sample)

    def set_render_rate(self, hz):
        self.config = replace(self.config, render_hz=hz)
        self.state.config = replace(self.state.config, render_hz=hz)
        if hasattr(self, 'timer'):
            self.timer.start(max(1, round(1000/hz)))

    def tick(self):
        self.poll_pca()
        if self.replay is not None:
            self.advance_replay()
        signature = (self.state.revision, self.state.received_count, len(self.state.reprojection),
                     self.source_closed, self.replay_index)
        if signature == self._tick_signature and time.monotonic()-self._last_render_at < 1:
            return
        start_ns = time.perf_counter_ns()
        self.render()
        self._tick_signature = signature
        if self.channel and self.state.selection() is not None:
            self.channel.add("draw_ns_total", time.perf_counter_ns()-start_ns)
            self.channel.add("scene_updates")

    def receive(self):
        self.state.process_reprojections()
        count = 0
        received_keys = set()
        if self.channel:
            if self.channel.stop.is_set():
                self.close()
                return
            if self.channel.disconnected.is_set():
                self.source_closed = True
                return
            start = time.perf_counter()
            while count < self.config.max_receive_per_tick:
                if (time.perf_counter() - start) * 1000 > self.config.receive_budget_ms:
                    break
                packet = self.channel.try_get()
                if packet is None:
                    break
                try:
                    sample = Observation.unpack(packet)
                    self.ingest(sample)
                except (ValueError, KeyError, TypeError):
                    self.channel.add("invalid_received")
                    continue
                self.channel.received(sample)
                count += 1
                received_keys.add((sample.probe_id, sample.sequence))
        if self.channel and count:
            current = self.state.selection()
            key = None if current is None else (current.probe_id, current.sequence)
            candidate = self.state.frozen is None and key in received_keys
            if candidate:
                if self.pending_live is not None:
                    self.channel.add("received_not_drawn")
                self.pending_live = (key, current.captured_at)
            self.channel.add("received_not_drawn", count-int(candidate))

    def on_painted(self, key, elapsed_ns):
        if self.channel:
            self.channel.add("paint_count")
            self.channel.add("paint_ns_total", elapsed_ns)
            if self.pending_live is not None and self.pending_live[0] == key:
                self.channel.add("drawn")
                self.channel.add("render_latency_ns_total", max(0, int((time.monotonic()-self.pending_live[1])*1e9)))
                self.pending_live = None

    def render(self, *_):
        if not hasattr(self, 'availability_label'):
            return
        self._last_render_at = time.monotonic()
        if self.channel:
            counters = self.channel.snapshot()
            self.counter_label.setText(f"Recibidas {counters['received']} | Descartadas {counters['transport_dropped']} | Gate {counters['gate_skipped']}")
            self.counter_label.setToolTip(f"Recibidas no dibujadas: {counters['received_not_drawn']}; dibujadas: {counters['drawn']}")
        sample = self.state.current()
        selected = self.state.selection()
        key = None if selected is None else (selected.probe_id, selected.sequence)
        for view in (self.matrix, self.history_view, self.directions_view.graph):
            view.paint_key = key
        p = self.state.probes.get(self.state.selected_probe)
        if p and p is not self._rendered_probe:
            self.page_spin.dimension = p.dimension
            self.page_spin.setMaximum((p.dimension-1)//256)
            self.component_spin.setMaximum(p.dimension-1)
            for spin in self.trace_spins:
                spin.blockSignals(True)
                spin.setMaximum(p.dimension-1)
                spin.blockSignals(False)
            for spin in self.axis_spins:
                spin.setMaximum(p.dimension-1)
            self.descriptor_label.setText(f"SONDA\n{p.name}\n\nFuente: {p.source_id}\nCaptura: {p.capture_point}\nDimension: {p.dimension}\nSeleccion: {p.selection_rule}\nEspacio: {p.space_id}")
        elif p is None:
            self.descriptor_label.setText("Sin sonda")
        self._rendered_probe = p
        values = self.state.values()
        self.prepared_values = values
        reason = unavailable_reason(selected, self.state.mode, self.state.references.get(self.state.selected_probe),
                                    self.state.previous_frame(selected))
        clipped = int(np.count_nonzero(np.abs(values) > self.limit)) if values is not None else 0
        self.matrix_notice.setText(reason or (f'Fuera de escala de color: {clipped} componentes' if clipped else ''))
        self.matrix_notice.setToolTip(self.matrix_notice.text())
        self.trace_selected_button.setEnabled(sample is not None)
        if self.maximized_panel in (None, 0):
            self.matrix.set_values(values, self.page_spin.value(), self.limit)
            self.matrix.context_text = f"Captura {selected.sequence if selected else '-'} | {MODE_NAMES[self.state.mode]}"
        self.ref_action.setEnabled(sample is not None)
        self.ref_action.setToolTip('Fijar referencia completa' if sample is not None else 'Requiere un vector conservado; no basta una proyeccion')
        self.freeze_action.setEnabled(selected is not None)
        self.auto_scale.setEnabled(values is not None)
        state_name = ('Reproduccion' + (' en curso' if self.replay_playing else ' pausada')) if self.replay is not None else 'Desconectado' if self.source_closed else 'Vista pausada' if self.state.frozen else 'En vivo'
        self.freeze_action.setText('Pausar reproduccion' if self.replay is not None else 'Pausar vista')
        self.freeze_action.setChecked(not self.replay_playing if self.replay is not None else self.state.frozen is not None)
        self.live_action.setText('Ir al final de la captura' if self.replay is not None else 'Volver al presente')
        self.empty_source.setVisible(not self.state.probes)
        context = dict(selected.context) if selected else {}
        declared = ' | '.join(f'{k}: {context[k]}' for k in ('stream_id', 'token', 'token_id', 'layer', 'layer_index', 'processed_position') if k in context)
        header = 'Sin captura' if selected is None else f'{state_name} | Captura {selected.sequence} | t={selected.captured_at:.3f} s | {declared}'
        self.frame_label.setToolTip(header)
        self.frame_label.setText(self.fontMetrics().elidedText(header, QtCore.Qt.TextElideMode.ElideRight, max(200, self.width()-285)))
        if p:
            badge = ('DEMO SINTETICA | ' if p.metadata.get('synthetic', False) else '') + p.source_id
            self.source_badge.setText(self.fontMetrics().elidedText(badge, QtCore.Qt.TextElideMode.ElideRight, 280))
            self.source_badge.setToolTip(f'Fuente: {p.source_id} | Sonda: {p.name}')
        availability = {'both': 'Vector y proyeccion', 'vector': 'Solo vector',
                        'projection': 'Solo proyeccion', 'absent': 'Captura ausente'}
        self.availability_label.setText(availability[selected.availability] if selected else 'Sin capturas')
        ref = self.state.references.get(self.state.selected_probe)
        if self.state.mode == 'reference_delta':
            self.availability_label.setText(self.availability_label.text() + (f' | Ref. {ref.sequence}' if ref else ' | Sin referencia'))
            self.availability_label.setToolTip(str(dict(ref.context)) if ref else 'Falta una referencia compatible')
        latest = self.state.last_sequences.get(self.state.selected_probe)
        rss = rss_bytes()
        self.memory_label.setText(f"Datos: {self.state.plan.committed/MIB:.2f}/{self.state.plan.total/MIB:.2f} MiB reservados\n"
                                 f"Historial ocupado: {self.state.history.used_bytes/MIB:.3f} MiB\n"
                                 f"RSS visor (separado): {'no disponible' if rss is None else f'{rss/MIB:.1f} MiB'}\n"
                                 f"Ultima recibida: {latest}\nRevision: {self.state.revision}\n"
                                 f"Contadores: {dict(self.state.history.counters)}")
        self.memory_label.setToolTip(str(self.state.plan.reserves))
        ring = self.state.history.rings.get(self.state.selected_probe)
        if ring:
            self.memory_label.setText(self.memory_label.text() +
                f"\nSonda: vector {ring.raw_bytes}/{ring.recent_limit} B; proy. {ring.projected_bytes}/{ring.projected_limit} B\n"
                f"Trabajo activo: {self.state.work.used}/{self.state.work.capacity} B" +
                ("\nConfiguracion legada: cuota de historial preservada" if self.state.plan.legacy else ""))
        if sample is None:
            self.status_label.setText("Captura retenida sin vector" if selected else "Sin muestras")
            self.context_label.setText("")
            self.stats_label.setText("")
        else:
            context = dict(sample.context)
            self.context_label.setText("CONTEXTO\n" + "\n".join(f"{k}: {str(v)[:180]}" for k, v in context.items()))
            self.context_label.setToolTip(str(context))
            if values is None:
                self.stats_label.setText("Delta no disponible")
            else:
                norm, rms = magnitude(values)
                saturated = int(np.count_nonzero(np.abs(values) > self.limit))
                self.stats_label.setText(f"Norma: {norm:.6g}\nRMS: {rms:.6g}\nFuera de escala de color: {saturated}/{len(values)}")
            reference = self.state.references.get(sample.probe_id)
            first = self.state.navigation_samples(512)
            timing = f"t relativo {sample.captured_at-first[0].captured_at:.3f} s" if self.replay and first else f"Edad {max(0, time.monotonic()-sample.captured_at):.2f} s"
            self.status_label.setText(f"{timing} | Ref. {'-' if reference is None else reference.sequence}")
        if selected is not None:
            self.context_label.setText('CONTEXTO\n' + '\n'.join(f'{k}: {str(v)[:180]}' for k, v in selected.context.items()))
            self.context_label.setToolTip(str(dict(selected.context)))
        self.render_inspector()
        self.render_history()
        if self.maximized_panel in (None, 1):
            self.render_directions()

    def render_directions(self):
        p = self.state.probes.get(self.state.selected_probe)
        if p:
            selection = self.state.selection()
            frames = self.state.history.rings[p.probe_id].tail(self.pca_count.value(), raw=True,
                                                            before=selection.sequence if selection else None)
            n, d, k = len(frames), p.dimension, self.pca_axes.value()
            known = pca_known_peak(n, d, k, sum(len(f.payload)+header_cost(f.context) for f in frames))
            # Heuristic only: opaque library copies and dense SVD workspace may differ.
            external = (2*n*d + 4*min(n,d)**2)*8
            self.pca_estimate.setText(f"Sonda: {p.name}. PCA: {n} vectores compatibles x {d}; k={k}. Buffers conocidos ~{known/MIB:.2f} MiB; reserva {self.state.work.capacity/MIB:.2f} MiB. "
                                     f"Extra de biblioteca orientativo ~{external/MIB:.2f} MiB, no acotado por SONAR.")
        segments = [(sid, s) for sid, s in self.state.segments.items() if s['probe_id'] == self.state.selected_probe]
        segment_ids = [None]+[sid for sid, _ in segments]
        self.segment_combo.blockSignals(True)
        if [self.segment_combo.itemData(i) for i in range(self.segment_combo.count())] != segment_ids:
            self.segment_combo.clear()
            self.segment_combo.addItem('Sin segmento', None)
            for sid, segment in segments:
                self.segment_combo.addItem(f"{sid[:8]} | {segment['basis'].origin[:40]}", sid)
        self.segment_combo.setCurrentIndex(max(0, self.segment_combo.findData(self.state.selected_segment)))
        self.segment_combo.blockSignals(False)
        sid = self.state.selected_segment
        segment = self.state.segments.get(sid)
        basis = segment['basis'] if segment else None
        self.pca_button.setEnabled(bool(p) and self.pca_future is None)
        self.import_basis_button.setEnabled(bool(p) and self.pca_future is None)
        self.pca_start_button.setEnabled(bool(p) and self.pca_future is None)
        if self.pca_future is None:
            self.pca_button.setText('Crear nueva base PCA' if basis else 'Crear mapa PCA')
        self.basis_label.setText(("Historia proyectada pendiente de base" if self.config.retention_mode == 'combined' else 'Sin base') if basis is None else f"{len(basis.axis_names)} ejes fijos | {basis.origin}")
        self.basis_label.setToolTip("" if basis is None else basis.basis_id)
        self.basis_label.setVisible(self.maximized_panel == 1)
        kind = 'PCA fija' if basis and basis.origin.startswith('PCA') else 'Componentes' if basis and 'componentes' in basis.origin.lower() else 'Base externa' if basis else 'Sin base'
        self.panel_titles[1].setText(f'Mapa representacional | {kind}')
        self.panel_titles[1].setToolTip(basis.origin if basis else 'Crear una base PCA o cargar una base externa')
        names = basis.axis_names if basis else ()
        for i, combo in enumerate(self.map_axes):
            desired = combo.currentIndex() if combo.count() >= 2 else i
            if hasattr(self, '_restore_axes'):
                desired = self._restore_axes[i]
            if [combo.itemText(j) for j in range(combo.count())] != list(names):
                combo.blockSignals(True)
                combo.clear()
                for j, name in enumerate(names):
                    combo.addItem(name, j)
                combo.setCurrentIndex(min(max(0, desired), len(names)-1))
                combo.blockSignals(False)
            elif hasattr(self, '_restore_axes'):
                combo.blockSignals(True)
                combo.setCurrentIndex(min(max(0, desired), len(names)-1))
                combo.blockSignals(False)
            combo.setEnabled(len(names) >= 2)
        if hasattr(self, '_restore_axes'):
            del self._restore_axes
        frames = self.state.viewport_frames(self.window_spin.value())
        try:
            self.directions_view.set_processed(basis, sid, frames,
                                              self.state.selection(), tuple(s.currentIndex() for s in self.map_axes),
                                              self.state.references.get(self.state.selected_probe), self.state.mode,
                                              self.state.previous_frame(frames[0]) if frames else None)
        except ValueError as exc:
            self.directions_view.metric_label.setText(str(exc))

    def render_history(self):
        samples = self.state.viewport_frames(self.window_spin.value())
        self.set_history_controls(True)
        for i, axis in ((1, "time"), (2, "token")):
            try:
                coordinates(samples, axis)
                enabled = bool(samples)
            except ValueError:
                enabled = False
            self.axis_combo.model().item(i).setEnabled(enabled)
            if not enabled and self.axis_combo.currentIndex() == i:
                self.axis_combo.blockSignals(True)
                self.axis_combo.setCurrentIndex(0)
                self.axis_combo.blockSignals(False)
        if self.maximized_panel in (None, 2):
            segment = self.state.segments.get(self.state.selected_segment)
            self.history_view.set_data(samples, self.state.mode,
                                      self.state.references.get(self.state.selected_probe),
                                      self.component_spin.value(), list(dict.fromkeys(s.value() for s in self.trace_spins)),
                                      self.limit, self.axis_combo.currentData(), kind=self.evolution_combo.currentData(),
                                      space=self.change_space.currentData(), basis=segment['basis'] if segment else None,
                                      previous=self.state.previous_frame(samples[0]) if samples else None,
                                      selected=self.state.selection())
            self.history_notice.setText(self.history_view.notice.strip(' |'))
            self.history_notice.setToolTip(self.history_notice.text())
        self.navigation = self.state.navigation_samples(limit=None)
        self.history_slider.blockSignals(True)
        self.history_slider.setRange(0, max(0, len(self.navigation)-1))
        current = self.state.selection()
        positions = {s.sequence: i for i, s in enumerate(self.navigation)}
        self.history_slider.setValue(positions.get(current.sequence, 0) if current else 0)
        self.history_slider.blockSignals(False)
        self.navigation_label.setText(f"seq {current.sequence}" if current else "-")

    def render_inspector(self):
        sample, values = self.state.current(), getattr(self, 'prepared_values', None)
        frame = self.state.selection()
        i = self.inspected_index
        if frame is None:
            self.inspector.setText("Sin lectura")
            return
        shown = "No disponible" if values is None else f"{values[i]:.9g}"
        original = f'{sample.values[i]:.9g}' if sample and i < sample.descriptor.dimension else 'Vector no conservado'
        info = f'Sesion: {self.state.history.session_id}\nCaptura: {frame.probe_id}/{frame.sequence}\nIndice: {i}\nOriginal: {original}\nVista: {shown}'
        segment = self.state.segments.get(self.state.selected_segment)
        ref = self.state.references.get(frame.probe_id)
        if self.inspector_dock.isVisible() and segment:
            basis = segment['basis']
            info += f'\nBase: {basis.basis_id}\nProcedencia declarada: {basis.origin}\nNombres de ejes externos, no interpretaciones certificadas.'
            try:
                z = projected_values(frame, basis)
                if ref is not None and frame.descriptor.compatible(ref.descriptor) and z is not None:
                    info += f'\nDistancia proyectada a referencia: {np.linalg.norm(z-basis.project(ref.values)):.6g}'
                    if sample is not None:
                        metrics = basis.displacement(sample.values.astype(float)-ref.values)
                        info += f'\nDistancia completa: {metrics["original_norm"]:.6g}\nNorma omitida ({metrics["metric"]}): {metrics["omitted_norm"]}'
                    else:
                        info += '\nDistancia completa: no disponible'
            except ValueError as exc:
                info += f'\n{exc}'
        self.inspector.setText(info)

    def closeEvent(self, event):
        self.timer.stop()
        self.receive_timer.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.pca_dialog.close()
        if self.channel:
            if self.pending_live is not None:
                self.channel.add("received_not_drawn")
                self.pending_live = None
            self.channel.disconnected.set()
        event.accept()
