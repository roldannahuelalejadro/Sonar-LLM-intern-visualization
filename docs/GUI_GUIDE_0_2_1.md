# Guia breve de SONAR 0.2.1

Actualizacion de interfaz 0.2.2: `Vista Hz` ajusta el refresco solicitado
(0.5..60 Hz; inicial 30). No cambia la frecuencia de captura del productor.
Con fuentes mas lentas se dibujan sus muestras disponibles, sin interpolar.
Los avisos tienen espacio fijo; pasar el cursor muestra el mensaje completo.
Los rangos numericos se mantienen mientras los datos quepan en ellos, se
amplian al salir y se reajustan al cambiar de contexto/modo. Esto evita el
reencuadre constante; no cambia las coordenadas ni la base.
La frecuencia elegida se aplica a esa sesion y no se guarda como preferencia
visual del archivo. Detalles en [FLUIDEZ_0_2_2.md](FLUIDEZ_0_2_2.md).

## Abrir sin terminal

Doble clic en `SONAR.cmd` para abrir sin fuente, o en `SONAR-demo.cmd` para la
demo sintetica. Requieren el entorno instalado en `.venv` de este proyecto.
Los accesos directos que apuntan a estos lanzadores siguen sirviendo.

Sin fuente se puede abrir una captura, iniciar la demo o consultar el ejemplo
del SDK. SONAR no se conecta por si solo a una LLM. La demo siempre se identifica
como sintetica; sus coordenadas no tienen interpretacion semantica.

## Controles principales

El selector de tema de la barra superior alterna **Laboratorio** (claro) y
**Grafito** (oscuro). La preferencia se guarda localmente para proximas
aperturas, independiente de los archivos de captura. No cambia colores de
activaciones, trayectorias, limites numericos ni frecuencia de captura.

| Control | Efecto |
|---|---|
| Sonda | Cambia el vector/contexto observado; no cambia el productor |
| Pausar vista | Fija una captura; siguen llegando y retirandose datos bajo cuota |
| Volver al presente | Sigue la ultima captura recibida y procesada disponible |
| Fijar referencia | Conserva el vector seleccionado bajo reserva; no basta una proyeccion |
| Guardar captura | Exporta la ventana retenida por sonda y la seleccion protegida |
| Abrir captura | Abre archivo; desde vivo utiliza otro visor independiente |
| Memoria | Previsualiza y aplica presupuesto, reparto y reserva de trabajo |
| Inspector tecnico | IDs, contexto, componentes, normas, tiempos y contadores |
| Boton de cada panel | Maximiza/restaura sin reiniciar seleccion o modo |

La cabecera identifica captura, estado y disponibilidad. Token/capa solo
aparecen si la fuente los declara. Click en un punto del mapa o del historial
fija esa misma captura para todos los paneles. Click en la matriz selecciona
una componente, no cambia de captura.

## Modos de valores

| Modo | Matriz, trazas y calor | Mapa en base fija |
|---|---|---|
| Activacion original | Vector actual | Posicion proyectada |
| Diferencia con referencia | Actual menos referencia | Diferencia de posiciones en la misma base |
| Cambio entre capturas consecutivas | Actual menos secuencia anterior compatible | Desplazamiento proyectado, como puntos |

No se divide por tiempo: cambio no significa derivada temporal. Un hueco o
cambio de serie impide el delta consecutivo. El modo elegido no cambia
silenciosamente si faltan datos: cada panel indica su disponibilidad.

La curva de historial **Cambio entre capturas** conserva su propia definicion
consecutiva en los tres modos: no se calculan diferencias de diferencias.

## Matriz

`Rango de componentes` pagina el vector de 256 en 256; no selecciona una capa.
El gris corresponde a padding o ausencia. Un valor cero pertenece a la escala
numerica y no significa dato perdido. El tooltip identifica componente, valor,
captura y modo.

`Escala +/-` permanece fija hasta cambiarla. El boton a su lado ajusta la
escala a la seleccion actual. `Fuera de escala de color` indica recorte visual,
no saturacion de una neurona. `Usar componente seleccionada en trazas` lleva
esa componente al historial.

## Mapa y PCA

1. Pulsar `Crear mapa PCA`.
2. Elegir ventana y numero de ejes. El dialogo informa sonda, vectores
   compatibles, buffers conocidos y estimacion externa del trabajo numerico.
3. Pulsar `Calcular base fija`. Si no alcanza la memoria, las muestras o el
   rango, se explica el problema y se conserva la base anterior.
4. Elegir Horizontal/Vertical. La base no se recalcula al mover ejes o modos.

El ajuste se ejecuta en un hilo de trabajo; la base queda asociada a la sonda
de origen, aunque se cambie de sonda mientras calcula. No hay cancelacion
inmediata del calculo. Para un plano hacen falta al menos dos ejes de rango
suficiente: dos muestras no garantizan una PCA bidimensional.

`Cargar base` importa el formato affine documentado en `FORMATS.md`. Los nombres
y procedencia son externos, no conceptos certificados por SONAR. En opciones
avanzadas se pueden elegir segmentos, exportar/retirar bases o usar componentes
directas. Esta ultima opcion no es PCA: muestra componentes originales.

Cada base tiene identidad propia. Al seleccionar historia antigua se usa su
base; no se restan coordenadas incompatibles. Una captura con solo proyeccion
puede verse en el mapa sin que eso permita reconstruir la matriz.

En ventanas pequenas el plano queda compacto; redimensionar o maximizar el
panel facilita leerlo, especialmente cuando se muestran avisos de ausencia.

## Historial

La franja superior indica disponibilidad. El selector inferior elige:

- **Cambio entre capturas:** norma L2 completa o proyectada. No es normalizada
  entre modelos, ni una medida de seguridad o significado.
- **Trazas de componentes:** hasta tres componentes en el modo global elegido.
- **Mapa de calor:** componentes frente a capturas, tambien en vista conjunta.

La ventana abarca hasta 512 capturas realmente retenidas. El calor reduce
componentes a 4096 celdas de datos, mas columnas vacias para huecos; el aviso lo
indica y no se recorta por ello el extremo temporal antiguo. Los huecos no se interpolan.
Secuencia es el eje inicial; tiempo/token requieren contexto valido.

Elegir espacio proyectado es explicito: si expira un vector no se sustituye
automaticamente la norma completa por una proyectada. Un plano constante no
demuestra que el vector completo no haya cambiado.

La norma proyectada usa todos los ejes de la base seleccionada; si la base tiene
mas de dos, no equivale necesariamente a la distancia en el plano visible.

## Memoria, archivos y desconexion

Detalle conserva vectores. Combinado reparte la retencion entre vectores
recientes y coordenadas proyectadas; sin base, esta ultima reserva queda
pendiente. El presupuesto administrado no es un limite del RSS total.
Reducirlo puede retirar historia; ampliarlo no recupera datos retirados.

Guardar conserva una ventana parcial, no toda la sesion. Mantener juntos JSON
y NPZ. Reproduccion tiene Play/Pausa, pasos, velocidad y `Ir al final de la
captura`; sus controles no alteran un productor vivo. Los modos principales se
restauran, pero no el tamano de paneles ni todos los ajustes de escritorio.

Una notificacion de desconexion conserva el historial y cambia la cabecera.
El SDK tambien tiene un cierre explicito: `MonitorSession.close()` cierra el
visor por contrato. No existe heartbeat para detectar una muerte silenciosa
del productor, ni reconexion automatica.
