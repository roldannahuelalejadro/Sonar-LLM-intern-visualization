import numpy as np
from .reference import consecutive, values_for


def coordinates(samples, axis="sequence"):
    if not samples:
        return np.array([], dtype=float)
    if axis == "sequence":
        result = np.array([s.sequence for s in samples], dtype=float)
    elif axis == "time":
        result = np.array([s.captured_at - samples[0].captured_at for s in samples])
    elif axis == "token":
        positions = [s.context.get("processed_position") for s in samples]
        if any(type(p) is not int for p in positions):
            raise ValueError("No hay posiciones procesadas para todas las lecturas")
        if len({s.context.get("stream_id") for s in samples}) != 1:
            raise ValueError("Eje token requiere un unico stream")
        result = np.array(positions, dtype=float)
    else:
        raise ValueError("Eje temporal desconocido")
    if len(result) > 1 and np.any(np.diff(result) <= 0):
        raise ValueError("Eje no estrictamente creciente en esta ventana")
    return result


def selected_history(samples, indices, mode, reference=None):
    result = np.full((len(samples), len(indices)), np.nan)
    for i, s in enumerate(samples):
        values = values_for(s, mode, reference, samples[i-1] if i else None, indices)
        if values is not None:
            result[i] = values
    return result


def broken_trace(samples, x, values):
    xs, ys = [], []
    for i, sample in enumerate(samples):
        if i and not consecutive(samples[i-1], sample):
            xs.append(np.nan)
            ys.append(np.nan)
        xs.append(x[i])
        ys.append(values[i])
    return np.asarray(xs), np.asarray(ys)


def mesh_columns(samples, x, values, axis):
    """Actual coordinates, with blank intervals for missing sequence positions."""
    if not len(x):
        return np.array([0, 1]), np.full((1, values.shape[1]), np.nan)
    width = 1.0 if axis != "time" or len(x) < 2 else float(np.min(np.diff(x))) * .9
    edges = [x[0] - width/2]
    rows = []
    for i, coordinate in enumerate(x):
        left, right = coordinate-width/2, coordinate+width/2
        if left > edges[-1] + width*1e-8:
            rows.append(np.full(values.shape[1], np.nan))
            edges.append(left)
        rows.append(values[i])
        edges.append(right)
    return np.asarray(edges), np.asarray(rows)

