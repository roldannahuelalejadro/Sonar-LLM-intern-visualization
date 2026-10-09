from dataclasses import dataclass, field
import math

import numpy as np

from ..contracts import Observation, ProbeDescriptor, MAX_PROBES, json_bytes
from ..processing.projection import DirectionBasis
from .numeric import read_pair, write_pair

MAX_CAPTURE_BYTES = 128*1024**2
MAX_JSON_BYTES = 16*1024**2
MODES = ("raw", "reference_delta", "previous_delta")


@dataclass(frozen=True)
class Capture:
    probes: tuple
    samples: tuple
    references: dict = field(default_factory=dict)
    bases: dict = field(default_factory=dict)
    basis_starts: dict = field(default_factory=dict)
    snapshot: Observation | None = None
    view: dict = field(default_factory=dict)
    counters: dict = field(default_factory=dict)
    history_evicted: int = 0


def _validate(capture):
    probes = {p.probe_id: p for p in capture.probes}
    if not 1 <= len(probes) <= MAX_PROBES or len(probes) != len(capture.probes):
        raise ValueError("Captura requiere sondas unicas, entre 1 y 64")
    if not capture.samples:
        raise ValueError("No hay muestras para guardar")
    sequences, times = {}, {}
    for sample in capture.samples:
        if sample.descriptor != probes.get(sample.probe_id):
            raise ValueError("Muestra incompatible con descriptor")
        if sample.sequence <= sequences.get(sample.probe_id, -1):
            raise ValueError("Secuencia duplicada o no creciente en captura")
        if sample.captured_at < times.get(sample.probe_id, 0):
            raise ValueError("Tiempos de captura no monotonicos")
        sequences[sample.probe_id] = sample.sequence
        times[sample.probe_id] = sample.captured_at
    if sum(s.accounted_bytes for s in capture.samples) > MAX_CAPTURE_BYTES:
        raise ValueError("Captura supera 128 MiB contabilizados; reducir ventana antes de guardar")
    for key, ref in capture.references.items():
        if ref.descriptor != probes.get(key):
            raise ValueError("Referencia incompatible en captura")
    if capture.snapshot is not None:
        snap = capture.snapshot
        if snap.descriptor != probes.get(snap.probe_id):
            raise ValueError("Instantanea incompatible")
        if not any(s == snap for s in capture.samples):
            raise ValueError("Instantanea debe estar incluida en la ventana")
    for key, basis in capture.bases.items():
        if key not in probes:
            raise ValueError("Base de sonda no declarada")
        basis.validate_probe(probes[key])
    if sum(b.nbytes for b in capture.bases.values()) > 32*1024**2:
        raise ValueError("Bases de captura superan 32 MiB")
    if set(capture.basis_starts) - set(capture.bases):
        raise ValueError("Inicio de base sin base")
    if any(type(seq) is not int or seq < 0 for seq in capture.basis_starts.values()):
        raise ValueError("Secuencia inicial de base invalida")
    view = capture.view
    if view.get("mode", "raw") not in MODES or view.get("selected_probe", next(iter(probes))) not in probes:
        raise ValueError("Estado visual incompatible")
    limit = view.get("visual_limit", 1.)
    if not isinstance(limit, (int, float)) or not math.isfinite(limit) or not 1e-9 <= limit <= 1e30:
        raise ValueError("Escala visual invalida")
    if len(json_bytes(view)) > 4096:
        raise ValueError("Estado visual demasiado grande")
    dimension = probes[view.get("selected_probe", next(iter(probes)))].dimension
    for key, low, high in (("component", 0, dimension-1), ("page", 0, (dimension-1)//256), ("window", 4, 512)):
        if key in view and (type(view[key]) is not int or not low <= view[key] <= high):
            raise ValueError(f"Estado visual invalido: {key}")
    if view.get("axis", "sequence") not in ("sequence", "time", "token"):
        raise ValueError("Eje de captura invalido")
    if "trace_indices" in view:
        trace = view["trace_indices"]
        if not isinstance(trace, list) or not 1 <= len(trace) <= 3 or any(type(i) is not int or not 0 <= i < dimension for i in trace):
            raise ValueError("Indices de traza invalidos")
    if len(capture.counters) > 32 or any(not isinstance(k, str) or len(k)>64 or type(v) is not int or not 0 <= v < 2**64 for k, v in capture.counters.items()):
        raise ValueError("Contadores invalidos")
    if type(capture.history_evicted) is not int or capture.history_evicted < 0:
        raise ValueError("Contador de eviccion invalido")


def save_capture(path, capture):
    _validate(capture)
    arrays, series, references, bases = {}, [], {}, {}
    for index, probe in enumerate(capture.probes):
        key = f"p{index}"
        samples = [s for s in capture.samples if s.probe_id == probe.probe_id]
        arrays[f"{key}_values"] = np.array([s.values for s in samples], dtype="<f4").reshape((-1, probe.dimension))
        series.append({"key": key, "descriptor": probe.to_dict(), "readings": [
            {"sequence": s.sequence, "captured_at": s.captured_at, "context": dict(s.context)} for s in samples],
            "gaps": [[a.sequence, b.sequence] for a, b in zip(samples, samples[1:]) if b.sequence != a.sequence+1],
            "truncated_start": bool(samples and samples[0].sequence > 0)})
        reference = capture.references.get(probe.probe_id)
        if reference is not None:
            arrays[f"{key}_reference"] = reference.values
            references[key] = {"sequence": reference.sequence, "captured_at": reference.captured_at,
                               "context": dict(reference.context)}
        basis = capture.bases.get(probe.probe_id)
        if basis is not None:
            bases[key] = {"metadata": basis.metadata(), "start_sequence": capture.basis_starts.get(probe.probe_id, 0)}
            for name in ("W", "center", "scale"):
                arrays[f"{key}_basis_{name}"] = getattr(basis, name)
    snapshot = None if capture.snapshot is None else {"probe_id": capture.snapshot.probe_id, "sequence": capture.snapshot.sequence}
    document = {"format": "sonar-capture", "schema_version": 1, "partial": True,
                "extent": "retained_window", "series": series, "references": references, "bases": bases,
                "snapshot": snapshot, "view": capture.view, "counters": capture.counters,
                "history_evicted": capture.history_evicted,
                "clock": "local_monotonic_seconds; replay uses relative intervals only"}
    if len(json_bytes(document)) > MAX_JSON_BYTES or sum(a.nbytes+256 for a in arrays.values()) > MAX_CAPTURE_BYTES:
        raise ValueError("Captura excede los limites del formato (128 MiB NPZ / 16 MiB JSON)")
    return write_pair(path, document, arrays)


def load_capture(path, *, admission=None, max_json_bytes=MAX_JSON_BYTES):
    document, arrays = read_pair(path, max_bytes=MAX_CAPTURE_BYTES, max_json_bytes=max_json_bytes, admission=admission)
    return decode_capture(document, arrays)


def decode_capture(document, arrays):
    try:
        if (document.get("format") != "sonar-capture" or document.get("schema_version") != 1
                or document.get("partial") is not True or document.get("extent") != "retained_window"):
            raise ValueError("Formato o version de captura no admitido")
        series = document["series"]
        if not isinstance(series, list) or not 1 <= len(series) <= MAX_PROBES:
            raise ValueError("Series fuera de limite")
        probes, samples, references, bases, starts = [], [], {}, {}, {}
        expected_arrays = set()
        accounted = 0
        for index, entry in enumerate(series):
            key = f"p{index}"
            if entry["key"] != key:
                raise ValueError("Clave de serie invalida")
            probe = ProbeDescriptor.from_dict(entry["descriptor"])
            probes.append(probe)
            readings = entry["readings"]
            values = arrays[f"{key}_values"]
            expected_arrays.add(f"{key}_values")
            if values.dtype != np.dtype("<f4") or values.shape != (len(readings), probe.dimension):
                raise ValueError("Valores float32 no coinciden con las lecturas")
            for row, record in enumerate(readings):
                sample = Observation.create(probe, values[row], record["sequence"], record["context"],
                                            record["captured_at"], max_bytes=16*1024**2)
                accounted += sample.accounted_bytes
                if accounted > MAX_CAPTURE_BYTES:
                    raise ValueError("Captura supera el presupuesto de objetos")
                samples.append(sample)
            record = document["references"].get(key)
            if record is not None:
                references[probe.probe_id] = Observation.create(probe, arrays[f"{key}_reference"], record["sequence"],
                                                               record["context"], record["captured_at"], max_bytes=16*1024**2)
                expected_arrays.add(f"{key}_reference")
            record = document["bases"].get(key)
            if record is not None:
                numeric = {name: arrays[f"{key}_basis_{name}"] for name in ("W", "center", "scale")}
                expected_arrays.update(f"{key}_basis_{name}" for name in numeric)
                bases[probe.probe_id] = DirectionBasis.from_data(record["metadata"], numeric)
                starts[probe.probe_id] = record["start_sequence"]
        known_keys = {f"p{i}" for i in range(len(series))}
        if set(document["references"]) - known_keys or set(document["bases"]) - known_keys or set(arrays) != expected_arrays:
            raise ValueError("Arrays o metadata sin serie asociada")
        # Validate each series before merging by its capture time.
        capture = Capture(tuple(probes), tuple(samples), references, bases, starts,
                          view=document["view"], counters=document["counters"], history_evicted=document["history_evicted"])
        _validate(capture)
        samples.sort(key=lambda s: (s.captured_at, s.probe_id, s.sequence))
        snapshot = document["snapshot"]
        if snapshot is not None:
            snapshot = next((s for s in samples if s.probe_id == snapshot["probe_id"] and s.sequence == snapshot["sequence"]), None)
            if snapshot is None:
                raise ValueError("Instantanea no encontrada en captura")
        return Capture(tuple(probes), tuple(samples), references, bases, starts, snapshot,
                       document["view"], document["counters"], document["history_evicted"])
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError(f"Captura invalida: {exc}") from exc
