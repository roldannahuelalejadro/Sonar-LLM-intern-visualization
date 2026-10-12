import gc
import os
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture(scope='session')
def qt_application():
    from sonar_activaciones.app.main import _application
    app = _application()
    yield app
    gc.collect()


@pytest.fixture
def app(qt_application):
    from PySide6 import QtCore, QtWidgets
    from sonar_activaciones.app.window import MonitorWindow
    yield qt_application
    # Destroy native objects while QApplication is still alive, not at Python exit.
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if isinstance(widget, MonitorWindow):
            widget.close()
            widget.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    qt_application.processEvents()
    gc.collect()
