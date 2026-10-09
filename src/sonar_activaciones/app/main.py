"""Entrypoints. Keep top-level imports free of Qt for spawn and SDK isolation."""


def _application():
    import os
    import pyqtgraph as pg
    from PySide6 import QtWidgets, QtGui
    pg.setConfigOptions(background="w", foreground="#243139", antialias=False, imageAxisOrder="row-major")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    if not QtGui.QFontDatabase.families() and os.name == "nt":
        # Qt's offscreen backend does not enumerate Windows system fonts.
        path = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "segoeui.ttf")
        if QtGui.QFontDatabase.addApplicationFont(path) >= 0:
            app.setFont(QtGui.QFont("Segoe UI", 10))
    app.setStyle("Fusion")
    return app


def run_monitor(probes, config, channel):
    from .window import MonitorWindow
    app = _application()
    window = MonitorWindow(probes, config, channel)
    window.show()
    channel.ready.set()
    app.exec()


def run_standalone(config, command=None, path=None):
    if command == "demo":
        return run_demo(config)
    from .window import MonitorWindow
    app = _application()
    window = MonitorWindow([], config)
    if command == "replay":
        window.open_capture(path)
    window.show()
    return app.exec()


def run_demo(config):
    import time
    import numpy as np
    from .. import ProbeDescriptor, open_monitor
    probe = ProbeDescriptor("demo", "Vector sintetico", "demo", "CPU", 70,
                            "vector completo", "synthetic/demo-v1", metadata={"synthetic": True})
    try:
        with open_monitor([probe], config) as monitor:
            step = 0
            while monitor.status()["state"] == "connected":
                if monitor.capture_allowed("demo"):
                    axis = np.arange(probe.dimension)
                    values = .7 * np.sin(axis*.18 + step*.04) + .35*np.cos(axis*.53-step*.07)
                    monitor.publish("demo", values, {"stream_id": f"demo-{step//600}",
                                    "processed_position": step, "stage": "synthetic"})
                step += 1
                time.sleep(1/30)
    except KeyboardInterrupt:
        pass
    return 0
