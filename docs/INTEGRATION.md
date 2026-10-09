# Integracion local

## Instalacion e Importaciones

`pip install .` instala el SDK y NumPy. `pip install ".[gui]"` agrega el visor;
para `open_monitor` el extra GUI debe estar disponible en el mismo entorno.
Importar `sonar_activaciones` no carga Qt, PyQtGraph ni Torch. Qt se importa
dentro del proceso visual. No hace falta ejecutar la CLI antes del SDK.

Python usa `spawn` en todas las plataformas, incluso Linux. Lanzar desde un
archivo `.py` importable con `if __name__ == '__main__':`, no desde `python -c`
ni asumir compatibilidad con celdas de notebook.

## Orden de Operaciones

1. Declarar sondas con espacio y regla de seleccion explicitos.
2. Abrir el monitor una sola vez, fuera del bucle de calculo.
3. Consultar `capture_allowed(probe_id)` antes de reducir/copiar activaciones.
4. Si permite capturar, producir el vector CPU y llamar a `publish`.
5. Revisar resultado y `status()`; usar `close()` o contexto `with` al terminar.

Ejemplo de la parte que se agrega a un programa existente:

```python
if monitor.capture_allowed("h"):
    # Esta funcion pertenece a tu programa y elige explicitamente una lectura.
    vector_cpu = capturar_vector_cpu()
    result = monitor.publish("h", vector_cpu, {
        "stream_id": identificador_de_secuencia,
        "processed_position": posicion_real,
        "stage": fase_real,
    })
```

El gate es opt-in y debe consultarse una vez por intento. `publish` no vuelve a
consultarlo. Sin gate, publicar todos los vectores es valido, pero no ahorra
ninguna reduccion/copia ya realizada. `capture_hz=0` deja el gate abierto.

## Ciclo de Vida

`open_monitor` espera hasta 20 s al arranque de la ventana y falla claramente si
no puede iniciarse. Publicar no espera a que se libere espacio ni a un dibujo.
Hay trabajo CPU finito de validacion, copia y serializacion; no es tiempo cero.
Llamadas de varios threads productores se serializan para proteger la secuencia.

Cerrar la GUI produce estado `disconnected`; publicar despues devuelve ese
resultado. La politica del programa externo sobre continuar o parar es suya.
`close` espera hasta 3 s al hijo y tiene fallback de terminacion/kill del visor;
libera el buffer de transporte y el handle del proceso. No termina el productor.
Use `with` o `try/finally`; no se depende de un destructor de Python.

Una cola aceptada aun no recibida puede perderse al cerrar. No se garantiza
drenaje ni persistencia continua. Abrir una captura desde una ventana viva
inicia otro proceso de reproduccion que no recibe la fuente viva.

## Sin Adaptador de Modelo

No hay hooks Torch, descarga de checkpoints, seleccion automatica de capas ni
tratamiento implicito de batch. `torch` se declara como extra opcional reservado,
no se instala con el lock de v0.1 y no esta validado. La fase 8 se inicia cuando
se elija el motor. Un endpoint solo texto no permite inventar hidden states.
