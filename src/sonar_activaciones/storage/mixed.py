"""Version 2 partial captures. Import/export admitted before numeric allocation."""
from collections import Counter
from pathlib import Path
import math
import numpy as np

from ..contracts import ProbeDescriptor, Metadata, Observation, bounded_text, json_bytes
from ..processing.combined import Frame
from ..processing.memory import header_cost, raw_cost, projected_cost
from ..processing.projection import DirectionBasis
from .numeric import read_pair, write_pair
from .capture import decode_capture


def _record(frame):
    return {"sequence": frame.sequence, "captured_at": frame.captured_at, "context": dict(frame.context)}


def validate_view(view, state):
    if not isinstance(view, dict) or len(json_bytes(view)) > 4096:
        raise ValueError('Estado visual invalido o fuera de limite')
    if view.get('mode', 'raw') not in ('raw', 'reference_delta', 'previous_delta'):
        raise ValueError('Modo de captura invalido')
    if view.get('axis', 'sequence') not in ('sequence', 'time', 'token'):
        raise ValueError('Eje de captura invalido')
    if view.get('evolution', 'change') not in ('change', 'traces', 'heat') or view.get('change_space', 'full') not in ('full', 'projected'):
        raise ValueError('Modo de historial invalido')
    d = state.probes[state.selected_probe].dimension
    for key, lo, hi in (('component', 0, d-1), ('page', 0, (d-1)//256), ('window', 4, 512)):
        if key in view and (type(view[key]) is not int or not lo <= view[key] <= hi):
            raise ValueError(f'Estado visual invalido: {key}')
    for key, lo, hi, length in (('trace_indices', 0, d-1, None), ('map_axes', 0, 31, 2)):
        if key in view:
            items = view[key]
            if not isinstance(items, list) or not 1 <= len(items) <= 3 or (length and len(items) != length) or any(type(i) is not int or not lo <= i <= hi for i in items):
                raise ValueError(f'Selectores invalidos: {key}')
    limit = view.get('visual_limit', 1.)
    if not isinstance(limit, (int, float)) or not math.isfinite(limit) or not 1e-9 <= limit <= 1e30:
        raise ValueError('Escala visual invalida')


def save_state(path, state, *, limit=128, view=None, counters=None):
    if not 1 <= limit <= 512:
        raise ValueError("Ventana de exportacion: 1..512 capturas por sonda")
    # Lists contain references only. Numeric snapshots/JSON are allocated after admission.
    selected = state.selection()
    frames = {pid: ring.tail(limit) for pid, ring in state.history.rings.items()}
    if state.frozen is not None:
        group = frames[state.frozen.probe_id]
        frames[state.frozen.probe_id] = sorted([f for f in group if f.sequence != state.frozen.sequence] + [state.frozen],
                                              key=lambda f: f.sequence)
    if not any(frames.values()):
        raise ValueError("No hay capturas retenidas")
    peak = 1024**2 + 2*state.basis_bytes
    for group in frames.values():
        peak += sum(2*(len(f.payload or b'')+sum(map(len, f.projections.values())))+3*header_cost(f.context) for f in group)
    peak += sum(2*s.accounted_bytes for s in state.references.values())
    state.work.acquire("Exportacion parcial", peak)
    try:
        arrays, series, segments = {}, [], []
        for index, (pid, group) in enumerate(frames.items()):
            key = f"p{index}"
            p = state.probes[pid]
            raw = [f for f in group if f.payload is not None]
            rows = {f.sequence: i for i, f in enumerate(raw)}
            arrays[key+"_values"] = np.array([np.frombuffer(f.payload, '<f4') for f in raw], dtype='<f4').reshape(-1, p.dimension)
            entries = []
            for f in group:
                entries.append({**_record(f), "raw_row": rows.get(f.sequence), "availability": f.availability})
            series.append({"key": key, "descriptor": p.to_dict(), "frames": entries,
                           "gaps": [[a.sequence, b.sequence] for a, b in zip(group, group[1:]) if b.sequence != a.sequence+1]})
        for index, (sid, segment) in enumerate(state.segments.items()):
            key = f"b{index}"
            basis = segment["basis"]
            group = [f for f in frames[segment["probe_id"]] if sid in f.projections]
            arrays[key+"_coordinates"] = np.array([np.frombuffer(f.projections[sid], '<f4') for f in group], dtype='<f4').reshape(-1, len(basis.axis_names))
            for name in ("W", "center", "scale"):
                arrays[key+"_"+name] = getattr(basis, name)
            segments.append({"key": key, "probe_id": segment["probe_id"], "start": segment["start"],
                             "metadata": basis.metadata(), "sequences": [f.sequence for f in group],
                             "derived": [sid in f.derived for f in group]})
        refs = []
        for pid, sample in state.references.items():
            arrays["reference"] = sample.values
            refs.append({"probe_id": pid, **_record(sample)})
        document = {"format": "sonar-capture", "schema_version": 2, "partial": True,
                    "extent": "retained_window", "session_id": state.history.session_id,
                    "series": series, "segments": segments, "active_segments": state.active_segments,
                    "references": refs, "snapshot": None if selected is None else [selected.probe_id, selected.sequence],
                    "selected_segment": state.selected_segment, "view": view or {},
                    "counters": counters or {}, "history_counters": dict(state.history.counters),
                    "events": list(state.history.events), "last_sequences": state.last_sequences,
                    "coordinate_dtype": "float32", "clock": "local_monotonic_seconds"}
        return write_pair(path, document, arrays)
    finally:
        state.work.release()


def load_state(path, config, admission, *, choose_reference=None):
    """Existing viewer holds the reservation until the candidate is adopted.

    Declines an oversized window before np.load. Explicitly increase the work
    reserve/budget or export a smaller window, never silently enlarge memory.
    """
    from ..app.state import ViewerState
    capacity = admission.capacity
    chosen_reference = None
    def check(document, shapes, json_size):
        nonlocal chosen_reference
        # Arrays, immutable payload copies, object graph, decode/ZIP/hash buffers.
        count = sum(len(s.get("frames", s.get("readings", []))) for s in document.get("series", []))
        peak = 3*sum(v[2] for v in shapes.values()) + 32*json_size + 8192*count + 1024**2
        admission.acquire("Importacion parcial", peak)
        if document.get('schema_version') == 1 and len(document.get('references', {})) > 1:
            ids = [s['descriptor']['probe_id'] for s in document['series'] if s['key'] in document['references']]
            if choose_reference is None:
                raise ValueError('Captura v1 con varias referencias: elegir una explicitamente al importar')
            chosen_reference = choose_reference(ids)
            if chosen_reference not in ids:
                raise ValueError('Importacion cancelada: no se eligio referencia')
    # Bound the JSON object graph before parsing; arrays have a separate preflight.
    if Path(path).stat().st_size*32 + 1024**2 > capacity:
        raise ValueError("JSON no cabe en reserva de trabajo; ampliar presupuesto/reserva o exportar una ventana menor")
    acquired_before = admission.active
    if acquired_before is not None:
        raise ValueError("Esperar al trabajo en curso antes de importar")
    try:
        document, arrays = read_pair(path, admission=check, max_json_bytes=min(16*1024**2, capacity//32))
        if document.get("format") != "sonar-capture" or document.get("partial") is not True or document.get("extent") != "retained_window":
            raise ValueError("Formato de captura no admitido")
        if document.get("schema_version") == 1:
            old = decode_capture(document, arrays)
            state = ViewerState(old.probes, config)
            for pid, basis in old.bases.items():
                state.install_basis(basis, pid, reproject=False)
                state.segments[basis.basis_id]["start"] = old.basis_starts.get(pid, 0)
            # Legacy files carry vectors, not measured historical coordinates.
            for sample in old.samples:
                state.history.rings[sample.probe_id].add(sample)
                state.last_sequences[sample.probe_id] = sample.sequence
            if state.history.evicted:
                raise ValueError("Ventana antigua excede cuota reciente; ampliar presupuesto o exportar menos capturas")
            state.references = {chosen_reference: old.references[chosen_reference]} if chosen_reference else old.references
            snapshot = old.snapshot or old.samples[-1]
            state.selected_probe = snapshot.probe_id
            state.freeze_sequence(snapshot.sequence)
            validate_view(old.view, state)
            return state, old.view, old.counters
        if document.get("schema_version") != 2:
            raise ValueError("Version de captura no admitida")
        series = document["series"]
        if not isinstance(series, list) or not 1 <= len(series) <= 64:
            raise ValueError("Series fuera de limite")
        probes = [ProbeDescriptor.from_dict(s["descriptor"]) for s in series]
        if len({p.probe_id for p in probes}) != len(probes):
            raise ValueError("Sondas duplicadas")
        state = ViewerState(probes, config)
        state.history.session_id = bounded_text(document["session_id"], "session_id")
        expected = set()
        availability = {}
        for i, (entry, probe) in enumerate(zip(series, probes)):
            key = f"p{i}"
            if entry["key"] != key:
                raise ValueError("Clave de serie invalida")
            values = arrays[key+"_values"]
            expected.add(key+"_values")
            if values.dtype != np.dtype('<f4') or values.ndim != 2 or values.shape[1] != probe.dimension:
                raise ValueError("Vectores incompatibles")
            ring = state.history.rings[probe.probe_id]
            last_seq, last_time, raw_row = -1, -1, 0
            for record in entry["frames"]:
                seq, stamp = record["sequence"], record["captured_at"]
                if type(seq) is not int or not last_seq < seq < 2**63 or not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or stamp < max(0, last_time):
                    raise ValueError("Identidad/tiempo no creciente o invalido")
                payload = None
                row = record["raw_row"]
                if row is not None:
                    if type(row) is not int or row != raw_row or row >= len(values):
                        raise ValueError("Indice de vector invalido")
                    obs = Observation.create(probe, values[row], seq, record["context"], stamp, max_bytes=16*1024**2)
                    payload = obs.payload
                    raw_row += 1
                frame = Frame(probe, seq, stamp, Metadata.parse(record["context"]), payload)
                ring.frames[seq] = frame
                availability[(probe.probe_id, seq)] = record["availability"]
                last_seq, last_time = seq, stamp
            if raw_row != len(values):
                raise ValueError("Vectores sin captura asociada")
        segments = document["segments"]
        if len(segments) > config.max_segments:
            raise ValueError("Demasiados segmentos para esta configuracion")
        for i, entry in enumerate(segments):
            key = f"b{i}"
            if entry["key"] != key or type(entry["start"]) is not int or entry["start"] < 0:
                raise ValueError("Segmento invalido")
            numeric = {name: arrays[key+"_"+name] for name in ("W", "center", "scale")}
            expected.update(key+"_"+name for name in numeric)
            basis = DirectionBasis.from_data(entry["metadata"], numeric)
            pid = entry["probe_id"]
            state.install_basis(basis, pid, reproject=False)
            sid = basis.basis_id
            state.segments[sid]["start"] = entry["start"]
            coords = arrays[key+"_coordinates"]
            expected.add(key+"_coordinates")
            seqs, derived = entry["sequences"], entry["derived"]
            if (coords.dtype != np.dtype('<f4') or coords.shape != (len(seqs), len(basis.axis_names))
                    or len(derived) != len(seqs) or len(set(seqs)) != len(seqs) or not np.isfinite(coords).all()):
                raise ValueError("Coordenadas incompatibles")
            for row, seq in enumerate(seqs):
                if type(derived[row]) is not bool:
                    raise ValueError("Marca derivada invalida")
                frame = state.history.rings[pid].frames[seq]
                frame.projections[sid] = coords[row].tobytes()
                if derived[row]:
                    frame.derived.add(sid)
        for pid, ring in state.history.rings.items():
            for seq, frame in ring.frames.items():
                if frame.availability == "absent" or frame.availability != availability[(pid, seq)]:
                    raise ValueError("Disponibilidad no coincide con los datos")
                if frame.payload is not None:
                    ring.raw[seq] = None
                    ring.raw_bytes += raw_cost(frame.descriptor.dimension) + (0 if frame.projections else header_cost(frame.context))
                if frame.projections:
                    ring.projected_bytes += header_cost(frame.context)
                    for sid, payload in frame.projections.items():
                        ring.projected[(seq, sid)] = None
                        ring.projected_bytes += projected_cost(len(payload)//4)
            if ring.raw_bytes > ring.recent_limit or ring.projected_bytes > ring.projected_limit:
                raise ValueError("Captura supera cuotas: aumentar presupuesto/reparto o exportar ventana menor")
        active = document["active_segments"]
        if any(pid not in state.probes or sid not in state.segments or state.segments[sid]["probe_id"] != pid for pid, sid in active.items()):
            raise ValueError("Segmento activo incompatible")
        state.active_segments = dict(active)
        state.bases = {pid: state.segments[sid]["basis"] for pid, sid in active.items()}
        refs = document["references"]
        if len(refs) > 1:
            raise ValueError("Solo se admite una referencia")
        if refs:
            ref = refs[0]
            p = state.probes[ref["probe_id"]]
            state.references[p.probe_id] = Observation.create(p, arrays["reference"], ref["sequence"], ref["context"], ref["captured_at"], max_bytes=16*1024**2)
            expected.add("reference")
        if set(arrays) != expected:
            raise ValueError("Arrays sin propietario")
        last = document["last_sequences"]
        if set(last)-set(state.probes) or any(type(v) is not int or not 0 <= v < 2**63 for v in last.values()):
            raise ValueError("Secuencias finales invalidas")
        state.last_sequences = last
        counters = document["history_counters"]
        if len(counters) > 32 or any(not isinstance(k, str) or len(k)>64 or type(v) is not int or not 0 <= v < 2**64 for k, v in counters.items()):
            raise ValueError("Contadores invalidos")
        state.history.counters.clear()
        state.history.counters.update(counters)
        if len(json_bytes(document["events"])) > 32768 or len(document["events"]) > 128:
            raise ValueError("Eventos fuera de limite")
        state.history.events.extend(document["events"])
        snapshot = document["snapshot"]
        if snapshot is not None:
            state.select_probe(snapshot[0])
            state.freeze_sequence(snapshot[1])
        sid = document.get("selected_segment")
        if sid is not None and (sid not in state.segments or state.segments[sid]["probe_id"] != state.selected_probe):
            raise ValueError("Segmento seleccionado incompatible")
        state.selected_segment = sid
        validate_view(document['view'], state)
        return state, document["view"], document["counters"]
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(f"Captura mixta invalida: {exc}") from exc
    finally:
        admission.release()
