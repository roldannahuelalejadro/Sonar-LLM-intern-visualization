# Verificacion local de SONAR 0.2.1

Informe historico de 0.2.1. Las vistas y el ritmo de refresco cambiaron en 0.2.2;
estas cifras y el ensayo de 610 s no cubren esa nueva interfaz. Ver
[FLUIDEZ_0_2_2.md](FLUIDEZ_0_2_2.md) para las comprobaciones actuales.

Fecha: 2026-10-10. Windows 11 x64, build 26200; Python 3.12.14.
Solo datos sinteticos. No se instalo ni ejecuto una LLM, ni se agregaron
dependencias. Las cifras no son garantias universales de rendimiento.

## Identificacion de la revision

Commit base 0.2: `784eb5b3612325ee6f0e3393ad4a7036b510b822`.
La actualizacion esta en el arbol de trabajo; no se hizo commit ni push.

Huella SHA-256 agregada del paquete de aplicacion realmente cargado:

```text
0.2:   331995230d3b1ef82048430023f30c224058c9a9c3dc2b37fdcff2d42b9310a0
0.2.1: 691c73acab408b798141d91dc780be5936bfe865c0e51cd0768dca1d3c1bc63b
```

`tools/evidence.py` enumera los `.py` del paquete cargado, calcula su SHA-256
individual y agrega el mapa ordenado. Los JSON guardan ambas huellas, version,
Python y plataforma. `git_head` es el HEAD del repositorio al ejecutar, no un
commit que incluya los cambios sin confirmar; la huella identifica esos cambios.
No incluye README, pruebas ni harnesses, que se versionan como herramientas.

## Verificado: suite

84 pruebas aprobadas en 4.79 s en la corrida final; salida 0. La suite anterior 0.2 tenia 67 pruebas y su
revalidacion registraba una excepcion nativa al finalizar. En 0.2.1 se cierran y
destruyen los visores de prueba mientras QApplication sigue viva; las corridas
completas verificadas terminan limpiamente. No se removieron tests para lograrlo.

Cobertura nueva y conservada:

- Diferencias originales, a referencia y consecutivas, incluidos huecos y
  cambios de serie. Referencia contra si misma produce cero.
- Bases afines con centro y escala no triviales; diferencia de coordenadas sin
  doble centrado. No se combinan proyecciones de bases incompatibles.
- Capturas solo proyectadas, ausencia de vector, norma completa no inferida y
  proyeccion al vuelo del vector conservado en modo Detalle.
- PCA con muestras/rango insuficientes; cambio de sonda durante trabajo y
  descarte de resultados cuyo contexto original dejo de ser valido.
- 128 capturas representadas en cambio, trazas y calor; modos globales no
  alteran la definicion de la norma de cambio. Maximizar/restaurar conserva estado.
- Mapa sin base, base de un eje, seleccion de ejes distintos y segmentos antiguos.
- Guardado mixto, carga de formatos anteriores, preferencias validadas y
  navegacion de replay. Reservas, admision, reduccion de cuotas e indices.

No afirmar que esta suite demuestra ausencia de todos los errores de Qt,
memoria o concurrencia posibles.

## Verificado: interfaz nativa

`tools/verify_ui_v021.py --native`: salida 0, 16 imagenes y ningun error del
harness. Dos ventanas de cliente: 1220 x 800 y 900 x 650. Se ejercita el boton y
dialogo PCA con eventos Qt, se espera el trabajo real, se recorren modos,
expiracion de vectores y replay. Los demas estados se preparan mediante la API
de la GUI con datos deterministas. No es una sesion de uso manual exhaustiva.

Se comprobaron tamanos efectivos, colores no uniformes, coordenadas y series
finitas, area de dibujo y extremo temporal antiguo/nuevo. Se inspeccionaron
visualmente capturas de ambos tamanos, incluida ausencia y replay. Con 128
retenidas, la ventana de ejemplo cubre secuencias 29..159: omite 40..42 por un
hueco intencional, no porque se corte el historial a 64.

| Estado | Captura grande | Captura compacta |
|---|---|---|
| Original sin base | [1220](../artifacts/v021/original-no-base-1220.png) | [900](../artifacts/v021/original-no-base-900.png) |
| PCA activa | [1220](../artifacts/v021/pca-active-1220.png) | [900](../artifacts/v021/pca-active-900.png) |
| Referencia | [1220](../artifacts/v021/reference-1220.png) | [900](../artifacts/v021/reference-900.png) |
| Consecutivo | [1220](../artifacts/v021/consecutive-1220.png) | [900](../artifacts/v021/consecutive-900.png) |
| Trazas | [1220](../artifacts/v021/traces-1220.png) | [900](../artifacts/v021/traces-900.png) |
| Calor | [1220](../artifacts/v021/heat-1220.png) | [900](../artifacts/v021/heat-900.png) |
| Solo proyeccion | [1220](../artifacts/v021/projection-only-1220.png) | [900](../artifacts/v021/projection-only-900.png) |
| Reproduccion | [1220](../artifacts/v021/replay-1220.png) | [900](../artifacts/v021/replay-900.png) |

Artefactos locales: `artifacts/v021/ui-verification.json`, PNG y pares JSON/NPZ de
replay. `artifacts/` esta ignorado por Git: los enlaces requieren haber ejecutado
el verificador y no se distribuyen automaticamente en el repositorio publico.

Preparacion de escena en 900 x 650, 15 repeticiones por estado, en ms:

| Estado | Mediana | p95 |
|---|---:|---:|
| Original sin base | 14.92 | 28.74 |
| PCA activa | 19.62 | 26.63 |
| Referencia | 20.03 | 21.71 |
| Consecutivo | 19.02 | 21.77 |
| Trazas | 22.45 | 23.96 |
| Calor | 16.35 | 23.05 |
| Solo proyeccion | 8.08 | 11.01 |
| Replay | 13.69 | 18.27 |

Son muestras cortas locales, no un benchmark estadistico ni FPS. No miden
latencia fisica de pantalla. El plano a 900 x 650 es compacto: mensajes largos
reducen el area util; el redimensionado y maximizacion siguen disponibles.

## Verificado: comparacion con la misma carga

`tools/compare_runtime_v021.py` extrae el paquete del commit 0.2 a una carpeta
temporal y ejecuta **el mismo harness actual** contra ambos paquetes. No cambia
el checkout ni usa un segundo entorno. Baseline fijado al commit anterior; no
se desplaza a otro HEAD cuando se confirma esta actualizacion.

Carga: dimension 4096, 16 slots, refresco solicitado 10 Hz, intento de
publicacion con pausa de 2 ms, cierre de ventana programado a 2.5 s. No hay
ajuste PCA en esta comparacion. El numero efectivo de intentos puede variar por
planificacion del SO. Resultados de la ultima pareja de corridas:

| Medida | 0.2 | 0.2.1 |
|---|---:|---:|
| Publicacion, mediana ms | 0.2471 | 0.2310 |
| Publicacion, p95 ms | 0.6432 | 0.6029 |
| Captura a recepcion, media ms | 6.3364 | 7.7898 |
| Procesamiento por recibida, media ms | 0.0366 | 0.0355 |
| Preparacion de escena, media ms | 11.0079 | 18.0766 |
| Qt paintEvent, media ms | 2.5115 | 3.2152 |
| Captura a pintura instrumentada, media ms | 21.0000 | 27.1579 |
| Intentos / aceptadas / recibidas | 978 / 977 / 972 | 990 / 986 / 985 |
| Descartes de transporte | 1 | 4 |
| Entradas invalidas recibidas | 0 | 0 |
| Salida del proceso visor | 0 | 0 |
| Productor sobrevivio al cierre / procesos huerfanos | Si / 0 | Si / 0 |

Preparar la escena cuesta aproximadamente un 64% mas en esta pareja. La
version nueva dibuja evolucion real donde antes solo habia disponibilidad.
Eso no justifica ocultar el coste: ambos timers comparten el hilo Qt y el
render puede retrasar recepcion. Otra pareja previa dio 12.90 vs 20.50 ms y
5 vs 22 descartes: la variabilidad impide atribuir cada descarte al cambio.

Aceptada significa ingreso a la cola, no necesariamente recibida antes del
cierre. No toda captura recibida se pinta individualmente; el visor muestrea
para dibujar. Los contadores separan estas situaciones de los descartes.

JSON finales: `artifacts/baseline-v02-comparable.json` y
`artifacts/current-v021-comparable.json`. El archivo basico anterior
`baseline-v02-20261010.json` se conserva, pero no se uso como equivalente a este
harness porque no registraba las mismas medidas de procesamiento.

## Verificado: ensayo integrado de diez minutos

`tools/native_soak_v2.py`: **610.109 s, completado, errores [], salida del visor
0, cero procesos huerfanos**. 21 checkpoints. Huella del paquete identica al
inicio y al final, igual a la de las capturas nativas y la comparacion 0.2.1.
No se modifico el codigo de la aplicacion durante el ensayo.

Carga: SDK manual real, tres sondas de dimensiones 70, 4096 y 5120; cola de
cuatro slots de 32768 bytes. Se intentan publicar las tres sondas cada 4 ms,
ademas del tiempo de publicacion. Ventana nativa 900 x 650; cambios de sonda,
modo numerico, tipo de historial, referencia, seleccion congelada, memoria,
base y guardado/carga mixtos cada 30 s. El ajuste PCA se verifica por separado;
este ensayo usa bases directas para ejercitar segmentos y reproyeccion.

| Medida | Resultado |
|---|---:|
| Intentos de publicacion | 351345 |
| Aceptadas / recibidas en checkpoint final | 222764 / 222760 |
| Descartes de transporte | 128581 (36.60%) |
| Cola llena / contencion | 127208 / 1373 |
| Entradas invalidas recibidas | 0 |
| Cambios de base registrados | 14 |
| Vectores retirados conservando proyeccion | 221960 |
| Coordenadas / capturas retiradas | 222922 / 222358 |
| Capacidad administrada comprometida | 8 o 9 MiB, segun reconfiguracion |
| Maximo uso contabilizado del historial en checkpoints | 2.207 MiB |
| RSS del visor observado, minimo..maximo | 126.781..133.234 MiB |
| RSS en checkpoint final | 133.234 MiB |
| Procesamiento por recibida, media | 0.1984 ms |
| Proyeccion por recibida, media | 0.1588 ms |
| Preparacion de escena, media | 24.0875 ms |
| Qt paintEvent, media | 1.8764 ms |

El RSS es independiente de la capacidad administrada; no se declara que el
proceso entero haya usado 8 MiB. Los valores de RSS son muestreos cada 30 s,
no el pico absoluto entre checkpoints. Cada comprobacion valido cuotas de
vectores/proyecciones y capacidad comprometida; las numerosas retiradas
ejercitaron reiteradamente el ciclo de retencion, no un historial vacio.

**La perdida es alta bajo esta carga de estres.** Aprobar el ensayo significa
que el sistema mantuvo sus invariantes y cerro correctamente, no que retuvo
todas las publicaciones. Para observacion con menor perdida se debe regular
la captura usando el gate, adecuar cuota/cola y medir el coste del dibujo; no
se promete que aumentar memoria o bajar refresco elimine los descartes.

Evidencia: `artifacts/native-soak-v021.json`, con checkpoints, contadores,
huellas inicial/final y comprobacion real de salida del proceso hijo. Este
ensayo reemplaza la laguna de cobertura temporal indicada en el reporte 0.2.

## Verificado: instalacion local

Reinstalacion editable 0.2.1 con `--no-index --no-deps --no-build-isolation`,
sin red ni paquetes nuevos. `pip check`: sin dependencias rotas. La ayuda del
entry point instalado responde con salida 0. Los lanzadores existentes siguen
utilizando este entorno; no se crearon nuevos accesos directos ni se publico.

## Inferido, no demostrado

- La mayor preparacion de escena es coherente con el historial ahora visible;
  estas corridas no aislan todos los factores de CPU, Qt o planificacion.
- El cierre limpio tras ordenar el teardown Qt indica que ese cambio resuelve
  la reproduccion local de la suite; no demuestra una causa unica para toda
  excepcion nativa posible.
- Un RSS aproximadamente estable durante minutos no prueba ausencia de fuga
  durante dias ni limita allocations opacas de NumPy/Qt/BLAS.

## Pendiente y limites

- Linux, otros DPI, notebooks y otras maquinas no se probaron nativamente.
- La fuente sigue siendo manual o sintetica; no hay captura de hidden states
  ni interpretacion semantica de ejes en esta actualizacion.
- La desconexion notificada conserva historia; no hay heartbeat. El cierre
  explicito del SDK cierra su visor, no deja una ventana desconectada abierta.
- I/O sigue sincronico y PCA no tiene cancelacion inmediata. Su workspace
  externo no queda garantizado por el presupuesto administrado.
- No se retienen escalares historicos adicionales al expirar vectores: donde
  faltan extremos, falta la norma completa; no se infiere de coordenadas.
- Los modos principales se guardan, no todo el escritorio. Ver `FORMATS.md`.
- Optimizar render y pulir densidad a 900 x 650 sigue siendo trabajo posterior.

## Repetir localmente

Con el entorno ya instalado, desde la raiz del proyecto:

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python tools\verify_ui_v021.py --native
.\.venv\Scripts\python tools\compare_runtime_v021.py
.\.venv\Scripts\python tools\native_soak_v2.py
```

El ultimo comando tarda aproximadamente diez minutos y abre un visor nativo;
no cerrarlo durante la prueba. Ejecutar los ensayos de rendimiento por separado.
