"""45-second native check with a separate 30 Hz manual SDK producer."""
import json
import multiprocessing as mp
from pathlib import Path
import time
import numpy as np
from evidence import identity
from sonar_activaciones import MonitorConfig, ProbeDescriptor
from sonar_activaciones.session import MonitorSession

OUTPUT = Path('artifacts/motion-sdk.json')


def viewer(probes, config, channel):
    from PySide6 import QtCore
    from sonar_activaciones.app.main import _application
    from sonar_activaciones.app.window import MonitorWindow
    from sonar_activaciones.processing.memory import rss_bytes
    from sonar_activaciones.processing.projection import component_basis
    app = _application()
    w = MonitorWindow(probes, config, channel)
    w.resize(900, 650)
    for p in probes:
        w.state.install_basis(component_basis(p, [0, 1]), p.probe_id)
    revision = identity()
    started = time.perf_counter()
    phase = 0
    painted = [[], [], []]
    last = None
    checks = []
    errors = []
    def on_paint(key, ns):
        nonlocal last
        if key is not None and key != last:
            painted[phase].append(time.perf_counter()-started)
            last = key
    w.matrix.painted.connect(on_paint)
    def checkpoint():
        try:
            assert w.state.plan.committed <= w.state.plan.total
            for ring in w.state.history.rings.values():
                assert ring.raw_bytes <= ring.recent_limit
                assert ring.projected_bytes <= ring.projected_limit
        except AssertionError:
            errors.append('Memory quota exceeded')
        checks.append({'time_s': time.perf_counter()-started, 'rss': rss_bytes(),
                       'managed': w.state.plan.committed, 'received': w.state.received_count})
    def switch(number, probe, kind):
        nonlocal phase, last
        phase, last = number, None
        w.probe_combo.setCurrentIndex(probe)
        w.evolution_combo.setCurrentIndex(w.evolution_combo.findData(kind))
    def finish():
        checkpoint()
        phases = []
        for name, samples in zip(('70D change', '4096D traces', '4096D heat'), painted):
            dt = np.diff(samples)
            phases.append({'name': name, 'painted': len(samples),
                           'hz': (len(samples)-1)/(samples[-1]-samples[0]) if len(samples)>1 else 0,
                           'interval_ms_p95': float(np.percentile(dt*1000, 95)) if len(dt) else None})
        report = {'revision': revision, 'source_unchanged': revision['application_sha256'] == identity()['application_sha256'],
                  'duration_s': time.perf_counter()-started, 'phases': phases, 'checkpoints': checks,
                  'errors': errors, 'config': {'render_hz': config.render_hz, 'producer_hz_per_probe': 30,
                                             'budget_bytes': config.data_budget_bytes, 'queue_capacity': config.queue_capacity}}
        OUTPUT.write_text(json.dumps(report, indent=2), encoding='utf-8')
        w.grab().save(str(OUTPUT.with_suffix('.png')))
        w.close()
    pulse = QtCore.QTimer()
    pulse.timeout.connect(checkpoint)
    pulse.start(1000)
    QtCore.QTimer.singleShot(15000, lambda: switch(1, 1, 'traces'))
    QtCore.QTimer.singleShot(30000, lambda: switch(2, 1, 'heat'))
    QtCore.QTimer.singleShot(45000, finish)
    w.show()
    channel.ready.set()
    app.exec()


def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    probes = [ProbeDescriptor(f'p{d}', f'Sintetico {d}D', 'motion-sdk', 'cpu', d, 'all',
                              f'synthetic/{d}', metadata={'synthetic': True}) for d in (70, 4096)]
    config = MonitorConfig(render_hz=30, data_budget_bytes=16*1024**2, work_bytes=4*1024**2,
                           queue_capacity=16, max_sample_bytes=32768)
    children = {p.pid for p in mp.active_children()}
    session = MonitorSession(probes, config, _consumer=viewer)
    axes = [np.arange(p.dimension)*.18 for p in probes]
    step = 0
    started = time.perf_counter()
    try:
        while session.status()['state'] == 'connected' and time.perf_counter()-started < 55:
            for p, axis in zip(probes, axes):
                session.publish(p.probe_id, np.sin(axis+step*.04), {'stream_id': 'A'})
            step += 1
            time.sleep(1/30)
        counters = session.status()
        session._process.join(3)
        exitcode = session._process.exitcode
    finally:
        session.close()
    report = json.loads(OUTPUT.read_text())
    report.update({'counters': counters, 'viewer_exitcode': exitcode,
                   'orphan_processes': len({p.pid for p in mp.active_children()}-children)})
    OUTPUT.write_text(json.dumps(report, indent=2), encoding='utf-8')
    assert not report['errors'] and report['source_unchanged']
    assert exitcode == 0 and report['orphan_processes'] == 0
    assert counters['received'] > 300 and counters['invalid_received'] == 0
    print(json.dumps({k: report[k] for k in ('duration_s', 'phases', 'viewer_exitcode', 'orphan_processes', 'errors')}))


if __name__ == '__main__':
    main()
