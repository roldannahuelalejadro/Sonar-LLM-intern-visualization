import numpy as np


def consecutive(previous, current):
    return (previous is not None and previous.descriptor.compatible(current.descriptor)
            and current.sequence == previous.sequence + 1
            and current.context.get("stream_id") == previous.context.get("stream_id"))


def difference(current, reference, indices=None):
    if not current.descriptor.compatible(reference.descriptor):
        raise ValueError("Referencia incompatible: descriptor/space_id distintos")
    left, right = current.values, reference.values
    if indices is not None:
        left, right = left[indices], right[indices]
    return left.astype(np.float64) - right


def values_for(current, mode="raw", reference=None, previous=None, indices=None):
    if mode == "raw":
        return current.values if indices is None else current.values[indices]
    if mode == "reference_delta":
        return None if reference is None else difference(current, reference, indices)
    if mode == "previous_delta":
        return difference(current, previous, indices) if consecutive(previous, current) else None
    raise ValueError(f"Modo no soportado: {mode}")


def magnitude(values):
    vector = np.asarray(values, dtype=np.float64)
    norm = float(np.linalg.norm(vector))
    return norm, norm / np.sqrt(vector.size)
