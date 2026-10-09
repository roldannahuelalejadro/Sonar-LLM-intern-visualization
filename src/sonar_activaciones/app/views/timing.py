import time
import pyqtgraph as pg
from PySide6 import QtCore


class TimedGraphicsLayout(pg.GraphicsLayoutWidget):
    painted = QtCore.Signal(object, object)

    def __init__(self):
        super().__init__()
        self.paint_key = None

    def paintEvent(self, event):
        start = time.perf_counter_ns()
        super().paintEvent(event)
        self.painted.emit(self.paint_key, time.perf_counter_ns()-start)
