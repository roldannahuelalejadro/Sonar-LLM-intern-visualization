"""Bounded synthetic longevity check. No model or semantic experiment."""
import json
import platform
import time
from pathlib import Path
from dataclasses import replace
import numpy as np
from sonar_activaciones import MonitorConfig, ProbeDescriptor, Observation
from sonar_activaciones.app.state import ViewerState
from sonar_activaciones.processing.memory import rss_bytes
from sonar_activaciones.processing.projection import component_basis


def main(seconds=610):
    mib = 1024**2
    states = []
    for d in (70, 4096, 5120):
        p = ProbeDescriptor(f"p{d}", f"Synthetic {d}", "soak", "cpu", d, "all", f"synthetic/{d}")
        config = MonitorConfig(data_budget_bytes=2*mib, queue_capacity=1, max_sample_bytes=32768,
                               work_bytes=0, recent_fraction=.1)
        state = ViewerState([p], config)
        state.install_basis(component_basis(p, [0, 1]))
        states.append((state, p, np.arange(d, dtype=np.float32)*.001))
    start = time.monotonic()
    checkpoint = 0
    seq = 0
    readings = []
    while time.monotonic()-start < seconds:
        for _ in range(10):
            for state, p, values in states:
                state.ingest(Observation.create(p, values+np.sin(seq*.01), seq))
                state.process_reprojections()
                assert state.plan.committed <= state.plan.total
                for ring in state.history.rings.values():
                    assert ring.raw_bytes <= ring.recent_limit and ring.projected_bytes <= ring.projected_limit
            seq += 1
        elapsed = time.monotonic()-start
        if elapsed >= checkpoint:
            record = {"seconds": round(elapsed, 3), "rss": rss_bytes(), "samples_per_probe": seq, "states": []}
            for state, p, _ in states:
                state.live()
                state.set_reference()
                state.freeze()
                rejected = None
                previous_plan = state.plan
                try:
                    state.reconfigure(replace(state.config, data_budget_bytes=(3 if checkpoint % 60 else 2)*mib))
                except ValueError as exc:
                    rejected = str(exc)
                    assert state.plan is previous_plan
                state.live()
                if len(state.segments) >= 3:
                    state.retire_segment(next(iter(state.segments)))
                state.install_basis(component_basis(p, [2, 3]))
                record["states"].append({"d": p.dimension, "managed_reserved": state.plan.committed,
                                          "history_used": state.history.used_bytes, "reconfiguration_rejected": rejected,
                                          "counters": dict(state.history.counters)})
            readings.append(record)
            print(json.dumps(record), flush=True)
            checkpoint += 30
        time.sleep(.05)
    for state, _, _ in states:
        assert state.history.counters["projection_retired"] > 1000
        assert state.history.counters["capture_retired"] > 1000
    result = {"seconds": time.monotonic()-start, "platform": platform.platform(),
              "python": platform.python_version(), "samples_per_probe": seq, "checkpoints": readings,
              "scope": "core, three independent states, no transport/Qt", "completed": True}
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/soak-v02.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("SOAK COMPLETE", flush=True)


if __name__ == "__main__":
    main()
