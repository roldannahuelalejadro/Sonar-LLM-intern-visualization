"""Native animated rendering check with deterministic 30 Hz synthetic input."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore
from evidence import identity
from sonar_activaciones import MonitorConfig, Observation, ProbeDescriptor
from sonar_activaciones.app.main import _application
from sonar_activaciones.app.window import MonitorWindow
from sonar_activaciones.app.themes import apply_window
from sonar_activaciones.processing.projection import component_basis


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hz', type=float, default=30)
    parser.add_argument('--seconds', type=float, default=10)
    parser.add_argument('--width', type=int, default=1220)
    parser.add_argument('--height', type=int, default=800)
    parser.add_argument('--output', default='artifacts/motion-current.json')
    parser.add_argument('--theme', choices=['laboratorio', 'grafito'], default='laboratorio')
    parser.add_argument('--switch-theme', action='store_true')
    args = parser.parse_args()
    revision = identity()
    app = _application()
    p = ProbeDescriptor('demo', 'Sintetico 30 Hz', 'motion-check', 'cpu', 70,
                        'all', 'synthetic/motion', metadata={'synthetic': True})
    w = MonitorWindow([p], MonitorConfig(render_hz=args.hz))
    apply_window(w, args.theme, persist=False)
    w.receive_timer.stop()
    w.resize(args.width, args.height)
    w.state.install_basis(component_basis(p, [0, 1]))
    axis = np.arange(p.dimension)
    sequence = 0
    def publish():
        nonlocal sequence
        values = .7*np.sin(axis*.18+sequence*.04)+.35*np.cos(axis*.53-sequence*.07)
        w.ingest(Observation.create(p, values, sequence, context={'stream_id': f'A{sequence//180}'}))
        sequence += 1
    for _ in range(128):
        publish()
    w.render()
    w.show()
    app.processEvents()
    counts = {'ScatterPlotItem': 0, 'PlotDataItem': 0, 'InfiniteLine': 0}
    original = {}
    for name in counts:
        cls = getattr(pg, name)
        original[name] = cls.__init__
        def counted(self, *a, _name=name, **kw):
            counts[_name] += 1
            original[_name](self, *a, **kw)
        cls.__init__ = counted
    geometries, times, paints, sequences = [], [], [], []
    original_render = w.render
    def render(*a):
        started = time.perf_counter_ns()
        original_render(*a)
        times.append((time.perf_counter_ns()-started)/1e6)
    w.render = render
    started = time.monotonic()
    def painted(key, ns):
        if key and (not sequences or key[1] != sequences[-1]):
            paints.append(time.monotonic()-started)
            sequences.append(key[1])
    w.matrix.painted.connect(painted)
    def sample_geometry():
        row = []
        for widget in (w.matrix, w.directions_view.graph, w.history_view):
            origin = widget.mapTo(w, QtCore.QPoint())
            row.append([origin.x(), origin.y(), widget.width(), widget.height()])
        geometries.append(row)
    source = QtCore.QTimer()
    source.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
    source.timeout.connect(publish)
    source.start(33)
    geometry = QtCore.QTimer()
    geometry.timeout.connect(sample_geometry)
    geometry.start(40)
    if args.switch_theme:
        other = 'grafito' if args.theme == 'laboratorio' else 'laboratorio'
        QtCore.QTimer.singleShot(round(args.seconds*500), lambda: apply_window(w, other, persist=False))
    def finish():
        source.stop()
        geometry.stop()
        elapsed = time.monotonic()-started
        intervals = np.diff(paints)*1000
        final_revision = identity()
        report = {'revision': revision, 'theme': args.theme, 'switched_theme': args.switch_theme,
                  'source_unchanged': revision['application_sha256'] == final_revision['application_sha256'],
                  'duration_s': elapsed, 'viewport': [w.width(), w.height()],
                  'requested_hz': args.hz, 'input_captures': sequence-128, 'painted_captures': len(paints),
                  'painted_hz': (len(paints)-1)/(paints[-1]-paints[0]) if len(paints)>1 else 0,
                  'paint_interval_ms_p95': float(np.percentile(intervals, 95)) if len(intervals) else None,
                  'render_ms_median': float(np.median(times)), 'render_ms_p95': float(np.percentile(times, 95)),
                  'geometry_variants': len({json.dumps(g) for g in geometries}),
                  'geometry_first': geometries[0], 'geometry_last': geometries[-1],
                  'created_graphics_items': counts, 'rss_note': 'UI-only test; SDK transport checked separately.'}
        path = Path(args.output)
        path.parent.mkdir(exist_ok=True, parents=True)
        w.grab().save(str(path.with_suffix('.png')))
        path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)
        w.close()
    QtCore.QTimer.singleShot(round(args.seconds*1000), finish)
    app.exec()
    for name, constructor in original.items():
        getattr(pg, name).__init__ = constructor


if __name__ == '__main__':
    main()
