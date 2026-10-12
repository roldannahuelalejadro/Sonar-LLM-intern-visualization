# SONAR 0.2.1: correcciones de visualizacion

Fecha: 2026-10-10. Fuentes sinteticas exclusivamente. Sin experimentos ni LLM.

## Punto de partida

Se inspecciono el codigo de 0.2, no solo las capturas del diagnostico.

| Estado anterior | Cambio |
|---|---|
| Historial conjunto mostraba solo disponibilidad | Un grafico de evolucion elegido por el usuario permanece visible |
| Detalle temporal recortado a 64 | Intervalo completo de la ventana, con limite de celdas explicitado en calor |
| Mapa vacio con acciones plegadas | Crear PCA/importar visibles y estado sin base accionable |
| Ejes numericos y Bloque | Nombres de ejes y Rango de componentes |
| Modos incompletos entre paneles | Calculos compartidos, incluyendo diferencias afines del mapa |
| PCA dependia de la sonda seleccionada al terminar | Resultado vinculado al estado y descriptor originales |
| Estado visual parcial y no validado de modo uniforme | Campos opcionales acotados y compatibles con v1/v2 |
| Suite aprobaba pero podia fallar al salir de Qt | Teardown de visores antes de destruir QApplication |

## Arquitectura actual

```text
Programa externo / demo sintetica                 Proceso productor
  ProbeDescriptor + MonitorConfig
  MonitorSession: capture_allowed -> publish
       |
       v
  LocalQueue: slots en memoria compartida, acotados
       |
       v
MonitorWindow                                    Proceso visor / hilo Qt
  receive_timer -> recepcion, validacion, ViewerState
  timer         -> resultado PCA, reproyeccion, render y navegacion
       |
       +-- ViewerState: sonda, captura, referencia y base seleccionadas
       |     +-- CombinedHistory: vectores y coordenadas bajo cuotas
       |     +-- segmentos de base fija + referencia/seleccion protegidas
       |     +-- MemoryPlan / WorkBudget: admision y reservas
       |
       +-- processing/display: calculos de presentacion de solo lectura
       |     +-- matriz: valores / referencia / consecutivo
       |     +-- mapa: posiciones / diferencias en la misma base
       |     +-- historial: cambio L2 / trazas / calor
       |
       +-- GUI: seleccion central -> todos los paneles + inspector
       +-- storage: guardado/carga JSON + NPZ, admision previa
       |
       +-- ThreadPoolExecutor                    Hilo trabajador PCA
             fit_pca(snapshot compatible)
             resultado -> instalacion en contexto de origen valido
```

Los dos timers pertenecen al mismo hilo Qt. Separar temporizadores no permite
render y recepcion concurrentes: un render lento o I/O sincronico puede retrasar
el vaciado de la cola. El productor es un proceso distinto y no espera espacio;
los descartes siguen siendo parte del contrato y se muestran.

No se reescribieron SDK, transporte, retencion ni formatos numericos. Se agrego
un modulo pequeno de calculos visuales para evitar que cada panel interprete
de manera diferente referencias, predecesores o bases.

## Reglas conservadas y reforzadas

- Una sola captura seleccionada alimenta matriz, mapa, historial e inspector.
- Un delta consecutivo requiere la secuencia inmediatamente anterior y serie
  compatible; no basta el ultimo punto que quede en pantalla.
- Diferencia proyectada significa restar dos posiciones de una misma base.
  El centrado affine no se aplica otra vez al vector diferencia.
- Una proyeccion retenida no habilita un vector, una norma completa o una
  referencia completa inexistentes. La ausencia no se rellena con cero.
- Las proyecciones calculadas al vuelo a partir de vectores conservados son
  derivadas de visualizacion; no cambian silenciosamente el registro historico.
- Cambiar ejes o modo no reajusta PCA. Los segmentos antiguos siguen separados.
- La curva de norma consecutiva no depende del selector de modo de valores.
- Los limites de dibujo afectan componentes/celdas, no el intervalo temporal.

## Cambios por modulo

| Archivo | Responsabilidad del cambio |
|---|---|
| `processing/display.py` | Reglas numericas de valores, disponibilidad, series y normas |
| `app/state.py` | Predecesor exacto, seleccion historica y base correspondiente |
| `app/window.py` | Controles, dialogo PCA, origen del trabajo, estados y persistencia visual |
| `app/views/history.py` | Disponibilidad compacta y evolucion elegible sin truncado temporal |
| `app/views/directions.py` | Modos del mapa, ejes, ausencia, rango constante y seleccion |
| `app/views/matrix.py` | Tooltip y rotulos legibles |
| `processing/projection.py` | Nombres de componentes directas |
| `storage/mixed.py` | Validacion acotada de preferencias visuales |
| `tests/conftest.py` | Ciclo de vida Qt de las pruebas |
| `tests/test_display_v021.py` | Regresiones numericas, GUI, PCA y archivos |
| `tools/evidence.py` | Huella reproducible del codigo realmente cargado |
| `tools/verify_ui_v021.py` | Estados nativos, screenshots y mediciones en dos tamanos |
| `tools/compare_runtime_v021.py` | Mismo harness contra codigo del commit 0.2 y codigo actual |
| `tools/native_soak_v2.py` | Ensayo integrado 610 s con huella inicial/final y cierre verificado |

## Interfaz incremental

Se conserva PySide6/PyQtGraph. La mejora inicial usa controles Qt, iconos
estandar, tooltips, una barra de acciones con texto y ajustes pequenos de estilo
y espacio. No se instala Node ni se agrega un frontend web en paralelo.

Una etapa posterior puede ajustar densidad, tipografia y lectura a pantallas
pequenas sobre estos mismos componentes. Antes de cambiar tecnologia conviene
medir perfiles de dibujo: en la comparacion actual, mostrar evolucion en vivo
cuesta mas que la franja de disponibilidad anterior.

## Alcance pendiente

No se implementaron deteccion por heartbeat, reconexion, cancelacion inmediata
de PCA, I/O asincronico, grabacion continua ni adaptadores de LLM. El cierre
explicito del SDK sigue cerrando su visor. Linux, notebooks y escalas de pantalla
distintas de las locales no tienen verificacion nativa en esta entrega.

La guia practica esta en [GUI_GUIDE_0_2_1.md](GUI_GUIDE_0_2_1.md). Evidencia,
costes y limites de las pruebas en [TEST_REPORT_0_2_1.md](TEST_REPORT_0_2_1.md).
