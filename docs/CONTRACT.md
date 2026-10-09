# Contrato numerico v1, gestion de memoria v2

## Sondas

`ProbeDescriptor` es inmutable y se declara al abrir la sesion. Campos requeridos:
`probe_id`, `name`, `source_id`, `capture_point`, `dimension`, `selection_rule`,
`space_id`; `schema_version=1` y metadata opcional. Maximo 64 sondas, IDs unicos.
Los campos de texto requeridos admiten hasta 256 bytes UTF-8 cada uno.

La metadata admite hasta 32 escalares JSON (texto, entero int64, float finito,
booleano o null); maximo 4096 bytes serializados y 2048 bytes por texto.
El contexto de cada lectura usa los mismos limites. Puede contener `stream_id`,
`processed_position`, `predicted_position`, `token`, `text`, `stage`, `run_label`.
No se deduce que una posicion procesada sea el token predicho.

`space_id` es una afirmacion del productor acerca de la identidad de las
coordenadas. Mismo tamano no implica mismo espacio. Cambiar checkpoint, capa,
seleccion o significado de coordenadas requiere otro descriptor/sesion.
SONAR comprueba el contrato, no puede comprobar la veracidad de esa afirmacion.

## Observaciones

Solo `numpy.ndarray` CPU real unidimensional, con dimension exacta. Se convierte
a float32 little-endian, se comprueba finitud **despues** de convertir y se copia
a bytes inmutables. Un overflow float32 se rechaza, no se sustituye por cero.
El array del llamador nunca se modifica; una publicacion aceptada conserva su
instantanea incluso si despues el productor reutiliza ese buffer.

Secuencia por sonda desde 0; timestamp `time.monotonic()` al entrar en la
construccion de la lectura, incluyendo la captura CPU de frontera. Los vectores
ya calculados externamente no incluyen ese tiempo de calculo previo. Los relojes
locales usados aqui se compararon en procesos Windows. Replay usa intervalos,
nunca calcula una edad viva restando un timestamp antiguo al reloj actual.

## Diferencias

- `raw`: vector original float32.
- `reference_delta`: actual menos referencia, en float64. Requiere descriptor
  completo identico; puede comparar streams distintos si el usuario lo decide.
- `previous_delta`: actual menos predecesora, en float64, solo si hay secuencias
  consecutivas y `stream_id` igual. Ausencia de `stream_id` significa un stream
  implicito por sonda. Un hueco o cambio de stream da `None`, no un cero.

La referencia es una observacion inmutable, no un puntero al array del productor.
La norma y el RMS se calculan sobre todos los componentes de la lectura mostrada,
no solo las celdas del bloque visible.

## Memoria

| Recurso | Inicio / tope |
|---|---|
| Cola compartida | 16 slots x 1 MiB; tope agregado 256 MiB |
| Muestra | 1 MiB; configurable de 4096 bytes a 16 MiB |
| Datos administrados globales | 64 MiB; hasta 2 GiB, sujeto a admision |
| Historial reciente / proyectado | 70% / 30% del remanente tras reservas |
| Referencia y congelacion | Una de cada una, con reserva independiente |
| Base | 16 MiB numericos por base; 8 segmentos por defecto, maximo 32 |
| Trabajo conocido | Reserva inicial 8 MiB, compartida por una operacion a la vez |
| PCA | Entrada float64 hasta 16 MiB, 512 muestras; k=1..32, sujeto a rango y reserva |
| Captura | Hasta 128 MiB NPZ expandido y 16 MiB JSON |

`processing/memory.py` define el plan: capacidad completa de slots compartidos,
seis slots para copias conocidas en vuelo, descriptores/eventos, dos fijaciones,
preparacion visual/numerica, reserva de trabajo y bases retenidas. El resto se
divide por sonda (bytes iguales por defecto) y por tipo de historial.

El encabezado compartido de cada captura reserva 4096 + 16 veces los bytes JSON
del contexto. Incluye objetos Python, indices y nodos. Vector: d*4+256 bytes;
coordenadas: k*4+512 bytes por segmento. El encabezado se carga al proyectado si
hay coordenadas y al reciente en caso contrario, nunca a ambos. Contexto y
descriptor se comparten entre ambas representaciones. Son margenes conservadores
inspeccionables, no una medicion exacta del heap.

Las cuotas son capacidades autorizadas; los historiales asignan registros a
demanda. La cola compartida si se preasigna completa. La suma de reservas y
cuotas no excede el presupuesto. Incluso el visor offline reserva conservadoramente
el transporte configurado. RSS del visor se muestra aparte: no incluye al productor.
Interprete, asignadores, Qt y workspace opaco de BLAS/LAPACK quedan fuera del
limite administrado. No hay una promesa de RSS maximo ni aislamiento del SO.

La PCA reserva snapshot, entrada float64, salidas SVD y copias conocidas antes
de fijar vectores. No forma covarianza d*d. Muestra una estimacion orientativa
adicional de biblioteca, no una cota de LAPACK. Importar una base evita el ajuste.
Proyecciones de recepcion y reproyecciones derivadas se procesan en lotes acotados
independientes del temporizador de render. Un matmul individual no tiene una
garantia de latencia maxima. PCA se ejecuta en un unico worker.

Aplicar una reduccion evicta in situ: sin duplicar buffers, sin volver a vivo y
sin eliminar referencia/seleccion. El impacto se calcula antes. Una ampliacion
no recupera datos. `history_bytes` legado conserva su cuota reciente y traduce
a un total mayor; se puede pasar a presupuesto global con Aplicar. Cambiar el
tamano del transporte o registrar otras sondas requiere otra sesion.

Identidad: session_id, probe_id, sequence. stream_id es contexto de continuidad.
Hay una union navegable de capturas, no dos series alineadas artificialmente.
Al salir el vector pueden quedar las coordenadas; si salen ambas, la captura
desaparece. La seleccion congelada queda fijada hasta cambiarla o volver a vivo.
Los eventos son una cola de 128 entradas; los contadores agregados no crecen
en cantidad de claves con el tiempo. La coordenada almacenada es float32;
la base afin permanece float64. No se cambia precision por presion de memoria.

## Transporte y Contadores

Ring buffer de slots fijos en memoria compartida de procesos relacionados.
Try-lock tanto al enviar como al recibir, sin sockets ni feeder threads.
Cola llena **o contencion momentanea** descarta la lectura entrante. No hay
reintentos silenciosos que cambien el ritmo del productor.

`accepted`: copiada a la cola (no garantiza que el visor llegue a recibirla).
`transport_dropped`: no encolada. `gate_skipped`: captura omitida antes del
calculo costoso. Ambos consumen posicion de secuencia, conservando los huecos.
`received`: retirada y aceptada por el visor. `drawn`: lectura seleccionada que
llego a un paintEvent de la vista. `received_not_drawn`: no llego a ese dibujo
primario, por supersesion, otra sonda o congelacion; puede existir en el historial.
Puede haber una lectura pendiente de paintEvent, y muestras en cola al cerrar.
Por ello `accepted` no equivale a `received` ni a `drawn`.

El transporte distingue `transport_full`, `transport_contended` e
`invalid_received`. El historial distingue `not_received` (huecos, sin inferir
su causa), `projection_pending_basis`, `projection_nonfinite`, `projection_quota`,
`vector_retired_projection_kept`, `vector_retired`, `projection_retired`,
`capture_retired`, `basis_changed` y reproyecciones no disponibles/reemplazadas.
`received_not_drawn` no significa datos perdidos: la proyeccion ocurre al recibir.

`publish_ns_total` mide frontera CPU + encolado; `receive_latency_ns_total` mide
captura a recepcion. `draw_ns_total/scene_updates` mide preparacion de escena;
`paint_ns_total/paint_count` mide CPU de paintEvent de Qt;
`render_latency_ns_total/drawn` mide captura al fin de ese paintEvent. No mide
scanout del monitor ni tiempo de inferencia.
