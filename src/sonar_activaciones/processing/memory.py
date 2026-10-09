"""Conservative ownership allowances, not a process-RSS limiter.

Quotas cover payloads AND Python bookkeeping. Reservations are unavailable to
histories even while empty. Shared transport is charged once across processes.
Opaque Qt/BLAS/allocator memory remains outside this managed-data contract.
"""

from dataclasses import dataclass
import math

from ..contracts import MIB, MAX_METADATA_BYTES, json_bytes


def header_cost(context):
    # Includes frame, two ring indexes, dict capacity, scalar/tuple/string owners.
    return 4096 + 16 * len(json_bytes(dict(context)))


def raw_cost(dimension):
    return dimension * 4 + 256


def projected_cost(axes):
    return axes * 4 + 512


@dataclass(frozen=True)
class BudgetPlan:
    total: int
    reserves: dict
    recent: dict
    projected: dict
    legacy: bool = False

    @property
    def reserved(self):
        return sum(self.reserves.values())

    @property
    def committed(self):
        return self.reserved + sum(self.recent.values()) + sum(self.projected.values())

    def capacities(self, probes, axes=2):
        return {p.probe_id: {
            "recent_approx": self.recent[p.probe_id] // (raw_cost(p.dimension) + header_cost({})),
            "projected_approx": self.projected[p.probe_id] // (projected_cost(axes) + header_cost({})),
        } for p in probes}


def _divide(total, ids, weights):
    if not ids:
        return {}
    result = {key: int(total * w / sum(weights)) for key, w in zip(ids, weights)}
    result[ids[-1]] += total - sum(result.values())
    return result


def plan_memory(probes, config, *, basis_bytes=0):
    probes = tuple(probes)
    ids = [p.probe_id for p in probes]
    weights = config.probe_weights or (1,) * len(ids)
    if len(weights) != len(ids):
        raise ValueError("Se requiere un peso por sonda declarada")
    if weights and (not math.isfinite(sum(weights)) or min(weights)/sum(weights) < 1e-12):
        raise ValueError("Pesos con rango excesivo; usar proporciones finitas moderadas")
    d = max((p.dimension for p in probes), default=0)
    max_frame = raw_cost(d) + header_cost({"_": "x" * MAX_METADATA_BYTES}) + 32 * projected_cost(32)
    reserves = {
        "transport": config.queue_capacity * (config.max_sample_bytes + 4) + 16384,
        "transport_copies": 6 * config.max_sample_bytes,
        "descriptors_events": 65536 + sum(8192 + 16*len(json_bytes(p.to_dict())) for p in probes),
        "reference_selection": 2 * max_frame,
        "visual_processing": 512*1024 + 64*d,
        "work": config.work_bytes,
        "bases": basis_bytes,
    }
    reserved = sum(reserves.values())
    fraction = 1. if config.retention_mode == "detail" else config.recent_fraction
    legacy = config.history_bytes is not None
    # A legacy quota retains its old meaning; no silent global reinterpretation.
    remainder = math.ceil(config.history_bytes / fraction) if legacy else config.data_budget_bytes-reserved
    total = reserved+remainder if legacy else config.data_budget_bytes
    if total > 2*1024*MIB:
        raise ValueError("La traduccion legada supera 2 GiB; reducir cuota o ajustar reparto")
    recent_total = config.history_bytes if legacy else int(max(0, remainder)*fraction)
    recent = _divide(recent_total, ids, weights)
    projected = _divide(max(0, remainder-recent_total), ids, weights)
    minimum_remainder = 0
    for p, weight in zip(probes, weights):
        r = raw_cost(p.dimension)+header_cost({})
        z = projected_cost(2)+header_cost({})
        minimum_remainder = max(minimum_remainder, math.ceil(r*sum(weights)/weight/fraction))
        if fraction < 1:
            minimum_remainder = max(minimum_remainder, math.ceil(z*sum(weights)/weight/(1-fraction)))
    minimum = reserved + minimum_remainder + len(ids)*2
    if remainder < minimum_remainder:
        raise ValueError(f"Presupuesto insuficiente; minimo calculado {minimum} bytes ({minimum/MIB:.3f} MiB). "
                         "Reducir transporte/trabajo o aumentar presupuesto.")
    plan = BudgetPlan(total, reserves, recent, projected, legacy)
    assert plan.committed <= plan.total
    return plan


class WorkAdmission:
    """Only one potentially allocating operation at a time."""
    def __init__(self, capacity):
        self.capacity = capacity
        self.active = None
        self.used = 0

    def acquire(self, name, known_bytes):
        if self.active is not None:
            raise ValueError(f"Trabajo en curso: {self.active}")
        if known_bytes > self.capacity:
            raise ValueError(f"{name}: requiere {known_bytes/MIB:.3f} MiB de trabajo; "
                             f"reserva {self.capacity/MIB:.3f} MiB. Reducir ventana o ampliar reserva.")
        self.active, self.used = name, known_bytes

    def release(self):
        self.active, self.used = None, 0


def pca_known_peak(n, d, k, snapshot_bytes):
    rank = min(n, d)
    # Pinned float32 owners, centered float64 input, thin-SVD outputs, bases,
    # immutable conversion copies and result. No d*d covariance.
    return snapshot_bytes + 2*n*d*8 + (n*rank + rank*d + rank)*8 + 4*d*(k+2)*8 + 65536


def rss_bytes():
    """Diagnostic current RSS (Windows/Linux); excludes other processes."""
    import os
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize
    elif os.path.exists("/proc/self/statm"):
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    return None
