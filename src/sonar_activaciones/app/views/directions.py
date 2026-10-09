import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore
from ...processing.reference import consecutive, difference, values_for
from .timing import TimedGraphicsLayout


class DirectionsView(QtWidgets.QWidget):
    selected = QtCore.Signal(object)
    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        self.graph = TimedGraphicsLayout()
        layout.addWidget(self.graph, 1)
        self.scores = self.graph.addPlot(row=0, col=0)
        self.scores.setLabel("left", "Score")
        self.scores.getAxis("left").enableAutoSIPrefix(False)
        self.plane = self.graph.addPlot(row=0, col=1)
        self.plane.showGrid(x=True, y=True, alpha=.15)
        self.plane.setAspectLocked(True)
        self.metric_label = QtWidgets.QLabel("Sin base")
        self.metric_label.setWordWrap(True)
        layout.addWidget(self.metric_label)
        self.projected = None
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

    def set_processed(self, basis, segment_id, frames, selected, axes=(0, 1), reference=None):
        self.scores.clear()
        self.plane.clear()
        self.projected = None
        if basis is None:
            self.metric_label.setText("Pendiente de proyeccion: sin base fija")
            return
        xaxis, yaxis = (min(a, len(basis.axis_names)-1) for a in axes)
        points, spots = [], []
        previous = None
        for frame in frames:
            payload = frame.projections.get(segment_id)
            if payload is None:
                previous = None
                points.append((np.nan, np.nan))
                continue
            z = np.frombuffer(payload, '<f4')
            if previous is not None and (frame.sequence != previous.sequence+1 or frame.context.get('stream_id') != previous.context.get('stream_id')):
                points.append((np.nan, np.nan))
            points.append((z[xaxis], z[yaxis]))
            spots.append({"pos": (z[xaxis], z[yaxis]), "data": frame.sequence,
                          "symbol": "o" if frame.payload is not None else "t", "brush": '#267d86'})
            previous = frame
        if points:
            xy = np.asarray(points)
            self.plane.plot(xy[:, 0], xy[:, 1], connect='finite', pen=pg.mkPen('#669d95', width=1))
        scatter = pg.ScatterPlotItem(spots, size=6, pen=None)
        scatter.sigClicked.connect(lambda item, pts: self.selected.emit(int(pts[0].data())))
        self.plane.addItem(scatter)
        self.plane.setLabel('bottom', basis.axis_names[xaxis])
        self.plane.setLabel('left', basis.axis_names[yaxis])
        payload = selected.projections.get(segment_id) if selected else None
        if payload is None:
            self.metric_label.setText("Captura seleccionada sin coordenadas en este segmento")
            return
        scores = np.frombuffer(payload, '<f4')
        self.projected = scores
        self.scores.addItem(pg.BarGraphItem(x=np.arange(len(scores)), height=scores, width=.65,
                                            brushes=['#287d9b' if z >= 0 else '#b64759' for z in scores]))
        self.scores.getAxis('bottom').setTicks([list(enumerate(basis.axis_names))])
        self.plane.plot([scores[xaxis]], [scores[yaxis]], pen=None, symbol='o', symbolSize=11, symbolBrush='#b64759')
        metric = "Coordenadas del vector original" + (" | derivado" if segment_id in selected.derived else "")
        if reference is not None:
            projected_distance = np.linalg.norm(scores-basis.project(reference.values))
            metric += f" | Dist. proyectada a ref.: {projected_distance:.4g}"
            if selected.payload is not None:
                full = np.linalg.norm(selected.observation().values.astype(float)-reference.values)
                metric += f" | Dist. completa: {full:.4g}"
            else:
                metric += " | Dist. completa no disponible"
        self.metric_label.setText(metric)

    def set_data(self, basis, samples, mode, reference, start_sequence):
        self.scores.clear()
        self.plane.clear()
        self.projected = None
        if basis is None or not samples:
            self.metric_label.setText("Sin base" if basis is None else "Sin lecturas")
            return
        current = samples[-1]
        previous = samples[-2] if len(samples) > 1 else None
        values = values_for(current, mode, reference, previous)
        if values is None:
            self.metric_label.setText("Delta no disponible")
            return
        transform = basis.project if mode == "raw" else basis.project_delta
        scores = transform(values)
        self.projected = scores
        self.scores.addItem(pg.BarGraphItem(x=np.arange(len(scores)), height=scores, width=.65,
                                           brushes=["#287d9b" if s >= 0 else "#b64759" for s in scores]))
        self.scores.getAxis("bottom").setTicks([list(enumerate(basis.axis_names))])
        for i, value in enumerate(scores):
            text = pg.TextItem(f"{value:.4g}", color="#26343c", anchor=(.5, 1 if value >= 0 else 0))
            text.setPos(i, value)
            self.scores.addItem(text)
        low, high = min(0, float(np.min(scores))), max(0, float(np.max(scores)))
        margin = max(.05, (high-low)*.22)
        self.scores.setYRange(low-margin, high+margin, padding=0)
        points = []
        for i, sample in enumerate(samples):
            if sample.sequence < start_sequence:
                continue
            prior = samples[i-1] if i else None
            if prior is not None and not consecutive(prior, sample):
                points.append([np.nan, np.nan])
            v = values_for(sample, mode, reference, prior)
            if v is None:
                points.append([np.nan, np.nan])
                continue
            z = transform(v)
            points.append([z[0], z[1] if len(z) > 1 else 0])
        if points:
            points = np.array(points)
            self.plane.plot(points[:, 0], points[:, 1], connect="finite", pen=pg.mkPen("#61968e", width=1.5),
                            symbol="o", symbolSize=3, symbolBrush="#61968e")
        self.plane.plot([scores[0]], [scores[1] if len(scores)>1 else 0], pen=None, symbol="o",
                        symbolSize=10, symbolBrush="#b64759")
        self.plane.setLabel("bottom", basis.axis_names[0])
        self.plane.setLabel("left", basis.axis_names[1] if len(scores)>1 else "Sin segundo eje")
        anchor = reference if reference is not None else previous if consecutive(previous, current) else None
        if anchor is None:
            self.metric_label.setText("Desplazamiento: sin referencia ni predecesora consecutiva")
            return
        metrics = basis.displacement(difference(current, anchor))
        omitted = "no disponible (direcciones no ortonormales)" if metrics["omitted_norm"] is None else f"{metrics['omitted_norm']:.6g}"
        self.metric_label.setText(f"Ancla seq {anchor.sequence} | Norma completa original: {metrics['original_norm']:.6g}\n"
                            f"Norma omitida [{metrics['metric']}]: {omitted}"
                            + (f" | Norma transformada: {metrics['transformed_norm']:.6g}" if metrics["metric"] != "original" else ""))
