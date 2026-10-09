import importlib.util
import multiprocessing as mp
import threading
import time

from .contracts import MonitorConfig, Observation, validate_probes
from .transport.local_queue import LocalQueue


def _gui_entry(probes, config, channel):
    try:
        from .app.main import run_monitor
        run_monitor(probes, config, channel)
    finally:
        channel.disconnected.set()


class MonitorSession:
    def __init__(self, probes, config=None, *, _consumer=None):
        self.config = config or MonitorConfig()
        validated = validate_probes(probes, self.config)
        if _consumer is None and importlib.util.find_spec("PySide6") is None:
            raise RuntimeError("GUI no instalada: pip install sonar-activaciones[gui]")
        self.probes = {p.probe_id: p for p in validated}
        self._sequences = dict.fromkeys(self.probes, 0)
        self._gates = dict.fromkeys(self.probes, float("-inf"))
        self._mutex = threading.RLock()
        self._closed = False
        ctx = mp.get_context("spawn")
        self._channel = LocalQueue(ctx, self.config)
        self._process = ctx.Process(target=_consumer or _gui_entry,
                                    args=(validated, self.config, self._channel),
                                    name="SONAR-viewer", daemon=True)
        self._process.start()
        deadline = time.monotonic() + 20
        while not self._channel.ready.wait(0.02):
            if not self._process.is_alive() or time.monotonic() >= deadline:
                self.close()
                raise RuntimeError("No se pudo iniciar la ventana SONAR; revisar consola y entorno grafico")

    def _connected(self):
        return not self._closed and not self._channel.disconnected.is_set() and self._process.is_alive()

    def _probe(self, probe_id):
        try:
            return self.probes[probe_id]
        except KeyError as exc:
            raise ValueError(f"Sonda no declarada: {probe_id}") from exc

    def capture_allowed(self, probe_id):
        """Call BEFORE expensive capture. publish() does not invoke this gate again.

        A rejected gate consumes a sequence position, preserving observable gaps.
        The producer must call this once per proposed sample when opting in.
        """
        with self._mutex:
            self._probe(probe_id)
            if not self._connected():
                return False
            now = time.monotonic()
            if self.config.capture_hz and now - self._gates[probe_id] < 1 / self.config.capture_hz:
                self._sequences[probe_id] += 1
                self._channel.add("gate_skipped")
                return False
            self._gates[probe_id] = now
            return True

    def publish(self, probe_id, values, context=None):
        started = time.perf_counter_ns()
        with self._mutex:
            probe = self._probe(probe_id)
            if not self._connected():
                return "disconnected"
            sample = Observation.create(probe, values, self._sequences[probe_id], context,
                                        max_bytes=self.config.max_sample_bytes)
            self._sequences[probe_id] += 1
            result = self._channel.try_put(sample.pack())
            self._channel.add("publish_attempts")
            self._channel.add("publish_ns_total", time.perf_counter_ns() - started)
            return result

    def status(self):
        with self._mutex:
            state = "closed" if self._closed else "connected" if self._connected() else "disconnected"
            return {"state": state, **self._channel.snapshot()}

    def close(self):
        with self._mutex:
            if self._closed:
                return
            self._closed = True
            self._channel.stop.set()
            self._process.join(3)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(2)
            if self._process.is_alive():
                self._process.kill()
                self._process.join(1)
            self._channel.disconnected.set()
            self._process.close()
            self._channel.buffer = None
            self._channel.lengths = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def open_monitor(probes, config=None):
    return MonitorSession(probes, config)
