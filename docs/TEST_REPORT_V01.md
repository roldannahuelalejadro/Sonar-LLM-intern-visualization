# Verificacion local de SONAR 0.1

Fecha: 2026-10-07. Todas las fuentes de prueba fueron **sinteticas**.
No se ejecuto una LLM ni un experimento de seguridad.

## Entorno Verificado

- Windows 11 x64, build 26200.
- CPython 3.12.14; entorno local `.venv`, creado para este proyecto.
- NumPy 2.3.3, PySide6/Qt 6.11.2, PyQtGraph 0.14.0, pytest 8.4.2.
- Instalacion editable, comando de ayuda, construccion wheel y `pip check`: OK.
- Importacion del SDK: sin Qt, PyQtGraph ni Torch en `sys.modules`.
- Qt offscreen para pruebas repetibles y backend nativo Windows para
  inspeccion visual, ciclo de vida y mediciones de pintura.

## Pruebas Automatizadas

**43 pruebas pasadas**, ultima ejecucion completa: 2.83 s.

| Area | Comprobaciones |
|---|---|
| Contratos | float32, finitud, dimension, metadata y buffers inmutables |
| Diferencias | referencia cero, descriptor incompatible, hueco y stream nuevo |
| Historial | eviccion, reduccion de presupuesto, congelacion y sondas separadas |
| Transporte | FIFO, cola llena, contencion, consumidor lento/cerrado, spawn |
| Ciclo de vida | tres sesiones consecutivas, cierre idempotente, sin hijos huerfanos |
| Proyeccion | referencia NumPy, fuera del plano, base no ortogonal y escala |
| PCA | datos insuficientes, rango nulo, resultado fijo y worker de GUI |
| Persistencia | valores/contextos/referencia/base/escala, deltas reproducidos |
| Archivos invalidos | pickle/objetos, traversal, checksum, forma NPY falsa, IDs/indices |
| GUI | matriz/padding/orientacion, hilo Qt, freeze, controles y replay |

Las pruebas negativas de NPZ comprueban las cabeceras antes de asignar arrays.
Esto no equivale a una auditoria de seguridad completa de NumPy, ZIP o Qt.

## Verificacion Visual

`tools/verify_ui.py --native` produjo matriz, historia y direcciones a
1220x800 y 900x650, mas reproduccion de la captura. Se inspeccionaron las
imagenes: texto legible, controles sin superposicion, valores con signo,
grises ausentes, cortes de trazas y scores consistentes. Hay scroll lateral
en ventanas compactas. Se comprobaron pixeles no uniformes en todas las vistas.

Archivos regenerables en `artifacts/`: `matrix-*.png`, `history-*.png`,
`directions-*.png`, `replay.png` y `ui-verification.json`.
El fallback de fuente Windows para Qt offscreen evita glifos vacios; la
verificacion nativa utiliza las fuentes del sistema.

## SDK Publico

`tools/smoke_sdk.py` usa `open_monitor` real, con proceso hijo `spawn` y
ventana Windows. Resultado: **30 aceptadas, 30 recibidas, 0 descartes**;
7 lecturas llegaron al dibujo primario y las otras 23 se conservaron como
recibidas no dibujadas en ese refresco. Cierre y liberacion del buffer: OK.

## Carga Tecnica

`tools/verify_runtime.py`: vectores de 4096 componentes, cola de 16 slots,
10 Hz, pausa solicitada de 2 ms entre intentos y ventana que se cierra a los
2.5 s. Una sola ejecucion local; **no son garantias de rendimiento**.

| Medida | Resultado |
|---|---:|
| Publicacion CPU, mediana | 0.460 ms |
| Publicacion CPU, p95 | 0.875 ms |
| Captura a recepcion, media | 104.47 ms |
| Captura a fin de paintEvent, lecturas dibujadas | 81.65 ms |
| Preparacion de escena, media | 2.22 ms |
| CPU de paintEvent Qt, media | 7.12 ms |
| Intentos / aceptadas / descartadas | 875 / 330 / 545 |
| Recibidas / dibujadas / recibidas no dibujadas | 314 / 23 / 291 |
| Aceptadas pendientes al cerrar | 16 |

El promedio a pintura usa solo lecturas dibujadas, no la misma poblacion que
el promedio de recepcion. No mide latencia fisica de pantalla. El exceso de
publicacion produce descartes explicitos: no se bloquea para vaciar la cola.
Los intervalos y la duracion de la prueba dependen del scheduler de Windows.

Primera medicion de preparacion de escena: 21.47 ms. Se detecto que se
recalculaban vistas ocultas. Despues de actualizar solo la pestaña visible,
la medicion fue 2.22 ms; las pestañas se actualizan al abrirlas. No se agrego
otra implementacion ni se optimizo el codigo de inferencia externo.

Prueba de historial: **10000** lecturas, presupuesto **1048576 bytes**, pico
contabilizado **1037104 bytes**, **9947** evicciones. El productor continuo
despues del cierre del visor y no quedaron procesos hijos huerfanos.
Datos de esta ejecucion en `artifacts/runtime-verification.json`.

## Limitaciones y Pendientes

- Linux no fue ejecutado; no se declara validado. Tampoco notebooks, GPU ni modelos.
- Fase 8 pendiente de elegir motor; el extra `torch` no implica un adaptador.
- No hay grabacion exhaustiva, servidor, conexion remota ni lector semantico.
- El historial acotado no limita todo el RSS; Qt, proyecciones, referencias,
  PCA y carga/guardado requieren memoria adicional acotada por recurso.
- La PCA es de ventana finita; un calculo ya iniciado termina en el worker.
  `session.close()` tiene un plazo de cierre y puede terminar el proceso visual.
- Carga/guardado se realiza sin un servicio de grabacion paralelo; puede pausar
  brevemente la recepcion y causar descartes contados mientras la GUI trabaja.
- La base externa solo admite la transformacion afin documentada. Su significado
  y su compatibilidad cientifica no se deducen ni se validan automaticamente.
- No se realizo una prueba de muchas horas; la carga automatizada es tecnica y corta.

## Repetir

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python tools\smoke_sdk.py
.\.venv\Scripts\python tools\verify_ui.py --native
.\.venv\Scripts\python tools\verify_runtime.py
.\.venv\Scripts\python -m pip check
```

Las mediciones y capturas generadas se sobrescriben al repetir sus verificadores.
Los NPZ de generaciones anteriores no se borran automaticamente.
