import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore
from ...processing.reference import consecutive
from ...processing.display import projected_series, MODE_NAMES
from .timing import TimedGraphicsLayout, stable_range, NoticeLabel


class DirectionsView(QtWidgets.QWidget):
    selected = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.graph = TimedGraphicsLayout()
        self.graph.ci.layout.setContentsMargins(2, 2, 2, 2)
        self.graph.ci.layout.setSpacing(2)
        layout.addWidget(self.graph, 1)
        self.scores = self.graph.addPlot(row=0, col=0)
        self.scores.setLabel('left', 'Coordenada')
        self.plane = self.graph.addPlot(row=0, col=1)
        self.plane.showGrid(x=True, y=True, alpha=.15)
        self.plane.getAxis('left').setWidth(70)
        self.plane.getAxis('bottom').setHeight(44)
        self.plane.getAxis('left').enableAutoSIPrefix(False)
        self.plane.getAxis('bottom').enableAutoSIPrefix(False)
        self.path = self.plane.plot(connect='finite', pen=pg.mkPen('#77a09c', width=1))
        self.scatter = pg.ScatterPlotItem(size=6, pen=None)
        self.scatter.sigClicked.connect(lambda item, pts: self.selected.emit(int(pts[0].data())))
        self.plane.addItem(self.scatter)
        self.marker = pg.ScatterPlotItem(size=11, pen=None, brush='#b64759')
        self.plane.addItem(self.marker)
        self.bars = pg.BarGraphItem(x=np.array([]), height=np.array([]), width=.65)
        self.scores.addItem(self.bars)
        self._labels = None
        self.metric_label = NoticeLabel()
        self.metric_label.setText('Sin base')
        self.setMinimumHeight(140)
        layout.addWidget(self.metric_label)
        self.projected = None
        self.metric_label.show()
        self.compact = False

    def set_compact(self, compact):
        if self.compact == compact:
            return
        self.graph.ci.removeItem(self.plane)
        if compact:
            self.graph.ci.removeItem(self.scores)
            self.graph.ci.addItem(self.plane, row=0, col=0)
        else:
            self.graph.ci.addItem(self.scores, row=0, col=0)
            self.graph.ci.addItem(self.plane, row=0, col=1)
        self.compact = compact

    def set_processed(self, basis, segment_id, frames, selected, axes=(0, 1), reference=None,
                      mode='raw', previous=None):
        self.projected = None
        if basis is None:
            self._clear()
            self.graph.hide()
            self.metric_label.setText('Todavia no hay un mapa. Crear una base PCA o cargar una base externa.')
            return
        self.graph.show()
        if len(basis.axis_names) < 2:
            self._clear()
            self.graph.hide()
            self.metric_label.setText('Base de un eje: seleccionar o crear una base con al menos dos ejes para el plano.')
            return
        xaxis, yaxis = axes
        if xaxis == yaxis or not all(0 <= a < len(basis.axis_names) for a in axes):
            self._clear()
            self.metric_label.setText('Seleccionar dos ejes distintos y validos.')
            return
        values = projected_series(frames, basis, mode, reference, previous)
        points, spots = [], []
        prior = previous
        for f, z in zip(frames, values):
            if prior is not None and not consecutive(prior, f):
                points.append((np.nan, np.nan))
            points.append((z[xaxis], z[yaxis]))
            if np.isfinite(z).all():
                spots.append({'pos': (z[xaxis], z[yaxis]), 'data': f.sequence,
                              'symbol': 't' if f.payload is None else 'o', 'brush': '#267d86'})
            prior = f
        if points and mode != 'previous_delta':
            xy = np.asarray(points)
            self.path.setData(xy[:, 0], xy[:, 1])
        else:
            self.path.setData([], [])
        self.scatter.setData(spots)
        self.marker.setData([])
        prefix = '' if mode == 'raw' else 'Delta '
        title = 'Posiciones' if mode == 'raw' else 'Desplazamiento a referencia' if mode == 'reference_delta' else 'Desplazamiento por captura'
        labels = (basis.basis_id, axes, mode)
        if self._labels != labels:
            self.plane.setLabel('bottom', prefix+basis.axis_names[xaxis])
            self.plane.setLabel('left', prefix+basis.axis_names[yaxis])
            self.plane.setTitle(title, size='10pt')
            self.scores.getAxis('bottom').setTicks([list(enumerate(basis.axis_names))])
            self._labels = labels
        valid = values[np.isfinite(values).all(axis=1)]
        constant = len(valid) > 0 and np.all(np.ptp(valid[:, [xaxis, yaxis]], axis=0) == 0)
        if len(valid):
            for axis, col in (('x', xaxis), ('y', yaxis)):
                stable_range(self.plane, axis, valid[:, col], labels)
        index = next((i for i, f in enumerate(frames) if selected and f.sequence == selected.sequence), None)
        if index is None or not np.isfinite(values[index]).all():
            self.bars.setOpts(x=np.array([]), height=np.array([]), brushes=[])
            self.metric_label.setText('Seleccion sin coordenadas calculables en este modo/base; revisar referencia o captura consecutiva.')
            return
        scores = values[index]
        self.projected = scores
        if not self.compact:
            self.bars.setOpts(x=np.arange(len(scores)), height=scores,
                              brushes=['#287d9b' if z >= 0 else '#b64759' for z in scores])
        self.marker.setData(x=[scores[xaxis]], y=[scores[yaxis]])
        metric = MODE_NAMES[mode]
        if segment_id not in selected.projections:
            metric += ' | Proyeccion al vuelo del vector conservado'
        if constant:
            metric += ' | Proyeccion constante en esta ventana; no implica ausencia de cambios fuera del plano'
        self.metric_label.setText(metric if metric != MODE_NAMES[mode] else '')
        self.metric_label.setToolTip(metric)

    def _clear(self):
        self.path.setData([], [])
        self.scatter.setData([])
        self.marker.setData([])
        self.bars.setOpts(x=np.array([]), height=np.array([]), brushes=[])
