"""Read-only display calculations; missing vectors are never reconstructed."""
import numpy as np
from .reference import consecutive, values_for


MODE_NAMES = {"raw": "Activacion original", "reference_delta": "Diferencia con referencia",
              "previous_delta": "Cambio entre capturas consecutivas"}


def vector_values(frame, mode="raw", reference=None, previous=None, indices=None):
    current = frame.observation() if frame is not None else None
    prior = previous.observation() if previous is not None else None
    if current is None:
        return None
    if reference is not None and not current.descriptor.compatible(reference.descriptor):
        reference = None
    return values_for(current, mode, reference, prior, indices)


def unavailable_reason(frame, mode, reference=None, previous=None):
    if frame is None:
        return "Sin captura"
    if frame.payload is None:
        return "El vector de esta captura ya no esta conservado"
    if mode == "reference_delta":
        if reference is None or not frame.descriptor.compatible(reference.descriptor):
            return "Falta una referencia compatible; fijar una o cambiar de modo"
    if mode == "previous_delta":
        if not consecutive(previous, frame):
            return "Cambio no disponible: falta la captura consecutiva de la misma serie"
        if previous.payload is None:
            return "Cambio completo no disponible: el vector anterior ya no esta conservado"
    return ""


def projected_values(frame, basis):
    if frame is None or basis is None:
        return None
    basis.validate_probe(frame.descriptor)
    payload = frame.projections.get(basis.basis_id)
    if payload is not None:
        return np.frombuffer(payload, '<f4').astype(float)
    if frame.payload is not None:
        try:
            return basis.project(frame.observation().values)
        except ValueError:
            return None
    return None


def projected_series(frames, basis, mode="raw", reference=None, previous=None):
    """Subtract positions in ONE affine basis, never center a difference again."""
    result = np.full((len(frames), len(basis.axis_names)), np.nan)
    anchor = None
    if reference is not None and frames and frames[0].descriptor.compatible(reference.descriptor):
        basis.validate_probe(reference.descriptor)
        try:
            anchor = basis.project(reference.values)
        except ValueError:
            anchor = None
    prior_z = projected_values(previous, basis)
    for i, frame in enumerate(frames):
        z = projected_values(frame, basis)
        if z is not None:
            if mode == "raw":
                result[i] = z
            elif mode == "reference_delta" and anchor is not None:
                result[i] = z - anchor
            elif mode == "previous_delta" and prior_z is not None and consecutive(previous, frame):
                result[i] = z - prior_z
        previous, prior_z = frame, z
    return result


def component_series(frames, indices, mode, reference=None, previous=None):
    result = np.full((len(frames), len(indices)), np.nan)
    for i, frame in enumerate(frames):
        values = vector_values(frame, mode, reference, previous, indices)
        if values is not None:
            result[i] = values
        previous = frame
    return result


def change_series(frames, space="full", basis=None, previous=None):
    result = np.full(len(frames), np.nan)
    if space == "projected":
        if basis is not None:
            delta = projected_series(frames, basis, "previous_delta", previous=previous)
            result = np.linalg.norm(delta, axis=1)
        return result
    for i, frame in enumerate(frames):
        delta = vector_values(frame, "previous_delta", previous=previous)
        if delta is not None:
            result[i] = np.linalg.norm(delta)
        previous = frame
    return result
