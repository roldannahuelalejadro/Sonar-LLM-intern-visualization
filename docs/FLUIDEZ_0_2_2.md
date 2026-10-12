# SONAR 0.2.2: estabilidad y movimiento

Fecha: 2026-10-12. Windows 11, Python 3.12.14. Datos sinteticos; sin modelos
ni dependencias adicionales. Cambios locales sin commit ni push.

## Diagnostico observado

Se leyo el video adjunto de 9.98 s, 1326 x 822 y 30 fps. Los fotogramas muestran
que el aviso de clipping aparece/desaparece y desplaza la matriz. El movimiento
avanza en pasos visibles. El codigo tenia refresco inicial de 5 Hz frente a
unas 30 capturas/s en la demo, y eliminaba/recreaba puntos, curvas y marcadores
en cada render. Los rangos y textos de ejes se recalculaban continuamente.

Una reproduccion nativa con 70 componentes, entrada sintetica de 30 Hz, ventana
1220 x 800 y ocho segundos sobre el paquete 0.2.1 confirmo:

- 4.97 capturas distintas pintadas/s, con p95 de intervalo 219 ms.
- Cuatro geometrias distintas de los paneles sin intervencion del usuario.
- 234 objetos ScatterPlotItem, 117 PlotDataItem y 39 InfiniteLine creados
  durante la ventana de medicion.
- Preparacion de cuadro: mediana 22.95 ms, p95 26.19 ms.

Huella del paquete anterior: `691c73acab408b798141d91dc780be5936bfe865c0e51cd0768dca1d3c1bc63b`.
El paquete se preservo como fixture local antes de modificarlo. Su evidencia
esta en `artifacts/motion-before-5hz.json`. La construccion de objetos se conto
despues de preparar y mostrar el estado inicial.

## Correcciones

- Los objetos de curva, puntos, marcador, cursor y barras se crean una vez y
  reciben datos nuevos. Cambiar el tipo de grafico reutiliza esos objetos.
- Avisos en una fila de altura fija, con texto completo en tooltip. Se prioriza
  la falta de valores calculables en el aviso del historial.
- Rangos numericos estables: se amplian al salir datos de sus limites; el
  contexto/modo nuevo los reajusta. Se conservan los cortes por huecos y series.
- Rotulos, paginas y selectores se actualizan al cambiar su contexto; no se
  reconstruyen por cada captura. Los ejes reservan espacio para sus etiquetas.
- Dos timers precisos de Qt conservan recepcion y dibujo independientes. Los
  contadores visibles se actualizan al dibujar, no en cada poll de recepcion.
- Refresco solicitado inicial de 30 Hz y control visible `Vista Hz` (0.5..60).
  No cambia el gate del productor. Si no hay cambios, se evita redibujar el
  mismo cuadro; el estado temporal sigue actualizandose una vez por segundo.
- Se corrigio la version de la ayuda CLI para que use la version del paquete.

La captura no se sincroniza bloqueando al productor hasta pintar cada muestra.
Con una fuente mas rapida que el dibujo, se conserva su historia bajo cuota y
se muestra la seleccion mas reciente. Una fuente lenta no genera cuadros con
muestras interpoladas. La frecuencia elegida es solicitada, no FPS garantizados.

## Verificacion de la revision final

Huella SHA-256 del paquete cargado:

```text
b35e73e5a6a064d2075d53465ba62956f2b971a8986290d6dd603a14b7801a5e
```

91 pruebas aprobadas, salida 0. Incluyen conservacion de objetos y numero de
items de escena, geometria ante clipping, encuadre estable, nuevos datos tras
idle, independencia de la frecuencia de captura, huecos y modos anteriores.

Verificacion UI nativa: 16 casos, salida 0, en 1220 x 800 y 900 x 650. Se
conservaron las capturas de 0.2.1 y los resultados nuevos se guardaron en
`artifacts/v022/`. No se atribuye el ensayo antiguo de 610 s a esta interfaz;
se usan las pruebas de movimiento y SDK que siguen para su cobertura actual.

Movimiento aislado, misma ventana y datos de 70 componentes:

| Medida | Anterior, 5 Hz | Actual, 5 Hz | Actual, 30 Hz |
| --- | ---: | ---: | ---: |
| Capturas distintas pintadas/s | 4.97 | 5.06 | 27.01 |
| Intervalo p95, ms | 219 | 219 | 53 |
| Preparacion mediana, ms | 22.95 | 23.52 | 16.01 |
| Preparacion p95, ms | 26.19 | 30.56 | 29.06 |
| Geometrias distintas | 4 | 1 | 1 |
| Objetos graficos nuevos | 390 | 0 | 0 |

Duracion: ocho segundos a 5 Hz y 10.11 s a 30 Hz. La prueba actual de 30 Hz
recibio 281 capturas y pinto 274 distintas. La reutilizacion elimino cambios
de geometria y creacion de objetos, pero no redujo el tiempo de preparacion
en la comparacion a igual frecuencia de 5 Hz. La mejora del ritmo resulta
principalmente del nuevo refresco solicitado; no se atribuye toda a esa
optimizacion. Evidencia: `artifacts/motion-after-5hz.json` y
`artifacts/motion-after-30hz.json`.

SDK separado, 45.06 s, ventana 900 x 650 y dos sondas:

| Vista activa | Capturas distintas pintadas/s | Intervalo p95, ms |
| --- | ---: | ---: |
| Cambio consecutivo, 70D | 25.63 | 66.30 |
| Trazas, 4096D | 27.01 | 66.37 |
| Mapa de calor, 4096D | 22.88 | 66.20 |

2616 intentos de publicacion, 2615 aceptados, una perdida por contencion de
transporte, 2609 recibidos antes del cierre y cero mensajes invalidos. Las
capturas aceptadas y recibidas se contabilizan separadamente; no se afirma
entrega completa al cerrar. Salida del visor 0, cero procesos huerfanos y
cero errores del verificador. Memoria gestionada: 16 MiB; RSS maximo observado
del visor: 136.26 MiB, que incluye Qt, Python y otras asignaciones fuera de la
cuota. Evidencia: `artifacts/motion-sdk.json`. Todas estas corridas confirmaron
que el paquete no cambio durante la medicion y coincide con la huella anterior.

## Evidencia y comandos

Los archivos de `artifacts/` son evidencia local ignorada por Git; estos
verificadores permiten reproducirla:

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python tools\verify_ui_v021.py --native --output-dir artifacts/v022
.\.venv\Scripts\python tools\verify_motion.py --hz 30 --seconds 10
.\.venv\Scripts\python tools\verify_motion_sdk.py
```

El verificador de movimiento usa entrada determinista en el mismo event loop
para aislar dibujo/geometria; registra cuadros distintos pintados por la matriz,
duracion de render y construccion de objetos. El de SDK usa un productor en
otro proceso, dos sondas (70D y 4096D), 30 Hz solicitados por sonda y 45 s.
Esas dos mediciones tienen alcances diferentes: no se intercambian sus cifras.

Imagenes actuales:
[PCA en ventana pequena](../artifacts/v022/pca-active-900.png),
[captura solo proyectada](../artifacts/v022/projection-only-900.png),
[replay](../artifacts/v022/replay-900.png).

## Limites

No se verifico Linux, otros DPI o un uso prolongado de dias. El nuevo ensayo
SDK es corto; el de diez minutos anterior documenta la revision 0.2.1. I/O
sincronico y calculos caros siguen pudiendo introducir pausas. No hay promesa
de pintar cada captura con vectores arbitrariamente grandes a 30 Hz.

Las medidas de pintura se toman en Qt; no son tiempo fisico de pantalla ni
sincronizacion con su barrido. La igualdad de frecuencias nominales de captura
y vista no asegura intervalos identicos por planificacion de SO y procesamiento.
El ritmo visual real se registra en los verificadores, separado del solicitado.
