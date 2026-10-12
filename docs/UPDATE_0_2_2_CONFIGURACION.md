# SONAR 0.2.2: configuracion y detalles de la actualizacion

Fecha: 2026-10-12.

Este documento resume los cambios posteriores a 0.2.1: correcciones de
estabilidad visual, control del refresco y temas Laboratorio/Grafito. Describe
la configuracion actual; los presupuestos indicados son valores predeterminados,
no una lectura de la sesion que pueda estar abierta en este momento.

## 1. Resumen de cambios

- Refresco visual inicial de 30 Hz, anteriormente 5 Hz.
- Control `Vista Hz` en la barra superior, ajustable durante la sesion.
- Graficos persistentes: se actualizan sus datos sin destruir y recrear curvas,
  puntos, barras o cursores en cada cuadro.
- Avisos de altura fija: clipping o mensajes largos ya no desplazan los paneles.
  El texto completo se consulta pasando el cursor sobre el aviso.
- Ejes y encuadres estables; los limites se amplian cuando los datos salen del
  rango y se reajustan al cambiar de contexto o modo.
- Textos, paginas y selectores se actualizan cuando cambia su contexto.
- Tema claro Laboratorio y tema oscuro Grafito, con preferencia persistente.
- Iconos de reproduccion y ampliar panel con contraste adaptado al tema.
- Version CLI tomada del paquete: `SONAR 0.2.2`.

No se migro la interfaz a una aplicacion web. Sigue siendo una aplicacion
de escritorio Python, PySide6/Qt y PyQtGraph. No se agregaron dependencias,
modelos descargados ni servicios externos para estos cambios.

## 2. Refresco y recepcion

| Parametro | Valor inicial | Funcion |
| --- | --- | --- |
| `render_hz` / `Vista Hz` | 30 Hz | Frecuencia solicitada de dibujo; intervalo permitido 0.5 a 60 Hz |
| Timer de recepcion | 10 ms | Consulta del canal, independiente del dibujo |
| `capture_hz` | 0 | Sin limite de frecuencia impuesto por el gate del SDK |
| `max_receive_per_tick` | 32 | Maximo de muestras procesadas por consulta |
| `receive_budget_ms` | 8 ms | Presupuesto de trabajo de recepcion por consulta |

Los dos timers utilizan `PreciseTimer` de Qt. Esto mejora su planificacion,
pero no garantiza intervalos exactos ni sincronizacion con la pantalla.

`Vista Hz` no cambia el ritmo del productor. Captura y dibujo permanecen
independientes: el productor no debe esperar a que la interfaz pinte cada
muestra. Si llegan datos mas rapido que el dibujo, la vista puede mostrar la
seleccion mas reciente sin pintar todas las capturas intermedias. La historia
se retiene segun las cuotas de memoria, no indefinidamente.

Si la fuente es mas lenta, no se inventan muestras ni se interpola movimiento.
Cuando no hay cambios se evita redibujar el mismo cuadro; el estado temporal
visible sigue actualizandose aproximadamente una vez por segundo.

La frecuencia elegida es propia de la sesion: no se recuerda automaticamente
en la proxima apertura ni se guarda como preferencia visual de la captura.

## 3. Temas

El selector de la barra superior alterna inmediatamente entre ambos temas.
La primera apertura usa Laboratorio; despues se utiliza la ultima eleccion.

| Elemento | Laboratorio | Grafito |
| --- | --- | --- |
| Fondo general | `#F3F5F7` | `#191C20` |
| Superficie de grafico | `#FFFFFF` | `#24282E` |
| Texto principal | `#20262D` | `#E9EDF2` |
| Texto secundario | `#56616D` | `#A9B3BF` |
| Bordes | `#CDD4DB` | `#454D57` |
| Hover | `#E2F0F2` | `#303D40` |
| Acento | `#167D8D` | `#55C5BD` |
| Aviso de fuente | `#805510` | `#F0C477` |
| Fondo sin datos/padding | `#DCE2E5` | `#343B44` |

El tema cubre controles, menus, dialogos, tooltips, avisos, fondos, ejes,
titulos y leyendas. Los iconos multicolor nativos se conservan; los iconos
monocromos de reproduccion y ampliar panel se adaptan y se reutilizan.

Se mantienen identicos los colores cientificos de las curvas y los mapas,
los limites numericos, las coordenadas, la seleccion y las bases. Cambiar el
tema tampoco modifica el muestreo ni reconstruye los objetos graficos.

La preferencia utiliza `QSettings`, organizacion `SONAR`, aplicacion
`Activaciones`, clave `appearance/theme`. Los valores internos son
`laboratorio` y `grafito`. Una preferencia desconocida vuelve a Laboratorio.
Se guarda localmente mediante Qt, separada de los archivos de captura.
Cada ventana aplica su paleta; una ventana ya abierta no sincroniza su tema
automaticamente cuando se cambia desde otra ventana.

## 4. Memoria y configuracion que se conserva

Estos parametros no se cambiaron al introducir los temas o el nuevo refresco:

| Parametro | Predeterminado |
| --- | --- |
| Presupuesto de datos administrados | 64 MiB |
| Reserva de trabajo | 8 MiB |
| Fraccion reciente | 70% |
| Retencion | `combined` |
| Capacidad de cola | 16 muestras |
| Tamano maximo de muestra | 1 MiB |
| Maximo de segmentos | 8 |
| Limite visual inicial | +/- 1 |

La cuota de datos administrados no es un limite del RSS total del proceso:
Python, Qt y otras asignaciones tambien consumen RAM. Los valores usados en
ensayos concretos pueden diferir de estos predeterminados.

## 5. Abrir y configurar

Sin terminal: doble clic en `SONAR.cmd` o `SONAR-demo.cmd` del proyecto. Los
accesos existentes siguen funcionando con el entorno `.venv` instalado.
Cerrar y volver a abrir el programa carga la interfaz actualizada.

Desde la carpeta del proyecto, si se desea iniciar con otra frecuencia:

```powershell
.\.venv\Scripts\sonar-activaciones --render-hz 20
.\.venv\Scripts\sonar-activaciones --render-hz 30 demo
.\.venv\Scripts\sonar-activaciones --budget-mib 64 --work-mib 8 --recent-percent 70 --retention combined
```

Tambien se pueden ajustar `Vista Hz` y el tema directamente en la interfaz.
No hay actualmente un argumento CLI para elegir el tema: se usa el selector
y su preferencia local.

## 6. Archivos involucrados

| Archivo | Responsabilidad |
| --- | --- |
| `src/sonar_activaciones/app/themes.py` | Paletas, estilos, preferencia local e iconos adaptados |
| `src/sonar_activaciones/app/window.py` | Selectores, timers y actualizaciones de contexto |
| `src/sonar_activaciones/app/views/timing.py` | Avisos estables y rangos de encuadre |
| `src/sonar_activaciones/app/views/history.py` | Curvas, puntos, cursor y mapa de calor persistentes |
| `src/sonar_activaciones/app/views/directions.py` | Trayectoria, marcador y barras persistentes |
| `src/sonar_activaciones/app/views/matrix.py` | Actualizacion de matriz y escala sin reencuadre continuo |
| `src/sonar_activaciones/contracts.py` | Refresco inicial de 30 Hz |
| `src/sonar_activaciones/cli.py` | Valor inicial de CLI y version del paquete |
| `tests/test_motion.py`, `tests/test_themes.py` | Regresiones de estabilidad y temas |
| `tools/verify_ui_v021.py`, `tools/verify_motion.py` | Verificacion visual y movimiento reproducibles |

Los contratos de muestras, el transporte SDK y los formatos de captura no
se modificaron por estas correcciones de fluidez ni por los temas.

## 7. Verificaciones realizadas

Entorno: Windows 11, Python 3.12.14, PySide6 6.11.2 y PyQtGraph 0.14.0.
Se utilizaron datos sinteticos, no activaciones de un modelo externo.

- Revision con temas: 95 pruebas aprobadas, salida 0.
- 32 casos visuales nativos: 16 por tema, en 1220 x 800 y 900 x 650.
- Prueba de 8 s alternando Laboratorio/Grafito: 240 capturas recibidas y
  pintadas, 29.99 actualizaciones/s e intervalo p95 de 47 ms.
- Durante esa prueba: una sola geometria de paneles y cero objetos graficos
  nuevos de los tipos instrumentados.

La revision de fluidez anterior a los temas tambien se midio con productor
SDK separado durante 45.06 s: entre 22.88 y 27.01 actualizaciones/s segun la
vista, una perdida por contencion, cero mensajes invalidos y cero procesos
huerfanos. Esa evidencia corresponde a la revision anterior, no es un nuevo
ensayo SDK realizado despues de incorporar los temas.

La comparacion previa a igual frecuencia de 5 Hz no mostro una reduccion del
tiempo de preparacion del cuadro, aunque elimino cambios de geometria y
recreacion de objetos. No se atribuye toda la mejora de movimiento a una
optimizacion del calculo: el nuevo refresco inicial tambien es determinante.

Estas cifras son mediciones cortas en Qt, no FPS fisicos de pantalla ni
garantias universales. No se verificaron otros DPI, Linux ni uso prolongado
de dias. El ensayo de 610 s de 0.2.1 no valida esta revision de interfaz.

## 8. Documentacion y evidencia

- [Diagnostico y mediciones de fluidez](FLUIDEZ_0_2_2.md).
- [Detalles y reproduccion de pruebas de temas](TEMAS.md).
- [Guia de uso de la interfaz](GUI_GUIDE_0_2_1.md).
- Evidencia local: `artifacts/v022/` y `artifacts/themes/`, ignorada por Git.

La huella del paquete verificado con los temas es:

```text
59316e6104beb8831de2d27b97eb8329bd1c074ab4b35fe47b81a553dfd47956
```

Este documento consolida lo implementado y verificado; no introduce nuevas
funciones ni cambios de codigo. No se hizo commit ni push para esta entrega.
