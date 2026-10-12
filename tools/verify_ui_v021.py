"""Deterministic native Qt interaction, screenshots and numeric/pixel checks."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import time

parser = argparse.ArgumentParser()
parser.add_argument('--native', action='store_true')
parser.add_argument('--output-dir', default='artifacts/v021')
parser.add_argument('--theme', choices=['laboratorio', 'grafito'], default='laboratorio')
args = parser.parse_args()
if not args.native:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import numpy as np
from PySide6 import QtCore, QtGui, QtTest
from sonar_activaciones import MonitorConfig, Observation, ProbeDescriptor
from sonar_activaciones.app.main import _application
from sonar_activaciones.app.window import MonitorWindow
from sonar_activaciones.app.themes import apply_window
from sonar_activaciones.storage.mixed import save_state
from evidence import identity


def main():
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    app = _application()
    reports = []
    errors = []
    p = ProbeDescriptor('qa', 'Vector sintetico', 'Verificacion local', 'CPU', 70,
                        'vector completo', 'synthetic/qa-v021', metadata={'synthetic': True})

    def capture(w, name, width, height, map_expected=False):
        w.resize(width, height)
        w.render()
        QtTest.QTest.qWait(120)
        assert w.width() == width and w.height() == height, 'Layout excede el viewport solicitado'
        assert not errors, errors
        if map_expected:
            assert w.directions_view.projected is not None
            rect = w.directions_view.plane.getViewBox().sceneBoundingRect()
            assert rect.height() >= 35 and rect.width() >= 100, (name, rect)
        if name != 'projection-only':
            assert np.isfinite(w.history_view.displayed).any(), name
            rect = w.history_view.trace.getViewBox().sceneBoundingRect()
            assert rect.height() >= 28 and rect.width() >= 100, (name, rect)
        image = w.grab().toImage().convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
        pixels = np.frombuffer(image.bits(), dtype=np.uint8).reshape(image.height(), image.width(), 4)
        colors = len(np.unique(pixels[::3, ::3, :3].reshape(-1, 3), axis=0))
        assert colors > 40
        filename = f'{name}-{width}.png'
        image.save(str(output/filename))
        timings = []
        for _ in range(15):
            start = time.perf_counter_ns()
            w.render()
            timings.append((time.perf_counter_ns()-start)/1e6)
            QtTest.QTest.qWait(10)
        reports.append({'file': filename, 'width': width, 'height': height, 'sampled_colors': colors,
                        'render_ms_median': float(np.median(timings)),
                        'render_ms_p95': float(np.percentile(timings, 95)),
                        'mode': w.state.mode, 'selection': w.state.selection().sequence,
                        'history_first': float(w.history_view.displayed_x[0]),
                        'history_last': float(w.history_view.displayed_x[-1])})

    for width, height in ((1220, 800), (900, 650)):
        w = MonitorWindow([p], MonitorConfig())
        apply_window(w, args.theme, persist=False)
        w.show_error = errors.append
        w.timer.stop()
        w.receive_timer.stop()
        for i in range(160):
            if i in (40, 41, 42):
                continue
            a = .8*np.sin(np.arange(70)*.17+i*.045)+.4*np.cos(np.arange(70)*.43-i*.1)
            w.ingest(Observation.create(p, a, i, {'stream_id': 'A' if i < 80 else 'B',
                            'processed_position': i, 'stage': 'synthetic'}, 10+i*.05))
            if i == 0:
                w.set_reference()
        w.show()
        capture(w, 'original-no-base', width, height)
        QtTest.QTest.mouseClick(w.pca_button, QtCore.Qt.MouseButton.LeftButton)
        assert w.pca_dialog.isVisible()
        QtTest.QTest.mouseClick(w.pca_start_button, QtCore.Qt.MouseButton.LeftButton)
        deadline = time.monotonic()+8
        while w.pca_future is not None and time.monotonic() < deadline:
            QtTest.QTest.qWait(20)
            w.poll_pca()
        assert w.pca_future is None and not errors, errors
        while w.state.reprojection:
            w.state.process_reprojections()
        capture(w, 'pca-active', width, height, True)
        w.mode_combo.setCurrentIndex(w.mode_combo.findData('reference_delta'))
        capture(w, 'reference', width, height, True)
        w.mode_combo.setCurrentIndex(w.mode_combo.findData('previous_delta'))
        capture(w, 'consecutive', width, height, True)
        for kind in ('traces', 'heat'):
            w.evolution_combo.setCurrentIndex(w.evolution_combo.findData(kind))
            capture(w, kind, width, height, True)
        w.evolution_combo.setCurrentIndex(0)
        w.mode_combo.setCurrentIndex(0)
        w.state.reconfigure(replace(w.state.config, history_bytes=20000, recent_fraction=.05))
        projection_only = [f for f in w.state.navigation_samples() if f.payload is None and f.projections]
        assert projection_only, 'La cuota de prueba debe conservar coordenadas sin vector'
        w.select_sequence(projection_only[0].sequence)
        assert w.state.current() is None and np.isnan(w.matrix.displayed).all()
        capture(w, 'projection-only', width, height, True)
        path = save_state(output/f'capture-{width}.json', w.state, view=w.view_settings())
        w.close()
        w.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        replay = MonitorWindow([], MonitorConfig())
        apply_window(replay, args.theme, persist=False)
        replay.show_error = errors.append
        replay.timer.stop()
        replay.receive_timer.stop()
        assert replay.open_capture(path), errors
        replay.show()
        replay.go_live()
        capture(replay, 'replay', width, height, True)
        replay.close()
        replay.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    report = {'revision': identity(), 'native': args.native, 'theme': args.theme, 'cases': reports, 'errors': errors}
    (output/'ui-verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
