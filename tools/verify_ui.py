"""Render synthetic fixtures and inspect pixels; never a model experiment."""
import argparse
import json
import os
from pathlib import Path
import time

parser = argparse.ArgumentParser()
parser.add_argument("--native", action="store_true")
args = parser.parse_args()
if not args.native:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
from PySide6 import QtTest, QtGui
from sonar_activaciones import MonitorConfig, Observation, ProbeDescriptor
from sonar_activaciones.app.main import _application
from sonar_activaciones.app.window import MonitorWindow
from sonar_activaciones.storage.mixed import save_state


def main():
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    app = _application()
    probe = ProbeDescriptor("qa", "Vector sintetico / 70 componentes", "demo QA", "CPU",
                            70, "vector completo", "synthetic/qa-v1", metadata={"synthetic": True})
    window = MonitorWindow([probe], MonitorConfig())
    window.timer.stop()
    window.receive_timer.stop()
    window.show()
    base_time = time.monotonic() - 6
    for i in range(120):
        if i in (35, 36, 37):
            continue
        values = .8*np.sin(np.arange(70)*.17+i*.045)+.4*np.cos(np.arange(70)*.43-i*.1)
        window.ingest(Observation.create(probe, values, i,
                      {"stream_id": "A" if i < 80 else "B", "processed_position": i, "stage": "synthetic"}, base_time+i*.05))
        if i == 0:
            window.set_reference()
            window.apply_components()
    reports = []
    for width, height in ((1220, 800), (900, 650)):
        window.resize(width, height)
        for panel, name in ((None, "unified"), (0, "matrix"), (1, "directions"), (2, "history")):
            if window.maximized_panel is not None:
                window.maximize_panel(window.maximized_panel)
            if panel is not None:
                window.maximize_panel(panel)
            window.render()
            QtTest.QTest.qWait(100)
            visible = (window.matrix, window.directions_view.graph, window.history_view)
            for index, graph in enumerate(visible):
                assert graph.isVisible() == (panel is None or panel == index)
            image = window.grab().toImage().convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
            pixels = np.frombuffer(image.bits(), dtype=np.uint8).reshape(image.height(), image.width(), 4)
            unique = len(np.unique(pixels[::3, ::3, :3].reshape(-1, 3), axis=0))
            assert unique > 40, "Blank or unpainted UI"
            path = output / f"v02-{name}-{width}.png"
            image.save(str(path))
            render_ms, paint_ms = [], []
            def painted(key, ns):
                paint_ms.append(ns/1e6)
            for graph in (window.matrix, window.history_view, window.directions_view.graph):
                graph.painted.connect(painted)
            for _ in range(25):
                start = time.perf_counter_ns()
                window.render()
                render_ms.append((time.perf_counter_ns()-start)/1e6)
                QtTest.QTest.qWait(20)
            for graph in (window.matrix, window.history_view, window.directions_view.graph):
                graph.painted.disconnect(painted)
            assert paint_ms, "Visible views did not paint"
            reports.append({"file": str(path), "width": image.width(), "height": image.height(), "sampled_colors": unique,
                            "render_ms_median": float(np.median(render_ms)), "render_ms_p95": float(np.percentile(render_ms, 95)),
                            "paint_event_ms_median": float(np.median(paint_ms)), "paint_event_ms_p95": float(np.percentile(paint_ms, 95))})
    window.toggle_freeze(True)
    saved = save_state(output / "synthetic-capture-v02.json", window.state)
    window.close()
    replay = MonitorWindow([], MonitorConfig())
    assert replay.open_capture(saved)
    replay.show()
    QtTest.QTest.qWait(100)
    replay.grab().save(str(output/"v02-replay.png"))
    replay.close()
    (output/"ui-verification-v02.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
