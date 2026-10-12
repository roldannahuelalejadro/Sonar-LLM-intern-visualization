# SONAR 0.2.2

Sonar de Activaciones en Estados de Representacion. Aplicacion local para
inspeccionar vectores CPU producidos por otro programa. No evalua respuestas,
no interpreta semanticamente las coordenadas y no modifica modelos.

Requiere Python 3.12+. SDK: solo NumPy. GUI opcional: PySide6 y PyQtGraph.
No descarga modelos ni utiliza servicios remotos. Las demostraciones son
senales sinteticas, rotuladas como tales.

## Instalacion

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-lock.txt
.\.venv\Scripts\python -m pip install --no-build-isolation -e ".[gui,dev]"
.\.venv\Scripts\sonar-activaciones --help
```

Para Linux, reemplazar `.venv\Scripts\` por `.venv/bin/`.
SDK sin GUI: `python -m pip install .`.

## Abrir

```powershell
.\.venv\Scripts\sonar-activaciones
.\.venv\Scripts\sonar-activaciones demo
.\.venv\Scripts\sonar-activaciones replay .\captura.json
.\.venv\Scripts\python examples\manual.py
```

En esta carpeta tambien estan `SONAR.cmd` (ventana sin fuente) y
`SONAR-demo.cmd` (demostracion sintetica). En Windows se pueden abrir con doble
clic despues de completar la instalacion anterior en esta misma carpeta.
Cerrar el visor no termina el programa productor.

El selector de la barra superior ofrece **Laboratorio** (claro) y **Grafito**
(oscuro). La eleccion se conserva al volver a abrir SONAR. Cambia fondos,
controles, ejes e iconos; no altera las escalas ni los colores de los datos.

## Acople Manual

Ejemplo ejecutable con datos **sinteticos**, no activaciones de una LLM:

```python
import time
import numpy as np
from sonar_activaciones import ProbeDescriptor, MonitorConfig, open_monitor

def main():
    probe = ProbeDescriptor(
        probe_id="vector", name="Ejemplo sintetico", source_id="mi-script",
        capture_point="CPU", dimension=64, selection_rule="vector completo",
        space_id="synthetic/ejemplo-v1", metadata={"synthetic": True},
    )
    with open_monitor([probe], MonitorConfig(capture_hz=30)) as monitor:
        for step in range(600):
            if monitor.status()["state"] != "connected":
                break
            if monitor.capture_allowed("vector"):
                values = np.sin(np.arange(64) / 5 + step / 10)
                monitor.publish("vector", values, {
                    "stream_id": "A", "processed_position": step,
                })
            time.sleep(1 / 30)

if __name__ == "__main__":
    main()
```

Para datos reales, reemplazar la fuente, el descriptor y el `space_id` por los
del programa externo, sin la marca `synthetic`. La captura/reduccion debe ocurrir
**despues** de consultar el gate. No hay un adaptador de modelo implementado.

## Vistas y Controles

- **Matriz:** valores firmados en paginas de hasta 256 componentes; el control
  Rango de componentes muestra los indices. Click para inspeccion y boton para
  usar la componente en trazas. Gris indica ausencia o padding, no cero.
  La escala es fija; su ajuste automatico requiere una accion explicita.
- **Referencia:** fija la lectura con vector disponible. Original, diferencia
  con referencia y cambio consecutivo se aplican a matriz, mapa y trazas.
  El consecutivo queda no disponible ante huecos o cambios de serie.
- **Pausar vista:** conserva una unica captura estable; recepcion y retencion
  continuan. Volver al presente sigue la ultima recibida, no la ultima producida.
- **Historia:** disponibilidad y un grafico de evolucion tambien en vista conjunta.
  Elegir norma de cambio, trazas o mapa de calor. Se cubre toda la ventana pedida
  (hasta 512 capturas retenidas), sin corte temporal oculto a 64. El mapa de calor
  limita las componentes a 4096 celdas de datos, mas columnas vacias para huecos,
  e informa esa reduccion.
  Ejes token/tiempo requieren metadata valida; huecos y series cortan las curvas.
  La norma puede ser completa o proyectada: nunca se sustituyen automaticamente.
- **Mapa:** Crear mapa PCA y Cargar base estan visibles. El dialogo PCA indica
  ventana, ejes, vectores compatibles y memoria estimada. La base queda fija;
  cambiar el modo numerico no la recalcula. Las diferencias se calculan entre
  coordenadas de la misma base, sin volver a centrar el delta.
  Componentes directas queda como diagnostico avanzado, sin base implicita.
  Cada base crea un segmento; hasta 32 ejes, dos visibles con nombres.
  La reproyeccion derivada abarca hasta 512 vectores aun retenidos, por lotes.
- **Guardar:** conserva una ventana parcial, limitada por el control Ventana
  (por sonda), mas la seleccion congelada. Incluye coordenadas sin vector y bases.
  El archivo JSON y su NPZ asociado deben mantenerse juntos.
- **Abrir:** reproduce con pausa, velocidad, pasos y selector de lectura.
  Desde un monitor vivo se abre otro visor independiente.

La [guia de uso 0.2.1](docs/GUI_GUIDE_0_2_1.md) explica modos, botones y ausencias.
En 0.2.2, `Vista Hz` permite ajustar el dibujo entre 0.5 y 60 Hz; el valor
inicial solicitado es 30 Hz. El ritmo real depende de las capturas disponibles
y del coste de dibujo. Los avisos reservan una fila estable y su texto completo
se puede leer al pasar el cursor. Resultados en
[Fluidez y estabilidad 0.2.2](docs/FLUIDEZ_0_2_2.md).
La desconexion notificada conserva el historial. El cierre explicito del SDK
con `MonitorSession.close()` sigue siendo una orden de cierre del visor; no hay
heartbeat ni deteccion automatica de muerte silenciosa del productor.

## Limites y Configuracion

Valores iniciales: 30 Hz de refresco solicitado, 16 slots de cola, 1 MiB por muestra y
**64 MiB globales de datos administrados**. Incluye transporte, copias conocidas,
referencia, seleccion, bases, metadatos y trabajo. Del remanente, 70% para
vectores recientes y 30% para coordenadas. Sin base, la cuota proyectada queda
pendiente. Modo Detalle dedica el remanente al vector completo recibido.

El panel Memoria muestra el impacto antes de **Aplicar**; no reconfigura al mover
el deslizador. Permite ajustar presupuesto, reparto, reserva de trabajo y pesos
por sonda (orden de registro). El inspector tecnico esta cerrado al iniciar.
Los botones de cada panel maximizan/restauran la vista; mapa e historial
seleccionan la misma captura que la matriz. Una captura solo proyectada nunca
se rellena con ceros ni muestra el vector de otra captura.

Compatibilidad: `MonitorConfig(history_bytes=...)` y `--history-mib` conservan
la cuota reciente legada; el total resultante es mayor y se informa. Para fijar
un presupuesto global usar `data_budget_bytes` o `--budget-mib`. No se cambia
el transporte de una sesion activa; sus slots ya fueron asignados.

```powershell
.\.venv\Scripts\sonar-activaciones --budget-mib 64 --work-mib 8 --render-hz 5 demo
```

La cola reserva `queue_capacity * max_sample_bytes` en memoria compartida.
Publicar no espera espacio: devuelve `accepted`, `dropped` o `disconnected`.
Las entradas invalidas generan `ValueError`. Hay conversion declarada a float32.
Las cuotas incluyen margenes conservadores para objetos e indices, no solo
`array.nbytes`. El presupuesto **no limita el RSS** del interprete, Qt,
asignadores o workspace opaco de BLAS/LAPACK. El inspector muestra RSS aparte.
PCA, importacion y exportacion se rechazan antes de sus arrays si no cabe el
trabajo conocido. La estimacion externa de PCA es orientativa, no una cota.
Una base importada o vigente no requiere ajustar PCA. Detalles en
[Contrato](docs/CONTRACT.md) y [Actualizacion 0.2.1](docs/UPDATE_0_2_1.md).

## Pruebas

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python tools\verify_ui_v021.py --native --theme laboratorio --output-dir artifacts/themes/laboratorio
.\.venv\Scripts\python tools\verify_ui_v021.py --native --theme grafito --output-dir artifacts/themes/grafito
.\.venv\Scripts\python tools\verify_runtime.py
.\.venv\Scripts\python tools\compare_runtime_v021.py
.\.venv\Scripts\python tools\native_soak_v2.py
.\.venv\Scripts\python tools\verify_motion.py --hz 30
.\.venv\Scripts\python tools\verify_motion_sdk.py
```

Comprobado en **Windows 11 x64, Python 3.12.14**. Linux sigue pendiente de
validacion real. No se garantiza lanzamiento desde notebooks: usar un script
con guard de entrada para `spawn`.

Las 95 pruebas de 0.2.2 pasan con salida 0. El teardown de pruebas destruye
los visores mientras QApplication sigue viva; la incidencia nativa registrada
en la suite anterior no se reprodujo en esta verificacion. Esto no garantiza
ausencia de fallos nativos en toda configuracion. Resultados, coste adicional de
dibujo y alcance historicos en [Verificacion 0.2.1](docs/TEST_REPORT_0_2_1.md), y
las comprobaciones actuales en [Fluidez 0.2.2](docs/FLUIDEZ_0_2_2.md).

El extra `torch` es opcional y reservado para una integracion posterior;
no esta instalado ni aporta un adaptador en esta version. Tampoco hay conexion
por red, lectura de servicios solo-texto, grabacion continua ni inferencia semantica.

## Documentacion

- [Guia de interfaz](docs/GUI_GUIDE_0_2_1.md)
- [Fluidez y estabilidad 0.2.2](docs/FLUIDEZ_0_2_2.md)
- [Cambios y arquitectura 0.2.1](docs/UPDATE_0_2_1.md)
- [Diagnostico previo 0.2](docs/DIAGNOSTICO_VISUAL_Y_ARQUITECTURA.md)
- [Integracion con un programa externo](docs/INTEGRATION.md)
- [Contrato, diferencias y limites](docs/CONTRACT.md)
- [Formato de bases y capturas](docs/FORMATS.md)
- [Registro por fases](docs/BUILD_LOG.md)
- [Resultados de verificacion y limitaciones](docs/TEST_REPORT_0_2_1.md)
- [Verificacion historica 0.2](docs/TEST_REPORT.md)

## Contenido del Repositorio

Se incluyen codigo fuente, pruebas, ejemplos sinteticos, verificadores y
documentacion. El entorno `.venv`, compilaciones, capturas, archivos numericos
generados y resultados locales de `artifacts/` no se versionan. Los informes de
verificacion mencionan archivos de esas corridas locales que no se distribuyen
con el repositorio; los scripts de `tools/` permiten generar nuevas mediciones.

El repositorio no incluye modelos, activaciones reales ni credenciales. No se
ha definido una licencia de distribucion para esta version.
