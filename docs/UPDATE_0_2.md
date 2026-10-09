# SONAR 0.2: mapa de implementacion y limites

Actualizacion local del 2026-10-09. Solo senales sinteticas de verificacion.
No se modificaron informes cientificos ni repositorios anteriores.

## U0: baseline y compatibilidad

Se inspeccionaron contratos, SDK manual, transporte spawn, GUI Qt, PCA y archivos.
Las 43 pruebas originales pasaron antes de editar (11.84 s). El baseline de carga
se guardo en `artifacts/baseline-v01-20261009.json`; el informe historico se conserva
en `TEST_REPORT_V01.md`. No se extrapolan sus tiempos a la nueva interfaz.

API conservada: `ProbeDescriptor`, `MonitorConfig`, `open_monitor`,
`capture_allowed`, `publish`, `status`, `close`. Contrato CPU float32 y descriptor
v1 sin Torch/Qt al importar SDK. Capturas v1 se pueden abrir con admision; una
referencia entre varias se elige explicitamente al migrar. No se inventan sus
coordenadas historicas.

## U1: presupuesto

`processing/memory.py` y `contracts.py`: configuracion v2, plan inspeccionable,
reservas antes de abrir transporte, pesos por sonda, capacidad aproximada con
contexto vacio. Admision minima calculada, no precision ni k adaptativos.

`history_bytes` explicito sigue siendo cuota de vectores, no presupuesto global.
El total traducido puede exceder 64 MiB; se muestra y puede sustituirse mediante
Aplicar. Las cuotas son autorizaciones de crecimiento, no arrays preasignados.
RSS es un diagnostico separado. El limite no impone un techo al proceso.

## U2: historia y seleccion

`processing/combined.py`: indices FIFO reciente y proyectado por sonda, con
encabezado/contexto compartido. Costes conservadores de objetos y payloads.
Una identidad de captura puede tener varios derivados, cada uno asociado a una
base. Recepcion calcula coordenadas aunque no se dibuje ese cuadro.

`app/state.py`: una referencia y una seleccion fijada bajo reserva; union
navegable, huecos, disponibilidad y 128 eventos maximos. No hay matriz reconstruida.
El gate y los descartes de transporte se distinguen de las evicciones del visor.

## U3: bases y trabajo

Bases afines inmutables float64, hasta k=32, coords almacenadas float32. Nuevo
ID abre segmento, no reemplaza datos viejos. Retirar una base que pertenece a una
seleccion congelada requiere primero volver al presente.

PCA: snapshot admitido, SVD delgado, un worker; nunca covarianza d*d por defecto.
Reproyeccion explicita de hasta 512 IDs en lotes (32 capturas / 6 ms de admision
por lote). Si un vector expira, no se recupera artificialmente. No existe una
cota temporal para un matmul individual. Reconfiguracion in situ, sin duplicar
arrays ni eliminar fijaciones. Transporte nuevo requiere nueva sesion.

## U4: interfaz

Matriz, mapa e historial de disponibilidad en una pantalla. Cada panel se puede
maximizar/restaurar. En Historia maximizada se ven mapa de componentes y trazas;
en Mapa maximizado, scores por eje. Inspector y ajustes de base plegados al inicio.
Controles de memoria con previsualizacion y Aplicar. Fuente sintetica rotulada.

5 Hz por defecto para dibujo, temporizador de recepcion separado de 10 ms con
lotes/tiempo acotados. La frecuencia efectiva depende de Qt/carga de CPU.
Hasta 512 puntos enviados al mapa/historia; detalle de calor hasta 64x64. El
slider recorre toda la union retenida, no solo los puntos visibles. Estos topes
visuales no eliminan capturas del almacenamiento.

## U5: archivos

`storage/mixed.py`: captura mixta v2 parcial, bases y ausencias explicitas;
`storage/capture.py` conserva el decodificador v1. Revision de JSON, cabeceras
NPY y coste previo a arrays. Guardado con admision y escritura ZIP en bloques
de 64 KiB. Importar no amplia presupuesto automaticamente. No hay grabacion
continua; exportar menos capturas o aumentar reserva si la ventana no cabe.

## U6: alcance de verificacion

Pruebas numericas, negativas, persistencia, GUI y API manual en Windows.
Capturas nativas a 1220x800 y 900x650, tiempos de tres paneles y maximizados,
carga comparable con v0.1 y ensayos de diez minutos. Cifras y resultados finales
en `TEST_REPORT.md` y archivos JSON regenerables de `artifacts/`.

## Limites conocidos

- Contabilidad por margenes conservadores, no medicion exacta de cada asignacion
  del heap. Qt, interprete, asignadores, BLAS/LAPACK y temporales opacos externos
  no quedan sometidos al presupuesto. No anunciar un limite duro de RSS.
- Estimacion externa PCA orientativa (copias densas y workspace cuadratico en
  rango), no cota de biblioteca ni porcentaje de informacion retenida.
- Guardar/cargar y algunas tareas de control son sincronicas. Pueden causar
  descartes durante una pausa de recepcion; el productor no espera espacio.
- Reproyeccion de una nueva base es acotada, no reconstruccion de todo el pasado.
  El limite visual, el de reproyeccion y la eviccion son conceptos distintos.
- En modo Detalle las coordenadas de historial se retiran al aplicar la cuota
  proyectada cero. Bases, referencia y seleccion fijada no se borran en silencio.
- Cambiar de descriptor, anadir sondas o cambiar slots requiere abrir sesion.
- Pruebas locales cortas/temporales no certifican dias de funcionamiento.
  Linux, notebooks, modelos reales y GPU siguen sin verificar/fuera de alcance.
