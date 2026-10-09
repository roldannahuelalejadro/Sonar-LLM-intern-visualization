"""Versioned, bounded, immutable CPU contracts (no GUI or framework imports)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import math
import struct
import time

import numpy as np

SCHEMA_VERSION = 1
MIB = 1024**2
MAX_METADATA_BYTES = 4096
MAX_PROBES = 64


def json_bytes(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")


def bounded_text(value, name, maximum=256, empty=False):
    if not isinstance(value, str) or (not value and not empty) or len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{name}: texto requerido, maximo {maximum} bytes UTF-8")
    return value


@dataclass(frozen=True, slots=True)
class Metadata(Mapping):
    entries: tuple = ()

    def __iter__(self):
        return (key for key, _ in self.entries)

    def __len__(self):
        return len(self.entries)

    def __getitem__(self, key):
        for name, value in self.entries:
            if name == key:
                return value
        raise KeyError(key)

    @classmethod
    def parse(cls, value):
        if not isinstance(value, Mapping) or len(value) > 32:
            raise ValueError("metadata/context: se espera un mapping de hasta 32 campos escalares")
        items = []
        for key, item in value.items():
            bounded_text(key, "metadata key", 64)
            if type(item) not in (str, int, float, bool, type(None)):
                raise ValueError(f"{key}: metadata solo acepta escalares JSON")
            if isinstance(item, str):
                bounded_text(item, key, 2048, empty=True)
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError(f"{key}: valor no finito")
            if type(item) is int and abs(item) > 2**63 - 1:
                raise ValueError(f"{key}: entero fuera de int64")
            items.append((key, item))
        if len(json_bytes(dict(items))) > MAX_METADATA_BYTES:
            raise ValueError("metadata/context supera 4096 bytes")
        return cls(tuple(sorted(items)))


@dataclass(frozen=True, slots=True)
class ProbeDescriptor:
    probe_id: str
    name: str
    source_id: str
    capture_point: str
    dimension: int
    selection_rule: str
    space_id: str
    schema_version: int = SCHEMA_VERSION
    metadata: Mapping = field(default_factory=dict)

    def __post_init__(self):
        for key in ("probe_id", "name", "source_id", "capture_point", "selection_rule", "space_id"):
            bounded_text(getattr(self, key), key)
        if type(self.dimension) is not int or not 1 <= self.dimension <= 4 * MIB:
            raise ValueError("dimension debe estar entre 1 y 4194304")
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError("schema_version no soportada")
        object.__setattr__(self, "metadata", Metadata.parse(self.metadata))

    def to_dict(self):
        return {key: dict(self.metadata) if key == "metadata" else getattr(self, key)
                for key in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("Descriptor invalido")
        try:
            return cls(**value)
        except TypeError as exc:
            raise ValueError(f"Descriptor invalido: {exc}") from exc

    def compatible(self, other):
        # Descriptor changes start a new series, even if dimensions happen to match.
        return self == other


@dataclass(frozen=True, slots=True)
class Observation:
    descriptor: ProbeDescriptor
    sequence: int
    captured_at: float
    payload: bytes
    context: Metadata

    def __post_init__(self):
        if not isinstance(self.descriptor, ProbeDescriptor):
            raise ValueError("Falta ProbeDescriptor")
        if type(self.sequence) is not int or not 0 <= self.sequence < 2**63:
            raise ValueError("sequence debe ser entero no negativo int64")
        if not isinstance(self.captured_at, (int, float)) or not math.isfinite(self.captured_at) or self.captured_at < 0:
            raise ValueError("captured_at debe ser un tiempo monotonic finito no negativo")
        if type(self.payload) is not bytes or len(self.payload) != self.descriptor.dimension * 4:
            raise ValueError("payload float32 incompatible con dimension")
        if not np.isfinite(self.values).all():
            raise ValueError("La muestra contiene NaN o infinito")
        validated = Metadata.parse(self.context)
        if not isinstance(self.context, Metadata) or self.context.entries != validated.entries:
            object.__setattr__(self, "context", validated)
        stream = self.context.get("stream_id")
        if stream is not None and not isinstance(stream, str):
            raise ValueError("stream_id debe ser texto")
        for key in ("processed_position", "predicted_position"):
            value = self.context.get(key)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{key} debe ser entero no negativo")

    @property
    def probe_id(self):
        return self.descriptor.probe_id

    @property
    def values(self):
        return np.frombuffer(self.payload, dtype="<f4")

    @property
    def accounted_bytes(self):
        # Conservative allowance for Python objects, UTF-32 strings and deque slots.
        return len(self.payload) + 2048 + 4 * len(json_bytes(self.header()))

    def header(self):
        return {"descriptor": self.descriptor.to_dict(), "sequence": self.sequence,
                "captured_at": self.captured_at, "context": dict(self.context)}

    def pack(self):
        header = json_bytes(self.header())
        return struct.pack("<I", len(header)) + header + self.payload

    @classmethod
    def unpack(cls, packet):
        if len(packet) < 4:
            raise ValueError("Paquete incompleto")
        size = struct.unpack("<I", packet[:4])[0]
        if size > 32 * 1024 or size > len(packet) - 4:
            raise ValueError("Cabecera fuera de limite")
        header = json.loads(packet[4:4+size])
        return cls(ProbeDescriptor.from_dict(header["descriptor"]), header["sequence"],
                   header["captured_at"], packet[4+size:], Metadata.parse(header["context"]))

    @classmethod
    def create(cls, descriptor, values, sequence, context=None, captured_at=None, max_bytes=MIB):
        if not isinstance(values, np.ndarray) or values.ndim != 1:
            raise ValueError("values debe ser un numpy.ndarray CPU unidimensional")
        if values.size != descriptor.dimension or values.dtype.kind not in "fiu":
            raise ValueError("values: dimension incompatible o dtype no real numerico")
        if values.size * 4 + 2048 > max_bytes:
            raise ValueError("Muestra supera max_sample_bytes")
        with np.errstate(over="ignore", invalid="ignore"):
            payload = values.astype("<f4", copy=False).tobytes()
        sample = cls(descriptor, sequence, time.monotonic() if captured_at is None else captured_at,
                     payload, Metadata.parse({} if context is None else context))
        if sample.accounted_bytes > max_bytes:
            raise ValueError("Muestra y metadata superan max_sample_bytes")
        return sample


@dataclass(frozen=True, slots=True)
class MonitorConfig:
    render_hz: float = 5.0
    queue_capacity: int = 16
    max_sample_bytes: int = MIB
    history_bytes: int | None = None
    capture_hz: float = 0.0
    max_receive_per_tick: int = 32
    receive_budget_ms: float = 8.0
    visual_limit: float = 1.0
    data_budget_bytes: int = 64 * MIB
    recent_fraction: float = .7
    retention_mode: str = "combined"
    work_bytes: int = 8 * MIB
    max_segments: int = 8
    probe_weights: tuple = ()
    config_version: int = 2

    def __post_init__(self):
        for key, low, high in (("queue_capacity", 1, 256), ("max_sample_bytes", 4096, 16*MIB),
                               ("data_budget_bytes", 65536, 2*1024*MIB),
                               ("work_bytes", 0, 512*MIB), ("max_segments", 1, 32),
                               ("max_receive_per_tick", 1, 256)):
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key}: fuera del intervalo [{low}, {high}]")
        for key, low, high in (("render_hz", 0.5, 60), ("capture_hz", 0, 100000),
                               ("receive_budget_ms", 0.1, 50), ("visual_limit", 1e-9, 1e30),
                               ("recent_fraction", .05, .95)):
            value = getattr(self, key)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{key}: fuera del intervalo [{low}, {high}]")
        if self.queue_capacity * self.max_sample_bytes > 256*MIB:
            raise ValueError("La reserva total de cola no puede superar 256 MiB")
        if self.history_bytes is not None and (type(self.history_bytes) is not int or not 4096 <= self.history_bytes <= 512*MIB):
            raise ValueError("history_bytes: intervalo legado [4096, 536870912]")
        if self.retention_mode not in ("detail", "combined") or self.config_version != 2:
            raise ValueError("Modo de retencion o version de configuracion invalida")
        if (not isinstance(self.probe_weights, tuple) or len(self.probe_weights) > MAX_PROBES
                or any(not isinstance(w, (int, float)) or not math.isfinite(w) or w <= 0 for w in self.probe_weights)):
            raise ValueError("probe_weights: tupla de pesos positivos finitos")


def validate_probes(probes, config):
    probes = tuple(probes)
    if not 1 <= len(probes) <= MAX_PROBES or any(not isinstance(p, ProbeDescriptor) for p in probes):
        raise ValueError("Declarar entre 1 y 64 sondas validas")
    if len({p.probe_id for p in probes}) != len(probes):
        raise ValueError("probe_id duplicado")
    for probe in probes:
        estimated = probe.dimension * 4 + 2048 + 4 * len(json_bytes(probe.to_dict())) + 512
        if estimated > min(config.max_sample_bytes, config.history_bytes or config.data_budget_bytes):
            raise ValueError(f"{probe.probe_id}: dimension/descriptor exceden los limites")
    from .processing.memory import plan_memory
    plan_memory(probes, config)
    return probes

