# SONAR 0.2

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

- **Matriz:** valores firmados en bloques de 256; click en celda para inspeccion.
  El indice es `bloque*256 + fila*16 + columna`. Gris indica ausencia, no cero.
- **Referencia:** fija la lectura mostrada; modos original, delta a referencia
  y delta consecutivo. Este ultimo queda no disponible ante huecos o stream nuevo.
- **Congelar:** conserva una unica captura estable y continua recibiendo datos.
  **Vivo** vuelve a la ultima lectura recibida, no a la ultima producida.
- **Historia:** navegacion por la union de vectores y proyecciones retenidos;
  hasta 512 puntos visibles. Al maximizar el panel aparecen el mapa de 64
  componentes sobre hasta 64 capturas y tres trazas. Es un limite visual, no
  una reduccion del historial almacenado. Ejes token/tiempo requieren metadata valida.
  No se unen lineas a traves de perdidas o cambios de stream.
- **Direcciones:** ejes por componentes, importacion de base afin o PCA fija.
  No hay base c0/c1 implicita. Aplicar una base crea un segmento nuevo; conserva
  las bases antiguas hasta retirarlas explicitamente. Hasta 32 ejes, dos visibles.
  La reproyeccion derivada abarca hasta 512 vectores aun retenidos, por lotes.
  La norma completa no se sustituye por la distancia 2D.
- **Guardar:** conserva una ventana parcial, limitada por el control Ventana
  (por sonda), mas la seleccion congelada. Incluye coordenadas sin vector y bases.
  El archivo JSON y su NPZ asociado deben mantenerse juntos.
- **Abrir:** reproduce con pausa, velocidad, pasos y selector de lectura.
  Desde un monitor vivo se abre otro visor independiente.

## Limites y Configuracion

Valores iniciales: 5 Hz de refresco, 16 slots de cola, 1 MiB por muestra y
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
[Contrato](docs/CONTRACT.md) y [Actualizacion 0.2](docs/UPDATE_0_2.md).

## Pruebas

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python tools\verify_ui.py --native
.\.venv\Scripts\python tools\verify_runtime.py
.\.venv\Scripts\python tools\native_soak_v2.py
```

Comprobado en **Windows 11 x64, Python 3.12.14**. Linux sigue pendiente de
validacion real. No se garantiza lanzamiento desde notebooks: usar un script
con guard de entrada para `spawn`.

Incidencia pendiente en la revalidacion: las 67 pruebas pasan, pero el proceso
completo presenta una violacion de acceso nativa al finalizar en Windows.
Las 59 pruebas sin GUI terminan con codigo 0. Detalles y alcance en
[Resultados de verificacion](docs/TEST_REPORT.md).

El extra `torch` es opcional y reservado para una integracion posterior;
no esta instalado ni aporta un adaptador en esta version. Tampoco hay conexion
por red, lectura de servicios solo-texto, grabacion continua ni inferencia semantica.

## Documentacion

- [Diagnostico visual y arquitectura actual](docs/DIAGNOSTICO_VISUAL_Y_ARQUITECTURA.md)
- [Integracion con un programa externo](docs/INTEGRATION.md)
- [Contrato, diferencias y limites](docs/CONTRACT.md)
- [Formato de bases y capturas](docs/FORMATS.md)
- [Registro por fases](docs/BUILD_LOG.md)
- [Resultados de verificacion y limitaciones](docs/TEST_REPORT.md)

## Contenido del Repositorio

Se incluyen codigo fuente, pruebas, ejemplos sinteticos, verificadores y
documentacion. El entorno `.venv`, compilaciones, capturas, archivos numericos
generados y resultados locales de `artifacts/` no se versionan. Los informes de
verificacion mencionan archivos de esas corridas locales que no se distribuyen
con el repositorio; los scripts de `tools/` permiten generar nuevas mediciones.

El repositorio no incluye modelos, activaciones reales ni credenciales. No se
ha definido una licencia de distribucion para esta version.
