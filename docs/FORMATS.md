# Bases v1 y capturas v2 (lectura compatible v1)

Cada objeto usa un JSON y un NPZ numerico asociado. El JSON contiene
`arrays_file` (solo nombre local) y `arrays_sha256`. El guardado crea un NPZ con
nombre unico y reemplaza el JSON al finalizar; un fallo no deja un JSON nuevo
apuntando a un archivo parcial. Si se sobrescribe un JSON existente, su NPZ viejo
no se borra automaticamente. Mover/compartir ambos archivos juntos.

No se carga pickle ni arrays objeto. El lector revisa ruta, checksum, tamano
comprimido/expandido y cabeceras NPY (forma, dtype y bytes reales) antes de cargar.
No es un importador universal de formatos externos.

## Bases

JSON: `format=sonar-basis`, `schema_version=1`, `basis_id`, `space_id`,
`dimension`, `n_axes`, `axis_names`, `origin` y:

```json
{"preprocessing": {"kind": "affine", "order": ["center", "scale", "project"]}}
```

NPZ: `W` de forma `(dimension, ejes)`, `center` de forma `(dimension,)`,
`scale` positiva de la misma forma (si se omite, se usan unos).

```text
z = W.T @ ((a - center) / scale)
delta_z = W.T @ (delta_a / scale)
```

La segunda expresion no vuelve a restar el centro. No se reordenan operaciones
ni se aplica normalizacion L2. Una base RepE con otra convencion debe convertirse
explicitamente fuera de SONAR y documentar su procedencia en `origin`.

Ejemplo de exportacion de dos componentes para probar el lector:

```python
from sonar_activaciones.processing.projection import component_basis, save_basis
basis = component_basis(probe, [0, 1])
save_basis("mi_base.json", basis)
```

Para direcciones reales, crear `DirectionBasis` con W/centro/escala explicitamente
medidos o provistos por la fuente. El ID y `space_id` son responsabilidad del
productor. La importacion no valida que un nombre corresponda a un concepto.

La PCA centra una ventana finita y aplica SVD; rechaza muestras insuficientes o
rango menor que k (1..32) en la GUI. Se calcula fuera del hilo Qt, luego queda fija.
Los signos se fijan por la componente de mayor magnitud; degeneraciones pueden
rotar la base entre ajustes, por lo que se guarda la matriz exacta y un ID nuevo.
No hay refit continuo. Cada aplicacion crea un segmento; no reemplaza coordenadas
antiguas. Hasta 512 vectores retenidos se pueden reproyectar por lotes como
derivados identificados. Si expiran antes de procesarlos, queda un evento.

La norma omitida usa `||u - W W.T u||` solo cuando W es ortonormal. Sin escala,
`u=delta_a` y la metrica es original; con escala, `u=delta_a/scale` y se rotula
metrica transformada. La norma completa original se muestra por separado. Para
W no ortonormal se deshabilita esa descomposicion, sin fingir ortogonalidad.

## Capturas antiguas v1

JSON: `format=sonar-capture`, `schema_version=1`, `partial=true`,
`extent=retained_window`. `series` asocia descriptor, secuencias, tiempos y
contextos a cada fila del array float32 `pN_values`. Las referencias conservan
su contexto y vector `pN_reference`; las bases usan `pN_basis_W/center/scale`.
Se guardan snapshot, estado visual, contadores, evicciones y huecos de secuencia.

Snapshot identifica una muestra de la ventana, incluso si era una lectura
congelada antigua. Los deltas conservan las mismas reglas: si falta una
predecesora, no se reconstruye. El historial puede empezar a mitad de un stream.
Reproduccion usa los intervalos monotonic originales y muestra tiempo relativo,
con pausa/velocidad/pasos; nunca presenta esos tiempos como edad de una fuente viva.

Se conserva la base activa de cada sonda, no un archivo ilimitado de versiones
previas. Para conservar otra version, exportarla antes de sustituirla.

El lector 0.2 conserva estos vectores y sus bases, pero no inventa coordenadas
historicas que el formato v1 no guardaba. Si habia varias referencias, solicita
elegir una explicitamente. La carga debe caber en las cuotas configuradas.

## Capturas mixtas v2

`storage/mixed.py`: `format=sonar-capture`, `schema_version=2`, `partial=true`,
`extent=retained_window`. Mantiene session_id y descriptores. Cada frame contiene
sequence, captured_at, contexto compartido, raw_row (entero o null) y disponibilidad
explicita. Solo los vectores presentes tienen fila en `pN_values`; no hay ceros
de relleno para un vector perdido.

Cada segmento `bN` conserva metadata de base, probe_id, inicio, secuencias y
marcas de reproyeccion derivada. Arrays: `bN_W`, `bN_center`, `bN_scale` float64
y `bN_coordinates` float32. Coordenadas siempre refieren al ID inmutable de base.
La captura guarda segmentos activos, referencia unica, seleccion, huecos,
eventos acotados, contadores y estado visual. El ultimo numero recibido no debe
confundirse con la ultima captura guardada en esta ventana parcial.

GUI guarda hasta el valor de Ventana (maximo 512 capturas por sonda), mas una
seleccion fijada que pueda estar fuera. Conserva las bases antiguas aun si esa
ventana no tiene puntos en ellas. No es grabacion exhaustiva.

Importacion: JSON acotado antes de parsear; cabeceras NPY y coste de arrays/objetos
admitidos antes de `np.load`. Si no cabe, ampliar presupuesto/reserva/reparto o
exportar una ventana menor. Nunca se aumenta memoria automaticamente al abrir.
La configuracion del visor receptor prevalece sobre la del archivo.

Exportacion: admision previa a stacks/snapshot/JSON. ZIP y SHA-256 trabajan en
fragmentos de 64 KiB; compresion opaca de biblioteca se distingue de buffers
conocidos. Como en v1, el guardado es JSON + NPZ local con SHA-256, sin pickle.
Carga/guardado son sincronicos: pueden retrasar recepcion, pero no bloquean al
productor para vaciar su cola. Los descartes se contabilizan.
