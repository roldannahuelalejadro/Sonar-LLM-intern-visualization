from dataclasses import dataclass
import uuid
import numpy as np

from ..contracts import bounded_text, json_bytes
from ..storage.numeric import read_pair, write_pair

MAX_BASIS_BYTES = 16 * 1024**2
MAX_PCA_BYTES = 16 * 1024**2
PREPROCESSING = {"kind": "affine", "order": ["center", "scale", "project"]}


def immutable_array(value):
    value = np.asarray(value)
    if value.dtype.kind not in "fiu" or value.nbytes > MAX_BASIS_BYTES:
        raise ValueError("Array de base demasiado grande o no numerico")
    array = np.asarray(value, dtype="<f8")
    if not np.isfinite(array).all():
        raise ValueError("Base contiene NaN o infinito")
    return np.frombuffer(array.tobytes(), dtype="<f8").reshape(array.shape)


@dataclass(frozen=True, slots=True, eq=False)
class DirectionBasis:
    basis_id: str
    space_id: str
    axis_names: tuple
    origin: str
    W: np.ndarray
    center: np.ndarray
    scale: np.ndarray
    schema_version: int = 1

    def __post_init__(self):
        bounded_text(self.basis_id, "basis_id")
        bounded_text(self.space_id, "space_id")
        bounded_text(self.origin, "origin", 2048)
        if self.schema_version != 1:
            raise ValueError("Version de base no soportada")
        arrays = (np.asarray(self.W), np.asarray(self.center), np.asarray(self.scale))
        if sum(a.size*8 for a in arrays) > MAX_BASIS_BYTES:
            raise ValueError("Base supera 16 MiB")
        w, center, scale = arrays
        if w.ndim != 2 or not 1 <= w.shape[1] <= 32 or w.shape[0] < 1:
            raise ValueError("W debe tener forma (dimension, ejes), con 1 a 32 ejes")
        if center.shape != (w.shape[0],) or scale.shape != center.shape:
            raise ValueError("Centro/escala no coinciden con W")
        names = tuple(self.axis_names)
        if len(names) != w.shape[1]:
            raise ValueError("Cantidad de nombres de eje incompatible")
        for name in names:
            bounded_text(name, "axis_name")
        object.__setattr__(self, "axis_names", names)
        for key in ("W", "center", "scale"):
            object.__setattr__(self, key, immutable_array(getattr(self, key)))
        if np.any(self.scale <= 0):
            raise ValueError("Escala debe ser estrictamente positiva")
        if np.any(np.linalg.norm(self.W, axis=0) == 0):
            raise ValueError("Una direccion tiene norma cero")

    @property
    def dimension(self):
        return self.W.shape[0]

    @property
    def nbytes(self):
        return self.W.nbytes + self.center.nbytes + self.scale.nbytes + 4*len(json_bytes(self.metadata())) + 2048

    def validate_probe(self, probe):
        if probe.dimension != self.dimension or probe.space_id != self.space_id:
            raise ValueError("Base incompatible: dimension o space_id no coinciden")

    def metadata(self):
        return {"schema_version": 1, "basis_id": self.basis_id, "space_id": self.space_id,
                "dimension": self.dimension, "n_axes": len(self.axis_names),
                "axis_names": list(self.axis_names), "origin": self.origin,
                "preprocessing": PREPROCESSING}

    def project(self, values):
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            result = ((np.asarray(values, dtype=float) - self.center) / self.scale) @ self.W
        if not np.isfinite(result).all():
            raise ValueError("Proyeccion no finita; revisar magnitudes y escala de la base")
        return result

    def project_delta(self, delta):
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            result = (np.asarray(delta, dtype=float) / self.scale) @ self.W
        if not np.isfinite(result).all():
            raise ValueError("Proyeccion del delta no finita; revisar escala de la base")
        return result

    def displacement(self, delta):
        delta = np.asarray(delta, dtype=float)
        result = {"original_norm": float(np.linalg.norm(delta)), "omitted_norm": None,
                  "transformed_norm": float(np.linalg.norm(delta/self.scale)),
                  "metric": "original" if np.array_equal(self.scale, np.ones(self.dimension)) else "transformed"}
        if np.allclose(self.W.T @ self.W, np.eye(self.W.shape[1]), atol=1e-7, rtol=1e-7):
            transformed = delta / self.scale
            result["omitted_norm"] = float(np.linalg.norm(transformed-self.W @ (self.W.T@transformed)))
        return result

    @classmethod
    def from_data(cls, metadata, arrays):
        if not isinstance(metadata, dict):
            raise ValueError("Metadata de base invalida")
        if metadata.get("preprocessing") != PREPROCESSING:
            raise ValueError("Preprocesamiento no soportado; se requiere center -> scale -> project afin")
        try:
            w = arrays["W"]
            if w.ndim != 2 or type(metadata["dimension"]) is not int or metadata["dimension"] != w.shape[0]:
                raise ValueError("Dimension declarada no coincide con W")
            basis = cls(metadata["basis_id"], metadata["space_id"], tuple(metadata["axis_names"]),
                        metadata["origin"], w, arrays["center"],
                        arrays.get("scale", np.ones(metadata["dimension"])), metadata["schema_version"])
            if metadata["dimension"] != basis.dimension or metadata["n_axes"] != basis.W.shape[1]:
                raise ValueError("Dimensiones declaradas no coinciden con arrays")
            return basis
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Base invalida: {exc}") from exc


def component_basis(probe, indices):
    indices = tuple(indices)
    if not 1 <= len(indices) <= 32 or len(set(indices)) != len(indices) or any(type(i) is not int or not 0 <= i < probe.dimension for i in indices):
        raise ValueError("Seleccionar entre 1 y 32 componentes distintas y validas")
    if probe.dimension*(len(indices)+2)*8 > MAX_BASIS_BYTES:
        raise ValueError("Base por componentes supera el limite")
    w = np.zeros((probe.dimension, len(indices)))
    w[indices, np.arange(len(indices))] = 1
    return DirectionBasis(uuid.uuid4().hex, probe.space_id, tuple(f"c{i}" for i in indices),
                          "componentes elegidas por el usuario", w, np.zeros(probe.dimension), np.ones(probe.dimension))


def fit_pca(samples, n_axes=2):
    if not samples or type(n_axes) is not int or not 1 <= n_axes <= 32 or len(samples) <= n_axes:
        raise ValueError("PCA requiere mas muestras que ejes")
    probe = samples[0].descriptor
    if any(not probe.compatible(s.descriptor) for s in samples):
        raise ValueError("PCA no mezcla espacios o sondas")
    if len(samples)*probe.dimension*8 > MAX_PCA_BYTES:
        raise ValueError("Ventana PCA supera 16 MiB de entrada float64; reducir muestras")
    data = np.array([s.values for s in samples], dtype=float)
    center = data.mean(axis=0)
    data -= center
    _, singular, vt = np.linalg.svd(data, full_matrices=False)
    tolerance = np.finfo(float).eps * max(data.shape) * (singular[0] if len(singular) else 0)
    rank = int(np.count_nonzero(singular > tolerance))
    if rank < n_axes:
        raise ValueError(f"PCA: rango {rank} insuficiente para {n_axes} ejes")
    w = vt[:n_axes].T.copy()
    for col in range(n_axes):
        if w[np.argmax(np.abs(w[:, col])), col] < 0:
            w[:, col] *= -1
    return DirectionBasis(uuid.uuid4().hex, probe.space_id, tuple(f"PC{i+1}" for i in range(n_axes)),
                          f"PCA fija; {len(samples)} lecturas; seq {samples[0].sequence}..{samples[-1].sequence}",
                          w, center, np.ones(probe.dimension))


def save_basis(path, basis):
    return write_pair(path, {"format": "sonar-basis", **basis.metadata()},
                      {"W": basis.W, "center": basis.center, "scale": basis.scale})


def load_basis(path, probe=None, *, admission=None):
    metadata, arrays = read_pair(path, max_bytes=MAX_BASIS_BYTES+65536, max_json_bytes=65536, admission=admission)
    if metadata.get("format") != "sonar-basis" or set(arrays) - {"W", "center", "scale"}:
        raise ValueError("Formato de base no admitido")
    basis = DirectionBasis.from_data(metadata, arrays)
    if probe is not None:
        basis.validate_probe(probe)
    return basis
