import time
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets
import numpy as np


class NoticeLabel(QtWidgets.QLabel):
    """Single stable row; keep the complete message available on hover."""
    def __init__(self):
        super().__init__()
        self.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.setFixedHeight(self.fontMetrics().height()+6)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setPen(self.palette().color(QtGui.QPalette.ColorRole.WindowText))
        text = self.fontMetrics().elidedText(self.text(), QtCore.Qt.TextElideMode.ElideRight, self.contentsRect().width())
        painter.drawText(self.contentsRect(), QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter, text)


def stable_range(plot, axis, values, key):
    """Keep numeric framing until context changes or data leaves the bounds."""
    finite = np.asarray(values)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return
    lo, hi = float(finite.min()), float(finite.max())
    margin = max((hi-lo)*.12, abs(lo)*.01, 1e-6)
    bounds = getattr(plot, '_stable_bounds', {})
    previous = bounds.get(axis)
    if previous and previous[0] == key:
        old_lo, old_hi = previous[1:]
        if old_lo <= lo and hi <= old_hi:
            return
        lo, hi = min(old_lo, lo-margin), max(old_hi, hi+margin)
    else:
        lo, hi = lo-margin, hi+margin
    bounds[axis] = (key, lo, hi)
    plot._stable_bounds = bounds
    if axis == 'x':
        plot.setXRange(lo, hi, padding=0)
    else:
        plot.setYRange(lo, hi, padding=0)


class TimedGraphicsLayout(pg.GraphicsLayoutWidget):
    painted = QtCore.Signal(object, object)

    def __init__(self):
        super().__init__()
        self.paint_key = None

    def paintEvent(self, event):
        start = time.perf_counter_ns()
        super().paintEvent(event)
        self.painted.emit(self.paint_key, time.perf_counter_ns()-start)
