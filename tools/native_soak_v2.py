"""Ten-minute end-to-end synthetic SDK/Qt/retention/I/O check on Windows."""
import json
import multiprocessing as mp
from pathlib import Path
import platform
import tempfile
import time
from dataclasses import replace
import numpy as np
from evidence import identity
from sonar_activaciones import MonitorConfig, ProbeDescriptor
from sonar_activaciones.session import MonitorSession


def viewer(probes, config, channel):
    from PySide6 import QtCore
    from sonar_activaciones.app.main import _application
    from sonar_activaciones.app.window import MonitorWindow
    from sonar_activaciones.processing.projection import component_basis
    from sonar_activaciones.processing.memory import rss_bytes
    from sonar_activaciones.storage.mixed import save_state, load_state
    app = _application()
    window = MonitorWindow(probes, config, channel)
    window.resize(900, 650)
    for p in probes:
        window.state.install_basis(component_basis(p, [0, 1]), p.probe_id)
    window.show()
    revision = identity()
    start = time.monotonic()
    checkpoints, errors = [], []
    temporary = tempfile.TemporaryDirectory(prefix='sonar-v02-soak-')
    def checkpoint():
        elapsed = time.monotonic()-start
        state = window.state
        try:
            window.probe_combo.setCurrentIndex(len(checkpoints) % len(probes))
            window.mode_combo.setCurrentIndex(len(checkpoints) % 3)
            window.evolution_combo.setCurrentIndex(len(checkpoints) % 3)
            state.live()
            state.set_reference()
            state.freeze()
            state.reconfigure(replace(state.config, data_budget_bytes=(8+len(checkpoints)%2)*1024**2))
            state.live()
            if len(checkpoints) % 2 == 0:
                while len(state.segments) > len(probes):
                    state.retire_segment(next(iter(state.segments)))
                p = probes[len(checkpoints) % len(probes)]
                state.install_basis(component_basis(p, [2, 3]), p.probe_id)
                path = save_state(Path(temporary.name)/'capture.json', state, limit=3)
                candidate, _, _ = load_state(path, state.config, state.work)
                assert candidate.history.session_id == state.history.session_id
                del candidate
            for ring in state.history.rings.values():
                assert ring.raw_bytes <= ring.recent_limit
                assert ring.projected_bytes <= ring.projected_limit
            assert state.plan.committed <= state.plan.total
        except Exception as exc:
            errors.append(repr(exc))
        record = {"seconds": elapsed, "rss": rss_bytes(), "managed_capacity": state.plan.committed,
                  "history_used": state.history.used_bytes, "received": state.received_count,
                  "history_counters": dict(state.history.counters), "transport": channel.snapshot(),
                  "processing_ns": state.processing_ns, "projection_ns": state.projection_ns}
        checkpoints.append(record)
        print(json.dumps({"seconds": round(elapsed), "rss": record['rss'], "received": state.received_count,
                          "errors": errors}), flush=True)
    def finish():
        checkpoint()
        for name in ('projection_retired', 'capture_retired', 'vector_retired_projection_kept'):
            if window.state.history.counters[name] < 1000:
                errors.append(f'Insufficient wraps: {name}')
        report = {"scope": "native Qt + real manual SDK + three probes + mixed I/O + visual modes",
                  'revision': revision, 'final_revision': identity(),
                  "duration": time.monotonic()-start, "platform": platform.platform(),
                  "checkpoints": checkpoints, "errors": errors, "completed": not errors}
        if report['final_revision']['application_sha256'] != revision['application_sha256']:
            errors.append('Application changed during verification')
            report['completed'] = False
        Path('artifacts/native-soak-v021.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        window.close()
    pulse = QtCore.QTimer()
    pulse.timeout.connect(checkpoint)
    pulse.start(30000)
    QtCore.QTimer.singleShot(610000, finish)
    channel.ready.set()
    app.exec()
    temporary.cleanup()


def main():
    Path('artifacts').mkdir(exist_ok=True)
    probes = [ProbeDescriptor(f'p{d}', f'SOAK SINTETICO d={d}', 'native-soak', 'cpu', d, 'all', f'synthetic/{d}',
                              metadata={'synthetic': True}) for d in (70, 4096, 5120)]
    config = MonitorConfig(data_budget_bytes=8*1024**2, recent_fraction=.1, work_bytes=4*1024**2,
                           queue_capacity=4, max_sample_bytes=32768)
    children = {p.pid for p in mp.active_children()}
    session = MonitorSession(probes, config, _consumer=viewer)
    values = [np.sin(np.arange(p.dimension, dtype=np.float32)*.01) for p in probes]
    start = time.monotonic()
    seq = 0
    child_exitcode = None
    try:
        while session.status()['state'] == 'connected' and time.monotonic()-start < 640:
            for p, a in zip(probes, values):
                session.publish(p.probe_id, a+np.sin(seq*.02), {'stream_id': 'A' if seq%1000 < 500 else 'B'})
            seq += 1
            time.sleep(.004)
        session._process.join(3)
        child_exitcode = session._process.exitcode
    finally:
        session.close()
    assert {p.pid for p in mp.active_children()} == children
    report = json.loads(Path('artifacts/native-soak-v021.json').read_text())
    report['viewer_exitcode'] = child_exitcode
    report['orphan_processes'] = len({p.pid for p in mp.active_children()}-children)
    report['completed'] = report['completed'] and child_exitcode == 0
    Path('artifacts/native-soak-v021.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    assert report['completed'], report['errors']
    print('NATIVE SOAK COMPLETE, no orphan children', flush=True)


if __name__ == '__main__':
    main()
