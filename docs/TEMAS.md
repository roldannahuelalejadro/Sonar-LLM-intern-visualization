# Temas de SONAR

Selector en la barra superior: **Laboratorio** (claro) o **Grafito** (oscuro).
La eleccion se aplica de inmediato y se recuerda para proximas aperturas.
La primera apertura usa Laboratorio. Una preferencia desconocida vuelve al
tema claro. Es una preferencia local, no se incluye en archivos de captura.

| Color | Laboratorio | Grafito |
| --- | --- | --- |
| Fondo | #F3F5F7 | #191C20 |
| Superficie de grafico | #FFFFFF | #24282E |
| Texto | #20262D | #E9EDF2 |
| Acento | #167D8D | #55C5BD |

La paleta cubre controles, menus, dialogos, avisos, ejes, titulos, leyendas,
fondos de graficos y los iconos monocromos de reproduccion y ampliar panel.
Los iconos multicolor nativos se conservan. Las dimensiones de los controles
son iguales en ambos temas. Los iconos adaptados se reutilizan desde un cache
acotado por tema y simbolo.

No cambia los colores cientificos de curvas o mapas, sus limites, los datos,
las bases, la seleccion ni la frecuencia de captura. No reconstruye graficos.
Las paletas son propias de cada ventana, sin modificar globalmente PyQtGraph.

## Verificacion

95 pruebas aprobadas, incluidas preferencia persistente, fallback, ejes y
leyendas tras cambiar de modo, dialogos, contraste de iconos y preservacion de
datos, limites, objetos y geometria. 16 casos nativos por tema, con ventanas
de 1220 x 800 y 900 x 650. Evidencia local en `artifacts/themes/`, ignorada por Git.

Movimiento con cambio de Laboratorio a Grafito a mitad de una prueba de 8 s:
240 capturas recibidas y pintadas, 29.99 actualizaciones/s, intervalo p95 de
47 ms, una sola geometria de paneles y cero objetos graficos nuevos. Datos
sinteticos, sin SDK ni modelo externo; no garantiza FPS con cualquier carga.

Huella del paquete verificado:
`59316e6104beb8831de2d27b97eb8329bd1c074ab4b35fe47b81a553dfd47956`.

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python tools\verify_ui_v021.py --native --theme laboratorio --output-dir artifacts/themes/laboratorio
.\.venv\Scripts\python tools\verify_ui_v021.py --native --theme grafito --output-dir artifacts/themes/grafito
.\.venv\Scripts\python tools\verify_motion.py --hz 30 --seconds 8 --theme laboratorio --switch-theme --output artifacts/themes/motion-switch.json
```

Los verificadores visuales no escriben preferencias del usuario.
