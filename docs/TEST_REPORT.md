# Verificacion local de SONAR 0.2

Informe historico. La verificacion de la version actual esta en
[TEST_REPORT_0_2_1.md](TEST_REPORT_0_2_1.md); no trasladar estas cifras a 0.2.1.

Fecha: 2026-10-09. Solo fuentes sinteticas. No se descargo ni ejecuto una LLM.
Informe anterior preservado en `TEST_REPORT_V01.md`.

## Revalidacion al preparar el repositorio

2026-10-09: sin cambios en el codigo funcional, se repitio la suite antes del
primer commit. Las 67 pruebas pasaron en 3.51 s, pero el proceso no termino
correctamente: con `-X faulthandler` informo `Windows fatal exception: access
violation`, sin marco Python, y codigo de salida `-1073741819` (`0xC0000005`).
Una primera ejecucion tambien informo 67 pruebas aprobadas y salida no exitosa.
Por tanto, esta revalidacion completa **no tiene un cierre limpio**.

La ejecucion sin `tests/test_gui.py` aprobo 59 pruebas en 2.57 s y termino con
codigo 0. La incidencia queda pendiente de diagnostico; su causa no se ha
atribuido a un componente concreto ni se ha demostrado que afecte al uso normal
del visor. No se repitieron los ensayos prolongados ni se modifico la aplicacion
para preparar la publicacion. Las mediciones siguientes corresponden a las
corridas anteriores documentadas, no a esta revalidacion.

## Entorno y estado

Windows 11 x64 build 26200, CPython 3.12.14, NumPy 2.3.3, PySide6 6.11.2,
PyQtGraph 0.14.0, pytest 8.4.2. Instalacion editable actualizada a 0.2.0 sin
red ni nuevas dependencias; wheel generado; `pip check` sin conflictos.
CLI devuelve `SONAR 0.2.0`. Importacion SDK sin Qt/Torch verificada por pruebas.

**67 pruebas aprobadas** en la verificacion previa: 4.21 s. Cubren contratos,
transporte, diferencias, proyeccion, PCA, memoria, persistencia y GUI.

## Cobertura nueva

- Presupuesto 1/64 MiB con dimensiones 70/4096/5120 y sondas heterogeneas.
  Los rechazos incluyen minimo calculado. 1 MiB es admisible para d=70 con
  transporte explicito reducido (1 slot de 4096 B), sin reserva de trabajo;
  no lo es con los defaults de transporte/reserva.
- Traduccion de `history_bytes` sin convertirlo silenciosamente en presupuesto
  global; suma de cuotas/reservas; transporte existente no subcontabilizado.
- Dos anillos, union de IDs, referencia y seleccion congelada, proyeccion
  conservada tras perder vector, retiro completo y eventos acotados.
- Error de proyeccion float32 conserva vector y registra causa. Formula afin,
  senal fuera de plano y base no ortogonal se contrastan con NumPy.
- Segmentos antiguos, reproyecciones derivadas, cambios de presupuesto y
  previsualizacion de evicciones contrastada con efecto real.
- Seleccion de proyeccion antigua limpia la matriz y permanece al recibir;
  navegacion llega a capturas fuera de la ventana visual de 512 puntos.
- Captura mixta con ausencias, bases, referencia y contexto; carga v1;
  eleccion explicita si la captura vieja contenia varias referencias.
- Importacion rechazada antes de `np.load` si no cabe. Checks previos de NPY,
  checksum, rutas y objetos/pickle siguen pasando. Exportacion rechazada antes
  de stacks si no cabe la reserva. No es una auditoria completa de ZIP/NumPy.
- Liberacion inmediata del historial sin depender del recolector ciclico
  (prueba con GC deshabilitado) y compactacion de indices al reducir cuotas.

## Ensayo del nucleo

`artifacts/soak-v02.json`: **610.016 s**, **102310 capturas por sonda**, tres
estados independientes d=70/4096/5120. Presupuestos pequenos 2/3 MiB con cientos
de vueltas de los anillos, fijaciones y cambios de base. Los rechazos de una
reduccion incompatible conservaron el plan anterior.

Tras 120 s, RSS agregado de este proceso paso de 35041280 a 35430400 bytes
(incremento ~0.37 MiB); la ocupacion retenida se repitio segun presupuesto/base.
Ultimo checkpoint: mas de 100000 retiros de proyeccion y capturas por estado.
Este ensayo inicial no incluia Qt/transporte. Fue seguido por el integrado.

## Ensayo integrado

`artifacts/native-soak-v02.json`: **610.047 s**, SDK real con proceso spawn,
Qt nativo a 900x650, 5 Hz de render, tres sondas d=70/4096/5120. Transporte:
4 slots de 32768 B. Publicacion solicitada: una muestra por sonda cada 4 ms,
sin esperar espacio. Presupuesto global alternado **8/9 MiB**, reserva de trabajo
4 MiB, reparto reciente 10%. Referencias/selecciones, bases, exportacion y
recarga mixta repetidas durante la recepcion. **Cero errores**.

| Medida al ultimo checkpoint | Valor |
|---|---:|
| Intentos de publicacion | 323382 |
| Aceptadas / recibidas | 215602 / 215598 |
| Descartes transporte | 107780 |
| Por cola llena / contencion | 106824 / 956 |
| Paquetes invalidos | 0 |
| Vectores retirados, proyeccion conservada | 214802 |
| Proyecciones retiradas | 215760 |
| Capturas completamente retiradas | 215196 |
| Segmentos creados durante la prueba | 14 |
| Proyecciones calculadas (incluye derivados) | 216162 |
| Preparacion media de escena | 17.77 ms |
| Procesamiento medio por recibida (incluye su proyeccion) | 0.100 ms |
| Proyeccion media, incluyendo derivados | 0.077 ms |

Desde 120 s: RSS minimo **127332352 B (121.43 MiB)**, maximo **130846720 B
(124.79 MiB)**. Final **127377408 B (121.48 MiB)**. No se observo crecimiento
sostenido en esa ventana. Las cuotas/reservas respetaron el presupuesto en cada
checkpoint; ocupacion de historial final 2165568 B. El RSS no se presenta como
parte de los 8/9 MiB ni como limite impuesto por SONAR.

El ultimo checkpoint precede al cierre: hay cuatro aceptadas pendientes en cola
y una recibida pendiente de paintEvent. Las perdidas son explicitas, no se
ocultan ni se interpretan como falta de capacidad de una IA. No quedaron hijos
de prueba en ejecucion, comprobado tambien por inspeccion posterior de procesos.

La primera corrida integrada detecto seleccion de segmento incorrecta al
instalar una base en otra sonda. Se interrumpio, se corrigio, se agrego regresion
y se repitieron los diez minutos. Solo la corrida completa sin errores sustenta
las cifras anteriores. Ninguna prueba temporal certifica funcionamiento por dias.

Revision posterior al ensayo: se elimino un ciclo de propiedad de los callbacks
de historial y se compacto la capacidad de diccionarios al reducir cuotas. Esa
correccion paso la regresion especifica y la suite de 67 pruebas; no se repitio
el ensayo completo de diez minutos despues de ese ultimo ajuste. Las cifras
temporales corresponden a la corrida identificada en el JSON, no a una medicion
nueva del ajuste final.

## UI y dibujo

Capturas nativas inspeccionadas: `artifacts/v02-unified-1220.png`,
`v02-unified-900.png`, vistas maximizadas y replay. Se verifico visibilidad de
cada grafico, pixeles no uniformes, seleccion compartida y ausencia de vector.
En vista integrada el historial muestra disponibilidad; al maximizarlo muestra
calor/trazas. Asi no se comprimen tres subgraficos en la ventana pequena.

`ui-verification-v02.json`: 25 refrescos por caso, fixture sintetica estatica
de 70 componentes y 117 capturas con hueco/cambio de serie. Preparacion CPU de
escena; **no incluye** latencia fisica de monitor ni inferencia.

| Vista | 1220x800 mediana / p95 | 900x650 mediana / p95 |
|---|---:|---:|
| Integrada | 16.92 / 19.17 ms | 17.87 / 22.25 ms |
| Matriz maximizada | 1.96 / 2.52 ms | 1.86 / 2.55 ms |
| Mapa maximizado | 11.94 / 14.06 ms | 12.28 / 14.75 ms |
| Historia maximizada | 19.18 / 23.18 ms | 21.32 / 23.70 ms |

La fixture no publica durante estos 25 refrescos: no mide perdidas de
transporte. Esas perdidas se miden en las pruebas en vivo. Las distribuciones
de paintEvent separadas estan en el JSON; no sumar sus p95 como latencia total.

## Comparacion con baseline

Misma carga solicitada que v0.1: d=4096, cola 16, cuota legada 2 MiB, 10 Hz,
pausa solicitada de 2 ms, cierre a 2.5 s. Una corrida local por version; cambios
del scheduler/carga de fondo limitan la comparacion. v0.1 dibuja solo matriz;
v0.2 dispone sus paneles juntos. Sin base en ambos casos. No es un benchmark de IA.

| Medida | Baseline v0.1 del 09/10 | v0.2 |
|---|---:|---:|
| Publicar mediana / p95 | 0.170 / 0.333 ms | 0.182 / 0.342 ms |
| Captura a recepcion, media | 96.66 ms | 8.68 ms |
| Preparacion de escena, media | 0.90 ms | 7.40 ms |
| Intentos / aceptadas / descartadas | 975 / 340 / 635 | 896 / 889 / 7 |
| Recibidas / dibujadas | 337 / 24 | 887 / 22 |

La recepcion desacoplada del render mejora esta corrida; dibujar mas vistas
cuesta mas que la matriz sola. No se atribuyen los tiempos antiguos al nuevo
layout. Datos: `baseline-v01-20261009.json` y `runtime-verification-v02.json`.

SDK publico sin cambios de llamada (`tools/smoke_sdk.py`): 30 aceptadas,
30 recibidas, 0 descartes, 3 dibujadas y 27 recibidas no dibujadas. Cierre OK.
Repeticion tras el ajuste final de indices/propiedad: 29 aceptadas/recibidas,
1 descarte por contencion, 4 dibujadas y 25 recibidas no dibujadas; cierre OK.
El descarte es una salida prevista del transporte try-lock, no un reintento oculto.

## Limites y repeticion

Linux, notebooks, GPU y modelos reales no fueron verificados. No hay adaptadores,
red, descarga de modelos ni experimentos conductuales. El presupuesto cubre
buffers conocidos y margenes de objetos, no RSS total o workspace opaco externo.
La PCA muestra una estimacion externa orientativa, no una garantia. I/O sincronico
puede causar descartes de transporte; aumentar RAM no recupera datos perdidos.

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python tools\smoke_sdk.py
.\.venv\Scripts\python tools\verify_ui.py --native
.\.venv\Scripts\python tools\verify_runtime.py
.\.venv\Scripts\python tools\soak_v2.py
.\.venv\Scripts\python tools\native_soak_v2.py
.\.venv\Scripts\python -m pip check
```

Los verificadores sobrescriben sus JSON/PNG de resultados; los pares de captura
no borran automaticamente NPZ viejos. El verificador integrado usa una carpeta
temporal propia y la limpia al terminar normalmente.
