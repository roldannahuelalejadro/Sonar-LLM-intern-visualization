# SONAR 0.2: diagnostico visual y arquitectura actual

Documento historico: describe el problema previo a la correccion. Consultar
[UPDATE_0_2_1.md](UPDATE_0_2_1.md) para los cambios y la arquitectura actual.

Fecha: 2026-10-09.

Alcance: revision de las tres capturas de la demo y del codigo actual. Este
documento registra el diagnostico; no implica cambios en el programa ni en su
configuracion. No se ejecutaron nuevas pruebas durante esta revision.

## 1. Resumen del analisis visual

### Historial en la vista conjunta

La vista conjunta no muestra la evolucion de las activaciones: el modo compacto
oculta deliberadamente el mapa de calor y las curvas. Solo queda una linea de
disponibilidad con un punto por captura:

- **Vector:** se conserva el vector original.
- **Proy.:** se conservan coordenadas proyectadas, pero no el vector original.
- **Ambos:** se conservan las dos representaciones.

Por eso los puntos pueden estar todos a la misma altura aunque las activaciones
cambien. Al maximizar el historial reaparecen el mapa de calor y las curvas, como
se observa en la segunda captura.

**Diagnostico:** es una limitacion de diseno de la interfaz actual, no una
restriccion de la demo ni evidencia de un fallo en la adquisicion. La vista
conjunta no satisface la observacion simultanea de la evolucion temporal.

Hay ademas una discrepancia: con una ventana de 128 capturas, la disponibilidad
puede mostrar las 128, pero las curvas y el mapa de calor usan como maximo 64.
Este limite visual no implica que se hayan eliminado las otras capturas.

### Mapa representacional vacio

La demo genera vectores sinteticos de 70 componentes, pero no instala una base
de proyeccion automaticamente. Los mensajes "Sin segmento" y "sin base fija"
indican que todavia no existen coordenadas que el mapa pueda dibujar.

```text
Vector original -> Base fija -> Coordenadas proyectadas -> Mapa
                       ^
            Componentes elegidos, PCA o base importada
```

Maximizar el panel solo cambia su distribucion visual; no calcula una base.
Los selectores visibles `0` y `1` eligen ejes de una base existente, no la crean.

Los controles ya disponibles estan en el ultimo boton del encabezado del mapa,
con aspecto de lista y tooltip "Bases, componentes y PCA". Al desplegarlos se
puede usar "Fijar PCA", "Aplicar componentes" o importar una base compatible.
No se accionaron estos controles durante la revision.

**Diagnostico:** es un estado previsto por falta de configuracion, con un problema
de claridad en la interfaz: los controles necesarios estan plegados al inicio.
Las capturas no aportan evidencia de un fallo del motor grafico.

### Evidencia en el codigo

- `app/views/history.py`: `set_compact` retira las curvas y el mapa de calor;
  `set_frames` representa disponibilidad y `set_data` omite el modo compacto.
- `app/window.py`: `render_history` limita el detalle a 64 capturas; los ajustes
  de base se ocultan inicialmente y `maximize_panel` solo reorganiza paneles.
- `app/views/directions.py`: `set_processed` deja el mapa sin puntos si no hay base.
- `app/main.py`: `run_demo` publica vectores sinteticos sin instalar una base.

## 2. Arquitectura actual

SONAR es un monitor local de vectores. Separa la fuente de datos del proceso
grafico y distingue adquisicion, retencion, procesamiento y dibujo.

### Mapa general

```text
ENTRADA: acceso directo / CLI
  |
  +-- Demo: productor de vectores sinteticos
  +-- Fuente externa: integracion manual mediante el SDK
  |       |
  |       v
  |   MonitorSession [proceso productor]
  |   capture_allowed / publish / status / close
  |       |
  |       v
  |   LocalQueue: cola acotada en memoria compartida
  |       |
  |       v
  |   VISOR [proceso separado: PySide6 + pyqtgraph]
  |       |
  |       +-- Recepcion y validacion de capturas
  |       |
  |       +-- ViewerState: estado comun de los paneles
  |       |     +-- Vectores originales retenidos
  |       |     +-- Bases fijas y segmentos de proyeccion
  |       |     +-- Coordenadas proyectadas retenidas
  |       |     +-- Referencia y seleccion temporal
  |       |
  |       +-- Procesamiento
  |       |     +-- Valores originales y diferencias
  |       |     +-- Proyeccion con la base activa
  |       |     +-- Ajuste PCA en un hilo de trabajo
  |       |
  |       +-- Interfaz
  |             +-- Matriz de la captura seleccionada
  |             +-- Historial temporal y disponibilidad
  |             +-- Mapa representacional
  |             +-- Inspector y controles de memoria
  |
  +-- Abrir captura guardada --------------------> Visor
          Guardar/cargar: JSON + NPZ
```

### Modulos y responsabilidades

Los nombres siguientes son relativos a `src/sonar_activaciones/`.

| Modulo | Responsabilidad |
| --- | --- |
| `cli.py`, `app/main.py` | Inicio normal, demo y apertura de capturas. |
| `contracts.py` | Descriptores de sondas, observaciones y configuracion. |
| `session.py` | SDK publico, publicacion y ciclo de vida del visor separado. |
| `transport/local_queue.py` | Transporte local acotado y contadores de descartes. |
| `app/state.py` | Recepcion, seleccion, referencia, bases y reproyeccion. |
| `processing/combined.py` | Retencion de vectores y proyecciones por sonda. |
| `processing/memory.py` | Presupuesto de datos, cuotas y admision de trabajos. |
| `processing/projection.py` | Bases, proyeccion, ajuste PCA e importacion/exportacion de bases. |
| `processing/reference.py`, `processing/temporal.py` | Diferencias, ejes temporales y tratamiento de discontinuidades. |
| `app/window.py`, `app/views/` | Controles, temporizadores y paneles graficos. |
| `storage/mixed.py`, `storage/capture.py`, `storage/numeric.py` | Persistencia, compatibilidad y validacion de archivos numericos. |

### Flujo y limites relevantes

- **Fuente desacoplada:** la demo usa el mismo SDK y transporte que una fuente
  externa. El SDK recibe vectores CPU; no depende de ejecutar un LLM.
- **Cola acotada:** si no puede admitir una muestra, registra un descarte en vez
  de esperar a que el visor termine de dibujar. La copia del vector tiene coste.
- **Recepcion y dibujo separados:** la interfaz recibe por lotes y dibuja con
  otro temporizador. No mostrar un cuadro no significa no haberlo almacenado.
- **Procesamiento:** la proyeccion habitual ocurre en el proceso del visor;
  el ajuste PCA utiliza un hilo de trabajo. No hay un proceso de proyeccion aparte.
- **Retencion doble:** el vector original y sus coordenadas tienen cuotas
  separadas. Pueden quedar coordenadas de una captura cuyo vector ya expiro;
  esas coordenadas no permiten recuperar automaticamente el vector completo.
- **Bases fijas:** cada base tiene identidad propia. Instalar una nueva abre
  un segmento; no mezcla silenciosamente coordenadas de bases distintas.
- **Memoria:** el presupuesto limita los datos administrados por SONAR, no toda
  la RAM del proceso. Qt, Python y bibliotecas numericas tienen costes adicionales.
- **Persistencia:** se guardan capturas parciales con datos y metadatos retenidos,
  no necesariamente la sesion completa desde su inicio.

### Alcance funcional

SONAR implementa captura, retencion, proyeccion e inspeccion de vectores. No
incluye todavia extraccion automatica de activaciones de un LLM, inferencia de
modelos, estimacion de un Hamiltoniano ni calculo de `D_stat`. Esos analisis
necesitan una integracion o capa adicional; no deben confundirse con lo que la
demo actual demuestra.
