import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore
from ...processing.reference import consecutive
from ...processing.temporal import coordinates, selected_history, broken_trace, mesh_columns
from .matrix import CMAP
from .timing import TimedGraphicsLayout


class HistoryView(TimedGraphicsLayout):
    selected = QtCore.Signal(object)
    def __init__(self):
        super().__init__()
        self.heat = self.addPlot(row=0, col=0)
        self.heat.setLabel("left", "Componente")
        self.heat.getViewBox().setBackgroundColor("#dce2e5")
        self.mesh = pg.PColorMeshItem(colorMap=CMAP, levels=(-1, 1), enableAutoLevels=False)
        self.heat.addItem(self.mesh)
        self.trace = self.addPlot(row=1, col=0)
        self.trace.setLabel("left", "Valor")
        self.trace.showGrid(x=True, y=True, alpha=.15)
        self.trace.addLegend()
        self.lines = []
        self.markers = []
        self.availability = self.addPlot(row=2, col=0)
        self.availability.setMaximumHeight(65)
        self.availability.setLabel('bottom', 'Capturas retenidas (secuencia)')
        self.availability.getAxis('left').setTicks([[(0, 'Proy.'), (1, 'Vector'), (2, 'Ambos')]])
        self.compact = False

    def set_compact(self, compact):
        if compact == self.compact:
            return
        self.ci.removeItem(self.availability)
        if compact:
            self.ci.removeItem(self.trace)
            self.ci.removeItem(self.heat)
            self.availability.setMaximumHeight(16777215)
            self.ci.addItem(self.availability, row=0, col=0)
        else:
            self.ci.addItem(self.heat, row=0, col=0)
            self.ci.addItem(self.trace, row=1, col=0)
            self.availability.setMaximumHeight(85)
            self.ci.addItem(self.availability, row=2, col=0)
        self.compact = compact

    def set_frames(self, frames, current):
        self.availability.clear()
        levels = {'projection': 0, 'vector': 1, 'both': 2}
        spots = [{'pos': (f.sequence, levels[f.availability]), 'data': f.sequence,
                  'symbol': 't' if f.availability == 'projection' else 'o',
                  'brush': '#b64759' if current and f.sequence == current.sequence else '#267d86'} for f in frames]
        scatter = pg.ScatterPlotItem(spots, size=7, pen=None)
        scatter.sigClicked.connect(lambda item, pts: self.selected.emit(int(pts[0].data())))
        self.availability.addItem(scatter)
        self.availability.setYRange(-.5, 2.5, padding=0)

    def set_data(self, samples, mode, reference, start_component, trace_indices, limit, axis):
        if self.compact:
            return
        self.trace.clear()
        self.trace.legend.clear()
        for marker in self.markers:
            self.heat.removeItem(marker)
        self.markers = []
        self.lines = []
        if not samples:
            self.mesh.setVisible(False)
            return
        dimension = samples[-1].descriptor.dimension
        indices = np.arange(start_component, min(dimension, start_component+64))
        x = coordinates(samples, axis)
        selected = selected_history(samples, indices, mode, reference)
        edges, columns = mesh_columns(samples, x, selected, axis)
        xx, yy = np.meshgrid(edges, np.arange(indices[0], indices[-1]+2)-.5)
        self.mesh.setVisible(True)
        self.mesh.setLevels((-limit, limit), update=False)
        self.mesh.setData(xx, yy, columns.T, autoLevels=False)
        self.heat.setRange(xRange=(edges[0], edges[-1]), yRange=(indices[0]-.5, indices[-1]+.5), padding=.01)
        values = selected_history(samples, trace_indices, mode, reference)
        colors = ["#166a94", "#b74457", "#31815d", "#996915"]
        for j, component in enumerate([] if self.compact else trace_indices):
            tx, ty = broken_trace(samples, x, values[:, j])
            line = self.trace.plot(tx, ty, connect="finite", pen=pg.mkPen(colors[j], width=1.5),
                                   symbol="o", symbolSize=3, symbolBrush=colors[j], name=f"c{component}")
            self.lines.append(line)
        for i in range(1, len(samples)):
            if not consecutive(samples[i-1], samples[i]):
                position = (x[i-1]+x[i])/2
                stream_change = samples[i-1].context.get("stream_id") != samples[i].context.get("stream_id")
                name = "stream" if stream_change else "hueco"
                marker = pg.InfiniteLine(position, pen=pg.mkPen("#93621b", style=pg.QtCore.Qt.PenStyle.DashLine),
                                         label=name, labelOpts={"position": .85})
                self.heat.addItem(marker)
                self.markers.append(marker)
        title = {"sequence": "Secuencia", "time": "Tiempo relativo (s)", "token": "Posicion procesada"}[axis]
        self.heat.setLabel("bottom", title)
        self.trace.setLabel("bottom", title)
