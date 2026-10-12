import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore
from ...processing.temporal import coordinates, broken_trace, mesh_columns
from ...processing.display import change_series, component_series, MODE_NAMES
from .matrix import CMAP
from .timing import TimedGraphicsLayout, stable_range


class HistoryView(TimedGraphicsLayout):
    selected = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self.ci.layout.setContentsMargins(2, 2, 2, 2)
        self.ci.layout.setSpacing(2)
        self.availability = self.addPlot(row=0, col=0)
        self.availability.setMaximumHeight(42)
        self.availability.hideAxis('bottom')
        self.availability.getAxis('left').setTicks([[(0, 'Proy.'), (1, 'Vector'), (2, 'Ambos')]])
        self.availability.setYRange(-.5, 2.5, padding=0)
        self.trace = self.addPlot(row=1, col=0)
        self.trace.getAxis('left').enableAutoSIPrefix(False)
        self.trace.showGrid(x=True, y=True, alpha=.15)
        self.trace.addLegend()
        self.availability.getAxis('left').setWidth(64)
        self.trace.getAxis('left').setWidth(64)
        self.trace.getAxis('bottom').setHeight(44)
        self.availability_points = pg.ScatterPlotItem(size=6, pen=None)
        self.availability.addItem(self.availability_points)
        self.availability_points.sigClicked.connect(self._selected)
        self.curves = [self.trace.plot(pen=pg.mkPen(color, width=1.5), connect='finite')
                       for color in ('#197b87', '#bb4c60', '#5a7541')]
        self.points = [pg.ScatterPlotItem(size=4, pen=None, brush='#197b87') for _ in range(3)]
        for points in self.points:
            self.trace.addItem(points)
            points.sigClicked.connect(self._selected)
        self.selection_line = pg.InfiniteLine(angle=90, pen=pg.mkPen('#b64759', width=1))
        self.trace.addItem(self.selection_line)
        self.selection_line.hide()
        self.selection_plot = self.trace
        self._labels = None
        self._names = None
        self.heat = pg.PlotItem()
        self.heat.setLabel('left', 'Indice')
        self.heat.getAxis('left').setWidth(64)
        self.heat.getAxis('bottom').setHeight(44)
        self.heat.getViewBox().setBackgroundColor('#dce2e5')
        self.mesh = pg.PColorMeshItem(colorMap=CMAP, levels=(-1, 1), enableAutoLevels=False)
        self.heat.addItem(self.mesh)
        self.kind = 'change'
        self.compact = False
        self.lines = []
        self.displayed = None
        self.displayed_x = np.array([])
        self.notice = ''

    def set_compact(self, compact):
        self.compact = compact

    def _selected(self, item, points):
        self.selected.emit(int(points[0].data()))

    def _kind(self, kind):
        if (kind == 'heat') != (self.kind == 'heat'):
            self.selection_plot.removeItem(self.selection_line)
            self.ci.removeItem(self.heat if self.kind == 'heat' else self.trace)
            self.ci.addItem(self.heat if kind == 'heat' else self.trace, row=1, col=0)
            self.selection_plot = self.heat if kind == 'heat' else self.trace
            self.selection_plot.addItem(self.selection_line)
        self.kind = kind

    def set_frames(self, frames, current, x=None):
        levels = {'projection': 0, 'vector': 1, 'both': 2}
        if x is None:
            x = coordinates(frames)
        spots = [{'pos': (pos, levels[f.availability]), 'data': f.sequence,
                  'symbol': 't' if f.availability == 'projection' else 'o',
                  'brush': '#b64759' if current and f.sequence == current.sequence else '#267d86'}
                 for f, pos in zip(frames, x)]
        self.availability_points.setData(spots)

    def set_data(self, frames, mode, reference, start_component, trace_indices, limit, axis,
                 *, kind='change', space='full', basis=None, previous=None, selected=None):
        self._kind(kind)
        self.selection_line.hide()
        self.notice = ''
        self.mesh.setVisible(kind == 'heat')
        x = coordinates(frames, axis)
        self.displayed_x = x
        self.set_frames(frames, selected, x)
        if not frames:
            for curve, points in zip(self.curves, self.points):
                curve.setData([], [])
                points.setData([])
            self.mesh.hide()
            self.displayed = np.array([])
            self.notice = 'Sin capturas retenidas'
            return
        axis_name = {'sequence': 'Secuencia', 'time': 'Tiempo relativo (s)', 'token': 'Posicion procesada'}[axis]
        plot = self.heat if kind == 'heat' else self.trace
        labels = (kind, mode, space, axis, tuple(trace_indices))
        if labels != self._labels:
            plot.setLabel('bottom', axis_name)
        pad = max(.5 if axis != 'time' else .01, float(x[-1]-x[0])*.015)
        for graph in (self.availability, plot):
            graph.setXRange(x[0]-pad, x[-1]+pad, padding=0)
        if kind == 'heat':
            # Bound mesh work while preserving every temporal coordinate.
            count = min(64, max(1, 4096//len(frames)), frames[-1].descriptor.dimension-start_component)
            indices = np.arange(start_component, start_component+count)
            values = component_series(frames, indices, mode, reference, previous)
            edges, columns = mesh_columns(frames, x, values, axis)
            xx, yy = np.meshgrid(edges, np.arange(start_component, start_component+count+1)-.5)
            self.mesh.setLevels((-limit, limit), update=False)
            self.mesh.setData(xx, yy, columns.T, autoLevels=False)
            self.mesh.setVisible(True)
            self.heat.setYRange(start_component-.5, start_component+count-.5, padding=0)
            if labels != self._labels:
                self.heat.setTitle(MODE_NAMES[mode], size='10pt')
            self.displayed = values
            self.notice = f'Componentes {start_component}..{start_component+count-1}; {len(frames)} capturas'
            if count < min(64, frames[-1].descriptor.dimension-start_component):
                self.notice += ' | Rango de componentes reducido para dibujo; intervalo temporal completo'
        else:
            if kind == 'change':
                values = change_series(frames, space, basis, previous)[:, None]
                names = ['Norma L2 completa' if space == 'full' else 'Norma L2 proyectada']
                if labels != self._labels:
                    self.trace.setLabel('left', 'L2')
                    self.trace.setTitle(names[0] + ' | siempre consecutivo', size='10pt')
                self.notice = 'Norma no normalizada; sin dividir por tiempo'
                if space == 'projected' and basis is None:
                    self.notice = 'Cambio proyectado no disponible: crear o cargar una base'
            else:
                values = component_series(frames, trace_indices, mode, reference, previous)
                names = [f'c{i}' for i in trace_indices]
                if labels != self._labels:
                    self.trace.setLabel('left', 'Valor')
                    self.trace.setTitle(MODE_NAMES[mode], size='10pt')
            self.displayed = values
            if tuple(names) != self._names:
                self.trace.legend.clear()
                for curve, name in zip(self.curves, names):
                    self.trace.legend.addItem(curve, name)
                self._names = tuple(names)
            self.lines = self.curves[:len(names)]
            for j, (curve, points) in enumerate(zip(self.curves, self.points)):
                curve.setVisible(j < len(names))
                points.setVisible(j < len(names))
            for j, name in enumerate(names):
                tx, ty = broken_trace(frames, x, values[:, j])
                self.curves[j].setData(tx, ty)
                valid = np.isfinite(values[:, j])
                spots = [{'pos': (pos, value), 'data': f.sequence} for f, pos, value, ok
                         in zip(frames, x, values[:, j], valid) if ok]
                self.points[j].setData(spots)
            stable_range(self.trace, 'y', values, (labels, frames[-1].descriptor.space_id,
                                                 basis.basis_id if basis else None))
        self._labels = labels
        missing = np.count_nonzero(~np.isfinite(self.displayed).all(axis=1))
        if missing:
            self.notice = f'{missing} capturas sin valores calculables (huecos, vector o base ausente) | ' + self.notice
        if selected:
            position = next((pos for pos, f in zip(x, frames) if f.sequence == selected.sequence), None)
            if position is not None:
                self.selection_line.setValue(position)
                self.selection_line.show()
