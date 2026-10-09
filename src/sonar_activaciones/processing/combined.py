"""Two bounded FIFO indexes sharing one context/header per capture."""
from collections import OrderedDict, Counter, deque
from dataclasses import dataclass, field
import uuid
import numpy as np
from ..contracts import Observation, Metadata
from .memory import header_cost, raw_cost, projected_cost


def record_event(counters, events, reason, probe_id, sequence, count=1):
    counters[reason] += count
    events.append((reason, probe_id, sequence, count))


@dataclass(slots=True)
class Frame:
    descriptor: object
    sequence: int
    captured_at: float
    context: Metadata
    payload: bytes | None = None
    projections: dict = field(default_factory=dict)
    derived: set = field(default_factory=set)

    @property
    def probe_id(self):
        return self.descriptor.probe_id

    @property
    def availability(self):
        if self.payload is not None:
            return "both" if self.projections else "vector"
        return "projection" if self.projections else "absent"

    def observation(self):
        if self.payload is not None:
            return Observation(self.descriptor, self.sequence, self.captured_at, self.payload, self.context)

    def pin(self):
        # Immutable owners can be shared; their full eventual ownership is reserved.
        return Frame(self.descriptor, self.sequence, self.captured_at, self.context,
                     self.payload, dict(self.projections), set(self.derived))


class ProbeHistory:
    def __init__(self, descriptor, recent, projected, notify):
        self.descriptor = descriptor
        self.recent_limit, self.projected_limit = recent, projected
        self.frames, self.raw, self.projected = OrderedDict(), OrderedDict(), OrderedDict()
        self.raw_bytes = self.projected_bytes = 0
        self.notify = notify

    def _header(self, frame):
        return header_cost(frame.context)

    def add(self, sample):
        frame = Frame(self.descriptor, sample.sequence, sample.captured_at, sample.context, sample.payload)
        cost = self._header(frame) + raw_cost(self.descriptor.dimension)
        if cost > self.recent_limit:
            self.notify("vector_too_large", frame.sequence)
            return frame
        self.frames[frame.sequence] = frame
        self.raw[frame.sequence] = None
        self.raw_bytes += cost
        self.trim()
        return frame

    def add_projection(self, frame, segment_id, values, derived=False):
        if segment_id in frame.projections:
            return False
        with np.errstate(over="ignore", invalid="ignore"):
            z = np.asarray(values, dtype="<f4")
        if z.ndim != 1 or not 1 <= len(z) <= 32 or not np.isfinite(z).all():
            raise ValueError("Coordenadas float32 no finitas o dimension invalida")
        charge = projected_cost(len(z)) + (0 if frame.projections else self._header(frame))
        if charge > self.projected_limit:
            self.notify("projection_quota", frame.sequence)
            return False
        seq = frame.sequence
        if seq not in self.frames:
            frame.payload = None
            self.frames[seq] = frame
        elif not frame.projections and frame.payload is not None:
            self.raw_bytes -= self._header(frame)
        frame.projections[segment_id] = z.tobytes()
        if derived:
            frame.derived.add(segment_id)
        self.projected[(seq, segment_id)] = None
        self.projected_bytes += charge
        self.trim()
        return True

    def _retire_empty(self, frame):
        if frame.payload is None and not frame.projections:
            del self.frames[frame.sequence]
            self.notify("capture_retired", frame.sequence)

    def remove_raw(self):
        seq, _ = self.raw.popitem(last=False)
        frame = self.frames[seq]
        self.raw_bytes -= raw_cost(self.descriptor.dimension) + (0 if frame.projections else self._header(frame))
        frame.payload = None
        self.notify("vector_retired_projection_kept" if frame.projections else "vector_retired", seq)
        self._retire_empty(frame)

    def remove_projection(self, key):
        self.projected.pop(key)
        seq, segment_id = key
        frame = self.frames[seq]
        payload = frame.projections.pop(segment_id)
        frame.derived.discard(segment_id)
        self.projected_bytes -= projected_cost(len(payload)//4)
        if not frame.projections:
            self.projected_bytes -= self._header(frame)
            if frame.payload is not None:
                self.raw_bytes += self._header(frame)
        self.notify("projection_retired", seq)
        self._retire_empty(frame)

    def trim(self):
        while self.projected_bytes > self.projected_limit and self.projected:
            self.remove_projection(next(iter(self.projected)))
        while self.raw_bytes > self.recent_limit and self.raw:
            self.remove_raw()
        assert self.raw_bytes >= 0 and self.projected_bytes >= 0

    def resize(self, recent, projected):
        shrinking = recent < self.recent_limit or projected < self.projected_limit
        self.recent_limit, self.projected_limit = recent, projected
        self.trim()
        if shrinking:
            # Release dict high-water capacity as well as payloads. Only indexes
            # coexist briefly; the per-frame allowance includes this workspace.
            self.raw = OrderedDict(self.raw)
            self.projected = OrderedDict(self.projected)
            self.frames = OrderedDict(self.frames)

    def tail(self, limit=512, *, raw=False, before=None):
        result = []
        for seq in reversed(self.raw if raw else self.frames):
            if before is None or seq <= before:
                result.append(self.frames[seq])
                if len(result) >= limit:
                    break
        return list(reversed(result))


class CombinedHistory:
    def __init__(self, probes, plan, session_id=None):
        self.session_id = session_id or uuid.uuid4().hex
        self.counters, self.events = Counter(), deque(maxlen=128)
        self.rings = {p.probe_id: ProbeHistory(p, plan.recent[p.probe_id], plan.projected[p.probe_id],
                     lambda reason, seq, pid=p.probe_id, counters=self.counters, events=self.events:
                     record_event(counters, events, reason, pid, seq)) for p in probes}

    def event(self, reason, probe_id, sequence, count=1):
        record_event(self.counters, self.events, reason, probe_id, sequence, count)

    @property
    def used_bytes(self):
        return sum(r.raw_bytes + r.projected_bytes for r in self.rings.values())

    @property
    def evicted(self):
        return self.counters["vector_retired"] + self.counters["vector_retired_projection_kept"]

    def samples(self, probe_id=None, limit=None, before=None):
        result = []
        for pid, ring in self.rings.items():
            if probe_id is None or pid == probe_id:
                frames = ring.tail(limit or len(ring.raw), raw=True, before=before) if ring.raw else []
                result.extend(f.observation() for f in frames)
        return result

    def reconfigure(self, plan):
        for pid, ring in self.rings.items():
            ring.resize(plan.recent[pid], plan.projected[pid])

    def impact(self, plan):
        detail_lost = retired = projections_lost = 0
        # Apply is infrequent; simulate identities/costs, never copy vector arrays.
        for pid, ring in self.rings.items():
            raw_removed, proj_removed = set(), Counter()
            rbytes, pbytes = ring.raw_bytes, ring.projected_bytes
            for (seq, sid) in ring.projected:
                if pbytes <= plan.projected[pid]:
                    break
                f = ring.frames[seq]
                pbytes -= projected_cost(len(f.projections[sid])//4)
                projections_lost += 1
                proj_removed[seq] += 1
                if proj_removed[seq] == len(f.projections):
                    pbytes -= ring._header(f)
                    if f.payload is not None:
                        rbytes += ring._header(f)
            for seq in ring.raw:
                if rbytes <= plan.recent[pid]:
                    break
                f = ring.frames[seq]
                rbytes -= raw_cost(f.descriptor.dimension)
                if proj_removed[seq] == len(f.projections):
                    rbytes -= ring._header(f)
                raw_removed.add(seq)
            detail_lost += len(raw_removed)
            retired += sum((f.payload is None or seq in raw_removed) and
                           proj_removed[seq] == len(f.projections) for seq, f in ring.frames.items())
        return {"detail_lost": detail_lost, "captures_retired": retired, "projections_lost": projections_lost}
