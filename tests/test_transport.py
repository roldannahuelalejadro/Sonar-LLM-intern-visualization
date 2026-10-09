import multiprocessing as mp
import time
import numpy as np

from sonar_activaciones import MonitorConfig, Observation
from sonar_activaciones.session import MonitorSession
from sonar_activaciones.transport.local_queue import LocalQueue
from .test_core import probe, sample


def idle_consumer(probes, config, channel):
    channel.ready.set()
    channel.stop.wait(30)
    channel.disconnected.set()


def short_consumer(probes, config, channel):
    channel.ready.set()
    time.sleep(.2)
    channel.disconnected.set()


def drain_consumer(probes, config, channel):
    channel.ready.set()
    while not channel.stop.is_set():
        packet = channel.try_get()
        if packet is not None:
            channel.received(Observation.unpack(packet))
        else:
            time.sleep(.001)
    channel.disconnected.set()


def test_bounded_fifo_and_contention():
    queue = LocalQueue(mp.get_context("spawn"), MonitorConfig(queue_capacity=2))
    assert queue.try_put(sample(0).pack()) == "accepted"
    assert queue.try_put(sample(1).pack()) == "accepted"
    assert queue.try_put(sample(2).pack()) == "dropped"
    assert Observation.unpack(queue.try_get()).sequence == 0
    assert Observation.unpack(queue.try_get()).sequence == 1
    assert queue.try_get() is None
    queue.lock.acquire()
    try:
        assert queue.try_put(sample(3).pack()) == "dropped"
    finally:
        queue.lock.release()
    assert queue.snapshot()["transport_dropped"] == 2


def test_slow_consumer_never_waits_for_space_and_closes():
    before = {p.pid for p in mp.active_children()}
    for _ in range(3):
        session = MonitorSession([probe()], MonitorConfig(queue_capacity=2), _consumer=idle_consumer)
        start = time.monotonic()
        statuses = [session.publish("p", np.arange(3.)) for _ in range(200)]
        assert time.monotonic() - start < 3
        assert statuses.count("accepted") == 2
        assert session.status()["transport_dropped"] == 198
        session.close()
        session.close()
        assert session.publish("p", np.arange(3.)) == "disconnected"
    assert {p.pid for p in mp.active_children()} == before


def test_closed_consumer_and_gate():
    session = MonitorSession([probe()], MonitorConfig(capture_hz=1), _consumer=short_consumer)
    assert session.capture_allowed("p")
    assert not session.capture_allowed("p")
    assert session.status()["gate_skipped"] == 1
    time.sleep(.5)
    assert session.status()["state"] == "disconnected"
    assert session.publish("p", np.arange(3.)) == "disconnected"
    session.close()


def test_spawn_transfers_large_sample():
    p = probe(dimension=64000)
    with MonitorSession([p], _consumer=drain_consumer) as session:
        assert session.publish("p", np.arange(64000.)) == "accepted"
        deadline = time.monotonic() + 5
        while not session.status()["received"] and time.monotonic() < deadline:
            time.sleep(.01)
        assert session.status()["received"] == 1

