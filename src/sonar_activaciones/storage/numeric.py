import hashlib
import json
import math
import os
from pathlib import Path
import re
import uuid
import zipfile

import numpy as np

from ..contracts import json_bytes


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_pair(path, document, arrays):
    path = Path(path).with_suffix(".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    identifier = uuid.uuid4().hex
    numeric_path = path.with_name(f"sonar-{identifier}.npz")
    temporary_json = path.with_name(f".{path.name}.{identifier}.tmp")
    for key, array in arrays.items():
        if not re.fullmatch(r"[A-Za-z0-9_]+", key) or array.dtype.kind not in "fiu":
            raise ValueError("Solo arrays numericos sin objetos")
    try:
        with zipfile.ZipFile(numeric_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for key, array in arrays.items():
                if not array.flags.c_contiguous:
                    raise ValueError("Exportacion requiere arrays contiguos; no se copia implicitamente")
                with archive.open(key + ".npy", "w", force_zip64=True) as stream:
                    np.lib.format.write_array_header_2_0(stream, np.lib.format.header_data_from_array_1_0(array))
                    data = memoryview(array).cast("B") if array.size else b""
                    for offset in range(0, len(data), 65536):
                        stream.write(data[offset:offset+65536])
        body = {**document, "arrays_file": numeric_path.name, "arrays_sha256": _digest(numeric_path)}
        temporary_json.write_bytes(json_bytes(body))
        os.replace(temporary_json, path)
    except Exception:
        temporary_json.unlink(missing_ok=True)
        numeric_path.unlink(missing_ok=True)
        raise
    return path


def read_pair(path, *, max_bytes=128*1024**2, max_json_bytes=16*1024**2, admission=None):
    path = Path(path).resolve()
    if path.stat().st_size > max_json_bytes:
        raise ValueError("JSON supera el limite de lectura")
    try:
        def invalid_constant(value):
            raise ValueError(f"Numero JSON invalido: {value}")
        document = json.loads(path.read_text(encoding="utf-8"), parse_constant=invalid_constant)
        if not isinstance(document, dict):
            raise ValueError("JSON raiz debe ser un objeto")
        filename = document["arrays_file"]
        if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9_. -]+\.npz", filename):
            raise ValueError("arrays_file debe ser un NPZ local sin rutas")
        numeric_path = (path.parent / filename).resolve()
        if numeric_path.parent != path.parent or numeric_path.stat().st_size > max_bytes:
            raise ValueError("Ruta o tamano NPZ no permitidos")
        if _digest(numeric_path) != document["arrays_sha256"]:
            raise ValueError("Checksum NPZ incorrecto; el par JSON/NPZ no coincide")
        shapes = {}
        with zipfile.ZipFile(numeric_path) as archive:
            members = archive.infolist()
            if len(members) > 512 or len({m.filename for m in members}) != len(members):
                raise ValueError("Demasiados arrays o nombres duplicados")
            if sum(m.file_size for m in members) > max_bytes:
                raise ValueError("NPZ expandido supera el limite")
            for info in members:
                if not re.fullmatch(r"[A-Za-z0-9_]+\.npy", info.filename):
                    raise ValueError("Entrada NPZ no admitida")
                with archive.open(info) as stream:
                    version = np.lib.format.read_magic(stream)
                    if version == (1, 0):
                        shape, _, dtype = np.lib.format.read_array_header_1_0(stream)
                    elif version == (2, 0):
                        shape, _, dtype = np.lib.format.read_array_header_2_0(stream)
                    else:
                        raise ValueError("Version NPY no admitida")
                    if dtype.hasobject or dtype.kind not in "fiu" or not 1 <= len(shape) <= 2:
                        raise ValueError("Array no numerico, objeto o rango no admitido")
                    size = math.prod(shape) * dtype.itemsize
                    if size > max_bytes or size != info.file_size - stream.tell():
                        raise ValueError("Forma NPY y tamano real no coinciden")
                    shapes[info.filename[:-4]] = (shape, dtype.str, size)
        if admission is not None:
            admission(document, shapes, path.stat().st_size)
        with np.load(numeric_path, allow_pickle=False) as arrays:
            return document, {key: arrays[key] for key in arrays.files}
    except (KeyError, TypeError, json.JSONDecodeError, zipfile.BadZipFile, EOFError, RecursionError) as exc:
        raise ValueError(f"Archivo invalido: {exc}") from exc
