import math
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore
from .timing import TimedGraphicsLayout

COLORS = [(22, 98, 147), (66, 157, 179), (246, 248, 249), (221, 128, 96), (164, 38, 58)]
CMAP = pg.ColorMap(np.linspace(0, 1, len(COLORS)), COLORS)


class MatrixView(TimedGraphicsLayout):
    inspected = QtCore.Signal(int)
    PAGE_SIZE = 256
    COLUMNS = 16

    def __init__(self):
        super().__init__()
        self.plot = self.addPlot()
        self.plot.setAspectLocked(True)
        self.plot.invertY(True)
        self.plot.setLabel("bottom", "Columna")
        self.plot.setLabel("left", "Fila")
        self.plot.getViewBox().setBackgroundColor("#dce2e5")
        self.image = pg.ImageItem(axisOrder="row-major")
        self.image.setLookupTable(CMAP.getLookupTable(nPts=256))
        self.plot.addItem(self.image)
        self.colorbar = pg.ColorBarItem(values=(-1, 1), colorMap=CMAP, interactive=False, label="Activacion")
        self.colorbar.setImageItem(self.image, insert_in=self.plot)
        self.offset = 0
        self.count = 0
        self.displayed = None
        self.context_text = ''
        self._layout_key = None
        self._limit = None
        self.scene().sigMouseClicked.connect(self._clicked)
        self.scene().sigMouseMoved.connect(self._hovered)

    def set_values(self, values, page, limit):
        self.offset = page * self.PAGE_SIZE
        self.count = 0 if values is None else min(self.PAGE_SIZE, max(0, len(values)-self.offset))
        rows = max(1, math.ceil(self.count / self.COLUMNS))
        matrix = np.full((rows, self.COLUMNS), np.nan, dtype=float)
        if self.count:
            matrix.ravel()[:self.count] = values[self.offset:self.offset+self.count]
        self.displayed = matrix
        self.image.setImage(matrix, autoLevels=False, levels=(-limit, limit))
        if self._limit != limit:
            self.colorbar.setLevels((-limit, limit))
            self._limit = limit
        if self._layout_key != (page, rows):
            self.plot.getAxis("bottom").setTicks([[(i+.5, str(i)) for i in (0, 4, 8, 12, 15)]])
            self.plot.getAxis("left").setTicks([[(i+.5, str(i)) for i in range(rows)]])
            self.plot.setRange(xRange=(0, self.COLUMNS), yRange=(0, rows), padding=.02)
            self._layout_key = (page, rows)

    def index_at(self, x, y):
        col, row = math.floor(x), math.floor(y)
        local = row * self.COLUMNS + col
        if 0 <= col < self.COLUMNS and row >= 0 and local < self.count:
            return self.offset + local
        return None

    def _clicked(self, event):
        if self.plot.sceneBoundingRect().contains(event.scenePos()):
            point = self.image.mapFromScene(event.scenePos())
            index = self.index_at(point.x(), point.y())
            if index is not None:
                self.inspected.emit(index)

    def _hovered(self, position):
        point = self.image.mapFromScene(position)
        index = self.index_at(point.x(), point.y())
        if index is None:
            self.setToolTip('Sin componente medida (padding o vector ausente)')
        else:
            value = self.displayed.ravel()[index-self.offset]
            self.setToolTip(f'Componente {index}: {value:.7g}\n{self.context_text}')
