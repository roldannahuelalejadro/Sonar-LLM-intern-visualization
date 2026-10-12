# Registro de construccion

## Correccion de fluidez 0.2.2, 2026-10-12

Video de uso y reproduccion nativa confirmaron cambios de geometria por avisos
y movimiento escalonado a 5 Hz. Se conservan objetos graficos entre cuadros,
rangos con encuadre estable y filas de avisos; se solicita 30 Hz por defecto
con control visible. Recepcion y captura siguen independientes. Se evita
reconstruir el mismo cuadro sin datos nuevos, salvo actualizacion lenta de estado.
Regresiones de movimiento, objetos, huecos y geometria: 91 pruebas aprobadas.
Evidencia actual y alcance en `FLUIDEZ_0_2_2.md`.

## Actualizacion 0.2.1, 2026-10-10

Seleccion comun y calculos visuales unificados en `processing/display.py`.
Historial de evolucion en vista conjunta, intervalo temporal completo,
PCA visible con contexto de origen protegido, modos afines coherentes y
controles de matriz/ejes mas explicitos. Interfaz nativa Qt, sin dependencias
nuevas, sin modelos y sin cambios al contrato del transporte.

Persistencia visual opcional compatible con capturas anteriores. Regresiones
numericas, GUI, archivos y teardown: 84 pruebas con salida limpia. Evidencia
visual nativa en dos tamanos y comparacion de rendimiento con la misma carga.
Ensayo integrado de 610 s aprobado con salida 0, sin huerfanos y sin cambio de
huella de aplicacion; 222760 capturas recibidas, 36.60% de descartes bajo la carga
de estres. Sus limites se documentan en `TEST_REPORT_0_2_1.md`.
La nueva evidencia incluye hash del codigo cargado, no solo el commit anterior.

## Actualizacion 0.2, 2026-10-09

U0: baseline repetido, 43 pruebas aprobadas; copia de mediciones v0.1 preservada.
U1-U3: presupuesto global, dos historias, fijacion unica, admision y bases por
segmento implementados sin cambiar el SDK manual ni introducir dependencias.
U4-U5: vistas reutilizadas en pantalla unificada, controles explicitos, captura
mixta v2 con lectura v1 y reservas previas a asignaciones numericas.
U6: pruebas nuevas, captura de UI nativa/offscreen, publicacion/procesamiento/
pintura medidos por separado y ensayos de diez minutos. Mapa detallado en
`UPDATE_0_2.md`; resultados finales en `TEST_REPORT.md`.

Se detectaron y corrigieron durante verificacion: vistas ocultas al reparentar,
nombre de QLabel que colisionaba con QWidget.metric y seleccion de segmento
alterada por instalar una base en otra sonda. Se agrego prueba de regresion para
la ultima y comprobaciones de visibilidad para las vistas.
La revision final elimino un ciclo de propiedad del historial y libero capacidad
de indices tras reducir cuotas. Regresion con GC deshabilitado y suite final:
67 pruebas aprobadas. El informe distingue ese ajuste de las cifras del ensayo
temporal anterior.

Lo que sigue conserva el registro historico de la construccion v0.1.

## Fase 0

- Proyecto nuevo `sonar/`, separado de informes y analisis anteriores.
- Python 3.12.14 (Windows x64); entorno `.venv`, sin instalacion global.
- Dependencias estables fijadas, sin descarga de modelos.
- CLI diferida: ayuda e importacion SDK no necesitan Qt ni Torch.

## Fase 1

- `contracts.py`: descriptores, contexto acotado, bytes inmutables float32.
- `processing/`: diferencias compatibles, norma/RMS e historial con eviccion.
- `tests/test_core.py`: fidelidad, incompatibilidad, huecos y limites.
- Los limites contabilizan datos y una reserva conservadora de objetos;
  no representan un limite del RSS total de Python/Qt.
- Comprobacion inicial: 12 pruebas pasadas; instalacion editable y ayuda OK.

## Fase 2

- `session.py`, `transport/local_queue.py`, `examples/manual.py`.
- Cola circular en memoria compartida local: capacidad fija, try-lock,
  descarte entrante por cola llena o contencion. No usa sockets ni feeder threads.
- Proceso hijo `spawn`; cierre con plazo y fallback de terminacion del visor.
- El gate es opt-in, previo a la captura; publicar no lo consulta dos veces.
- Pruebas de consumidor lento/cerrado, FIFO, copia grande y sesiones repetidas.
- Resultado: 16 pruebas nucleo/transporte pasadas en Windows.

## Fase 3

- `app/window.py`, `app/views/matrix.py`, `app/state.py`, CLI y demo por SDK.
- Matriz por bloques de 256 componentes, inspeccion numerica y relleno ausente.
- Escala simetrica fija, contador de saturacion, referencia y congelacion.
- 18 pruebas pasadas, incluida GUI Qt offscreen en su hilo principal.
- Ejecutar `.venv/Scripts/sonar-activaciones demo` (Windows).

## Fase 4

- Historia de hasta 512 lecturas visibles; mapa de 64 componentes desde el
  indice elegido y hasta 3 trazas configurables. Todos los indices son accesibles.
- Ejes secuencia, tiempo relativo y posicion procesada validada.
- Huecos y cambios de stream cortan curvas; huecos ocupan intervalos vacios.
- Congelacion reserva su ventana dentro del mismo presupuesto del historial.
- Historial y presupuesto editables; navegacion sincronizada por secuencia.
- Resultado integrado: 20 pruebas pasadas.

## Fase 5

- `processing/projection.py`: ejes por componentes, base afin externa y PCA fija.
- JSON+NPZ versionados, checksum, validacion de cabeceras/tamanos, sin pickle.
- PCA en un worker separado del hilo Qt, entrada acotada a 16 MiB float64.
- Cada aplicacion explicita cambia el ID de base y reinicia la cola proyectada.
- Desplazamiento completo en metrica original; componente omitida solo con
  base ortonormal, rotulada en metrica transformada cuando hay escala.
- UI: Direcciones, importar/exportar, scores, plano y control de ventana PCA.
- Resultado: 25 pruebas pasadas antes de integrar capturas.

## Fase 6

- `storage/capture.py`: ventana retenida e instantanea, JSON+NPZ numerico.
- Conserva descriptores, secuencias, contextos, referencias, base, escala y perdidas.
- Siempre rotulada como captura parcial; no promete grabacion exhaustiva.
- Reproduccion con play/pausa, velocidad, pasos y navegacion; tiempos relativos.
- Abrir desde una fuente viva crea un visor independiente, sin mezclar datos.
- Limites de archivo antes de cargar arrays, SHA-256 y rechazo de objetos/pickle.
- Comando: `sonar-activaciones replay captura.json`.
- Resultado tras integrar controles: 29 pruebas pasadas. La revision posterior
  amplia casos adversariales y del SDK a 43 pruebas.

## Fase 7

- `requirements-lock.txt`, `README.md`, `docs/CONTRACT.md`, `INTEGRATION.md`,
  `FORMATS.md` y `TEST_REPORT.md` documentan instalacion, uso y restricciones.
- Lanzadores Windows `SONAR.cmd` y `SONAR-demo.cmd`.
- `tools/smoke_sdk.py`: SDK publico y proceso visual real.
- `tools/verify_ui.py`: capturas nativas/offscreen y comprobaciones de pixeles.
- `tools/verify_runtime.py`: carga sintetica, timing separado, cierre y memoria.
- 43 pruebas pasadas; wheel construido; `pip check` sin conflictos.
- Se evito recalcular vistas ocultas tras medir ese coste, conservando refresco
  al seleccionar una pestaña. No se cambio el contrato numerico.
- Windows validado; Linux, notebooks y conexion a motores quedan pendientes.

## Estado de Entrega

Fases 0-7 implementadas e integradas localmente, con pruebas descritas arriba.
Hitos A/B/C cubiertos por el acople manual y las fuentes sinteticas rotuladas.
Fase 8 no implementada: requiere eleccion de motor por parte del usuario.
No se modificaron informes, datos, modelos ni repositorios cientificos anteriores.
No se hizo commit, push ni publicacion remota.

## Documentacion Tecnica Consultada

- PyQtGraph estable 0.14.0: https://pyqtgraph.readthedocs.io/en/pyqtgraph-0.14.0/
- ImageItem: https://pyqtgraph.readthedocs.io/en/pyqtgraph-0.14.0/api_reference/graphicsItems/imageitem.html
- PColorMeshItem: https://pyqtgraph.readthedocs.io/en/pyqtgraph-0.14.0/api_reference/graphicsItems/pcolormeshitem.html
- QTimer y bucle de eventos: https://doc.qt.io/qtforpython-6/PySide6/QtCore/QTimer.html
- Versiones y ruedas verificadas en PyPI: https://pypi.org/project/PySide6/6.11.2/
  y https://pypi.org/project/pyqtgraph/0.14.0/

La documentacion `latest` de PyQtGraph apuntaba a desarrollo; la implementacion
y las verificaciones usan la version estable instalada, 0.14.0.
