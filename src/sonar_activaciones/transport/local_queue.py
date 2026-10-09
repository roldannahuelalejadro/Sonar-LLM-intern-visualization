import ctypes
import time

COUNTERS = (
    "accepted", "transport_dropped", "gate_skipped", "received", "drawn",
    "received_not_drawn", "publish_attempts", "publish_ns_total",
    "receive_latency_ns_total", "receive_latency_ns_max", "draw_ns_total",
    "render_latency_ns_total",
    "scene_updates", "paint_ns_total", "paint_count",
    "transport_full", "transport_contended", "invalid_received",
)


class LocalQueue:
    """Fixed-slot shared-memory ring. Both enqueue and dequeue try-lock, never wait.

    Unlike multiprocessing.Queue there is no feeder thread to join after a viewer
    closes with large samples still pending. Lock contention drops incoming data,
    exactly like a full queue. Only related, trusted local processes share it.
    """

    def __init__(self, ctx, config):
        self.capacity = config.queue_capacity
        self.slot_bytes = config.max_sample_bytes
        self.buffer = ctx.RawArray(ctypes.c_ubyte, self.capacity * self.slot_bytes)
        self.lengths = ctx.RawArray(ctypes.c_uint32, self.capacity)
        self.head = ctx.RawValue(ctypes.c_uint32, 0)
        self.tail = ctx.RawValue(ctypes.c_uint32, 0)
        self.count = ctx.RawValue(ctypes.c_uint32, 0)
        self.lock = ctx.Lock()
        self.counters = ctx.Array(ctypes.c_uint64, len(COUNTERS))
        self.stop = ctx.Event()
        self.ready = ctx.Event()
        self.disconnected = ctx.Event()

    def add(self, name, amount=1):
        with self.counters.get_lock():
            self.counters[COUNTERS.index(name)] += int(amount)

    def snapshot(self):
        with self.counters.get_lock():
            return dict(zip(COUNTERS, self.counters[:]))

    def try_put(self, packet):
        if len(packet) > self.slot_bytes:
            raise ValueError("Paquete excede el tamano de slot")
        if self.stop.is_set() or self.disconnected.is_set():
            return "disconnected"
        if not self.lock.acquire(False):
            self.add("transport_dropped")
            self.add("transport_contended")
            return "dropped"
        try:
            if self.count.value == self.capacity:
                self.add("transport_dropped")
                self.add("transport_full")
                return "dropped"
            slot = self.tail.value
            ctypes.memmove(ctypes.addressof(self.buffer) + slot * self.slot_bytes, packet, len(packet))
            self.lengths[slot] = len(packet)
            self.tail.value = (slot + 1) % self.capacity
            self.count.value += 1
            self.add("accepted")
            return "accepted"
        finally:
            self.lock.release()

    def try_get(self):
        if not self.lock.acquire(False):
            return None
        try:
            if not self.count.value:
                return None
            slot = self.head.value
            packet = ctypes.string_at(ctypes.addressof(self.buffer) + slot * self.slot_bytes,
                                      self.lengths[slot])
            self.head.value = (slot + 1) % self.capacity
            self.count.value -= 1
            return packet
        finally:
            self.lock.release()

    def received(self, sample):
        latency = max(0, int((time.monotonic() - sample.captured_at) * 1e9))
        with self.counters.get_lock():
            self.counters[COUNTERS.index("received")] += 1
            self.counters[COUNTERS.index("receive_latency_ns_total")] += latency
            idx = COUNTERS.index("receive_latency_ns_max")
            self.counters[idx] = max(self.counters[idx], latency)
