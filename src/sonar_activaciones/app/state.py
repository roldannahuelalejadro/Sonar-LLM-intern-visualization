from collections import OrderedDict, deque
from dataclasses import replace
import time
from ..processing.combined import CombinedHistory
from ..processing.memory import plan_memory, WorkAdmission, pca_known_peak, header_cost
from ..processing.reference import values_for


class ViewerState:
    def __init__(self, probes, config):
        self.probes = {p.probe_id: p for p in probes}
        self.config = config
        self.plan = plan_memory(self.probes.values(), config)
        self.work = WorkAdmission(config.work_bytes)
        self.history = CombinedHistory(self.probes.values(), self.plan)
        self.selected_probe = next(iter(self.probes), None)
        self.last_sequences, self.references, self.bases, self.basis_starts = {}, {}, {}, {}
        self.segments = OrderedDict()
        self.active_segments = {}
        self.selected_segment = None
        self.reprojection = deque(maxlen=512)
        self.frozen = None
        self.mode = "raw"
        self.received_count = self.processing_ns = self.projection_ns = self.revision = 0

    def ingest(self, sample):
        started = time.perf_counter_ns()
        if self.probes.get(sample.probe_id) != sample.descriptor:
            raise ValueError("Descriptor no declarado o modificado durante la serie")
        last = self.last_sequences.get(sample.probe_id, -1)
        if sample.sequence <= last:
            raise ValueError("Secuencia duplicada o fuera de orden")
        if sample.sequence > last+1:
            self.history.event("not_received", sample.probe_id, sample.sequence, sample.sequence-last-1)
        self.last_sequences[sample.probe_id] = sample.sequence
        frame = self.history.rings[sample.probe_id].add(sample)
        sid = self.active_segments.get(sample.probe_id)
        if sid and self.config.retention_mode == "combined":
            self._project(frame, sid)
        elif self.config.retention_mode == "combined":
            self.history.event("projection_pending_basis", sample.probe_id, sample.sequence)
        self.received_count += 1
        self.processing_ns += time.perf_counter_ns()-started

    def _project(self, frame, sid, derived=False):
        start = time.perf_counter_ns()
        try:
            obs = frame.observation()
            if obs is None:
                return
            values = self.segments[sid]["basis"].project(obs.values)
            if self.history.rings[frame.probe_id].add_projection(frame, sid, values, derived):
                self.history.counters["projected"] += 1
        except ValueError:
            self.history.event("projection_nonfinite", frame.probe_id, frame.sequence)
        finally:
            self.projection_ns += time.perf_counter_ns()-start

    def selection(self):
        if self.frozen is not None:
            return self.frozen
        ring = self.history.rings.get(self.selected_probe)
        frames = ring.tail(1) if ring else []
        return frames[-1] if frames else None

    def visible_history(self, limit=128):
        selected = self.selection()
        samples = self.history.samples(self.selected_probe, limit, selected.sequence if selected else None)
        if self.frozen is not None and self.frozen.payload is not None:
            if not samples or samples[-1].sequence != self.frozen.sequence:
                samples.append(self.frozen.observation())
        return samples[-limit:]

    def current(self):
        selected = self.selection()
        return selected.observation() if selected else None

    def previous(self):
        samples = self.visible_history(2)
        return samples[-2] if len(samples) > 1 else None

    def values(self):
        current = self.current()
        return None if current is None else values_for(current, self.mode, self.references.get(self.selected_probe), self.previous())

    def set_reference(self):
        current = self.current()
        if current is None:
            raise ValueError("La referencia completa requiere un vector retenido")
        self.references = {self.selected_probe: current}

    @property
    def basis_bytes(self):
        return sum(s["basis"].nbytes + 2048 for s in self.segments.values())

    def install_basis(self, basis, probe_id=None, *, reproject=True):
        probe_id = probe_id or self.selected_probe
        basis.validate_probe(self.probes[probe_id])
        sid = basis.basis_id
        if sid in self.segments:
            raise ValueError("ID de base ya existente; las bases son inmutables")
        if len(self.segments) >= self.config.max_segments:
            raise ValueError("Limite de segmentos: retirar uno explicitamente o conservar la base vigente")
        plan = plan_memory(self.probes.values(), self.config, basis_bytes=self.basis_bytes+basis.nbytes+2048)
        self.history.reconfigure(plan)
        self.plan = plan
        self.segments[sid] = {"basis": basis, "probe_id": probe_id, "start": self.last_sequences.get(probe_id, -1)+1}
        self.bases[probe_id], self.active_segments[probe_id] = basis, sid
        if probe_id == self.selected_probe:
            self.selected_segment = sid
        self.basis_starts[probe_id] = self.segments[sid]["start"]
        self.history.event("basis_changed", probe_id, self.basis_starts[probe_id])
        # Only bounded identities are queued; vectors can expire meanwhile.
        if reproject and self.config.retention_mode == "combined":
            ring = self.history.rings[probe_id]
            if self.reprojection:
                self.history.event("reprojection_replaced", probe_id, self.basis_starts[probe_id], len(self.reprojection))
                self.reprojection.clear()
            for frame in ring.tail(512, raw=True):
                self.reprojection.append((probe_id, frame.sequence, sid))
        self.revision += 1

    def process_reprojections(self, limit=32, budget_ms=6):
        start = time.perf_counter()
        for _ in range(limit):
            if not self.reprojection or (time.perf_counter()-start)*1000 >= budget_ms:
                break
            pid, seq, sid = self.reprojection.popleft()
            ring = self.history.rings[pid]
            frame = ring.frames.get(seq)
            if sid in self.segments and frame is not None and frame.payload is not None:
                self._project(frame, sid, derived=True)
            else:
                self.history.event("reprojection_unavailable", pid, seq)

    def retire_segment(self, sid):
        if self.work.active:
            raise ValueError("Esperar al trabajo en curso")
        if self.frozen and sid in self.frozen.projections:
            raise ValueError("Volver al presente antes de retirar la base de la seleccion congelada")
        segment = self.segments[sid]
        ring = self.history.rings[segment["probe_id"]]
        for key in list(ring.projected):
            if key[1] == sid:
                ring.remove_projection(key)
        ring.trim()
        del self.segments[sid]
        pid = segment["probe_id"]
        if self.active_segments.get(pid) == sid:
            self.active_segments.pop(pid)
            self.bases.pop(pid, None)
            self.basis_starts.pop(pid, None)
        if self.selected_segment == sid:
            self.selected_segment = self.active_segments.get(pid)
        self.reconfigure(self.config)

    def pca_snapshot(self, count, axes):
        selected = self.selection()
        ring = self.history.rings[self.selected_probe]
        frames = ring.tail(min(512, count), raw=True, before=selected.sequence if selected else None)
        if len(frames) <= axes:
            raise ValueError("PCA requiere mas vectores que ejes")
        d = ring.descriptor.dimension
        peak = pca_known_peak(len(frames), d, axes, sum(len(f.payload)+header_cost(f.context) for f in frames))
        self.work.acquire("PCA (workspace LAPACK externo no incluido)", peak)
        try:
            plan_memory(self.probes.values(), self.config, basis_bytes=self.basis_bytes+d*(axes+2)*8+16384)
            return tuple(f.observation() for f in frames)
        except Exception:
            self.work.release()
            raise

    def preview_config(self, config):
        if (config.queue_capacity, config.max_sample_bytes) != (self.config.queue_capacity, self.config.max_sample_bytes):
            raise ValueError("Cambiar transporte requiere una nueva sesion; los slots ya estan asignados")
        if config.max_segments < len(self.segments):
            raise ValueError("Retirar segmentos antes de reducir su limite")
        plan = plan_memory(self.probes.values(), config, basis_bytes=self.basis_bytes)
        if self.work.active and config.work_bytes < self.work.used:
            raise ValueError("La nueva reserva no admite el trabajo activo")
        return plan, self.history.impact(plan)

    def reconfigure(self, config):
        if self.work.active:
            raise ValueError("Esperar al trabajo en curso antes de reconfigurar")
        plan, impact = self.preview_config(config)
        self.history.reconfigure(plan)
        self.config, self.plan = config, plan
        self.work.capacity = config.work_bytes
        self.revision += 1
        return impact

    def select_probe(self, probe_id):
        if probe_id not in self.probes:
            raise ValueError("Sonda desconocida")
        self.live()
        self.selected_probe = probe_id
        self.selected_segment = self.active_segments.get(probe_id)

    def navigation_samples(self, limit=512):
        ring = self.history.rings.get(self.selected_probe)
        frames = (list(ring.frames.values()) if limit is None else ring.tail(limit)) if ring else []
        if self.frozen is not None and all(f.sequence != self.frozen.sequence for f in frames):
            frames.append(self.frozen)
        return sorted(frames, key=lambda f: f.sequence)

    def viewport_frames(self, limit=128):
        ring = self.history.rings.get(self.selected_probe)
        selected = self.selection()
        frames = ring.tail(limit, before=selected.sequence if selected else None) if ring else []
        if self.frozen and all(f.sequence != self.frozen.sequence for f in frames):
            frames.append(self.frozen)
        return frames[-limit:]

    def freeze(self, index=None, limit=128):
        frames = self.navigation_samples()
        if frames:
            self.frozen = frames[index if index is not None else -1].pin()

    def freeze_sequence(self, sequence, limit=128):
        ring = self.history.rings.get(self.selected_probe)
        frame = ring.frames.get(sequence) if ring else None
        if frame is None:
            if self.frozen and self.frozen.sequence == sequence:
                return
            raise ValueError("Captura ausente: ya no esta retenida")
        self.frozen = frame.pin()
        if self.selected_segment not in frame.projections and frame.projections:
            self.selected_segment = next(reversed(frame.projections))

    def live(self):
        self.frozen = None
        self.selected_segment = self.active_segments.get(self.selected_probe)

    def resize_history(self, budget):
        self.reconfigure(replace(self.config, history_bytes=budget))
