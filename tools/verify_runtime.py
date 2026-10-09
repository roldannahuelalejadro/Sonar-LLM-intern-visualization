"""Native GUI lifecycle + CPU transport timings, using synthetic vectors only."""
import json
import multiprocessing as mp
import os
from pathlib import Path
import platform
import statistics
import time

import numpy as np
from sonar_activaciones import MonitorConfig, Observation, ProbeDescriptor
from sonar_activaciones.session import MonitorSession
from sonar_activaciones.processing.history import History


def viewer(probes, config, channel):
    from PySide6 import QtCore
    from sonar_activaciones.app.main import _application
    from sonar_activaciones.app.window import MonitorWindow
    app = _application()
    window = MonitorWindow(probes, config, channel)
    window.show()
    channel.ready.set()
    QtCore.QTimer.singleShot(2500, window.close)
    app.exec()


def run():
    probe = ProbeDescriptor("load", "PRUEBA SINTETICA", "runtime-test", "CPU", 4096, "all", "synthetic/load-v1",
                            metadata={"synthetic": True})
    before = {p.pid for p in mp.active_children()}
    config = MonitorConfig(history_bytes=2*1024**2, queue_capacity=16, render_hz=10)
    session = MonitorSession([probe], config, _consumer=viewer)
    values = np.sin(np.arange(4096)*.1)
    durations = []
    results = {"accepted": 0, "dropped": 0, "disconnected": 0}
    deadline = time.monotonic() + 8
    while session.status()["state"] == "connected" and time.monotonic() < deadline:
        start = time.perf_counter_ns()
        status = session.publish("load", values)
        durations.append((time.perf_counter_ns()-start)/1e6)
        results[status] += 1
        time.sleep(.002)
    assert session.status()["state"] == "disconnected", "Native window did not close"
    assert session.publish("load", values) == "disconnected"
    counters = session.status()
    session.close()
    assert session._channel.buffer is None
    assert {p.pid for p in mp.active_children()} == before
    history = History(1024**2)
    peak = 0
    for i in range(10000):
        history.append(Observation.create(probe, values, i))
        peak = max(peak, history.used_bytes)
    assert peak <= history.budget_bytes
    assert history.evicted > 0
    assert counters["drawn"] > 0
    assert counters["drawn"] + counters["received_not_drawn"] == counters["received"]
    def avg(total, count):
        return counters[total]/max(1, counters[count])/1e6
    report = {
        "platform": platform.platform(), "python": platform.python_version(), "dimension": 4096,
        "queue_capacity": 16, "render_hz": 10, "synthetic": True,
        "publish_ms_median": statistics.median(durations), "publish_ms_p95": float(np.percentile(durations, 95)),
        "capture_to_receive_ms_mean": avg("receive_latency_ns_total", "received"),
        "capture_to_paint_ms_mean": avg("render_latency_ns_total", "drawn"),
        "scene_preparation_ms_mean": avg("draw_ns_total", "scene_updates"),
        "qt_paint_event_ms_mean": avg("paint_ns_total", "paint_count"),
        "results": results, "counters": counters,
        "history_test": {"samples": 10000, "budget_bytes": history.budget_bytes, "peak_accounted_bytes": peak,
                         "evicted": history.evicted},
        "producer_survived_window_close": True, "orphan_processes": 0,
        "note": "One local synthetic run, not performance guarantees; painting is CPU Qt paintEvent, not physical display latency."
    }
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/runtime-verification-v02.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    run()
