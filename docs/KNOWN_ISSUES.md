# KNOWN_ISSUES — Nexo Invest AI

Actualizado: 2026-10-31 · Versión: 0.3.0

Este documento recoge las limitaciones **reales y comprobadas** del sistema, no las que
existían en ciclos anteriores. Lo que ya está resuelto no se repite aquí.

## Limitaciones del entorno

- ~~`venv` no disponible~~: **resuelto y comprobado el 2026-10-31**. `python3 -m venv` funciona;
  una copia limpia del repositorio (exportada con `git archive`) se instaló con
  `pip install -e ".[dev]"` en un entorno virtual aislado y ejecutó las 391 pruebas sin
  depender del workspace.
- Sin programación persistente de tareas: no hay demonio ni servicio que ejecute
  `scripts/update_reports.sh` solo. Se lanza a mano o desde el programador del sistema del
  usuario (`cron`, `systemd timer`, Programador de tareas). **No existe automatización diaria.**
- El hosting de Freebuff compila con Node, no con Python: el producto no se despliega ahí como
  servicio web. El entregable es la CLI y los informes que genera.

## Datos y procedencia

- **La corroboración sigue sin ser una fuente primaria independiente.** Desde el Ciclo 3
  hay dos tipos y hay que distinguirlos:
  - *intra-fuente*: dos rutas internas del mismo documento coinciden (concepto XBRL
    alternativo o suma de cuatro trimestres reales).
  - *entre proveedores*: SEC EDGAR y Nasdaq publican la misma cifra para el mismo periodo,
    o Yahoo y Nasdaq dan el mismo cierre para la misma fecha.
  Ambos comprueban la **cadena de distribución**, no que la cifra fuera correcta en origen:
  todas las cifras públicas proceden de la presentación de la empresa. Para confirmar el
  origen haría falta el documento HTML original de la SEC o los datos publicados por la
  propia empresa en su web.
- **La unidad de Nasdaq no la declara su endpoint.** La relación (miles de USD) se infiere
  por contraste con la fuente primaria y se registra como inferida. Si ninguna potencia de
  diez alinea, el resultado es discrepancia, no coincidencia.
- **La segunda fuente no responde siempre.** Se observó un corte silencioso (timeout) en
  `api.nasdaq.com` cuando el `User-Agent` incluía una URL de contacto; verificado con
  peticiones repetidas. Un fallo de la fuente secundaria deja el contraste en
  `incomparable` y la cifra primaria **no** se promueve.
- Una respuesta HTTP correcta solo autoriza el nivel `EXTERNAL_DOWNLOADED`. El sistema no
  presenta ese nivel como dato verificado.
- El modelo de procedencia no rechaza automáticamente monedas incompatibles fuera de los
  cálculos que sí validan escala: registra la moneda real y deja la decisión al consumidor.
- Los precios vienen de Yahoo Finance y Nasdaq, **agregadores**: ninguno es el mercado
  oficial ni el SIP. La comprobación cubre una fecha concreta, no toda la historia.
- Sin precio comprobado no se calcula margen de seguridad y `can_recommend` es siempre
  `False`. Esto es una decisión de diseño, no un defecto pendiente de arreglar.

## Cálculos

- `ROIC` clásico (`operating_income / invested_capital`) queda en `None` si la empresa no
  reporta capital invertido. El indicador que sí se calcula es `roic_nopat`, con capital
  invertido **estimado** (deuda total + patrimonio) y marcado como estimación.
- La deuda total se suma desde sus componentes. Si falta alguno, la nota dice que la cifra es
  un mínimo; no se completa el hueco con una estimación silenciosa.
- La deuda neta resta caja e inversiones corrientes, pero **no** inversiones a largo plazo: en
  empresas como Apple la deuda neta queda sobrestimada. Está anotado en el informe.
- `free_cash_flow` no existe como concepto XBRL estándar único. Se calcula como
  flujo operativo − |inversiones| y se marca `free_cash_flow_estimated=True`.
- Concentración de clientes y rotación de capital no son calculables con la fuente usada: los
  `companyfacts` no publican segmentos ni desglose de clientes.
- Los periodos con el mismo cierre y distinta duración comparten clave en `FinancialState`: se
  conserva uno solo (sobrescritura documentada).

## TTM y periodos

- TTM es `None` cuando la fuente no publica el cuarto trimestre como periodo independiente
  (caso real de Apple en sus 10-K/10-Q). Se explica y no se rellena con acumulados YTD.
- `ttm_periods` exige duración trimestral real (80-100 días) y diferencia entre cierres dentro
  del rango documentado: un trimestre atípico rompe la secuencia y deja TTM en `None`.
- La regla de año fiscal (`finish.month <= close_month => finish.year`, si no `+1`) es una
  convención, no la única posible. Está documentada para evitar ambigüedad.
- Sin calendario fiscal adjunto, el crecimiento compara con el periodo anterior más reciente de
  la misma frecuencia, que puede no ser el año fiscal anterior.

## Valoración y estrategias

- Con los supuestos actuales el DCF deja a Apple por encima de su precio en los tres
  escenarios (margen de seguridad de −519 % a −76 %). **No es una conclusión de sobreprecio**:
  es el resultado de aplicar un descuento que no tiene en cuenta la rentabilidad del
  negocio (ROIC ~65 %) ni la calidad de la marca. Un descuento del 8,5 % para Apple es una
  suposición discutible, y el informe lo dice.
- Los comparables son un modelo con criterios documentados, pero **no hay comparables reales**:
  sin precios ni múltiplos de mercado verificados, no se calculan múltiplos aplicables.
- Los escenarios bajista/base/alcista son sensibilidad a supuestos, no predicciones. El escenario
  base no es una previsión.
- La estrategia táctica no está lista: exige series de precios verificadas, volatilidad y reglas
  de entrada/salida que hoy no se pueden sostener con datos contrastados.
- La estrategia de valor clasifica por calidad y endeudamiento, no por precio. Cumplir los seis
  criterios no equivale a una señal de compra y el informe lo dice en cada empresa.

## Pruebas históricas

- Un solo activo (AAPL) y un solo periodo de cinco años. No hay evidencia de generalización.
- Sin corrección por comparaciones múltiples: cambiar de activo o de periodo cambia el resultado.
- No se modelan impuestos, dividendos cobrados en efectivo (van dentro del precio ajustado),
  liquidez real de las órdenes ni eventos corporativos distintos de los ajustes de precio.
- Hay una prueba automática de ausencia de sesgo de anticipación, pero no sustituye una
  validación walk-forward con múltiples activos.
- El resultado real obtenido (65,07 % frente a 132,90 % de buy & hold tras corregir el
  reparto de los costes de entrada, antes publicado como 133,25 %) muestra que la regla
  **no** supera a mantener el activo. No se oculta ni se reencuadra; el dato anterior
  queda documentado en CHANGELOG y DECISIONS para que la corrección sea rastreable.
- La auditoría (`audit_backtest`) recalcula cada cifra publicada con fórmulas aparte y
  repite la ejecución sobre la serie recortada. Eso comprueba estas cifras concretas, no
  la bondad de la estrategia.

## Qué queda por hacer (priorizado)

1. **Fuente primaria independiente**: documento HTML original de la SEC, otro registrador
   o los datos publicados por la propia empresa. Es lo único que puede confirmar que la
   cifra es correcta en origen y no solo bien transmitida.
2. Precio de una fuente oficial en **una segunda fecha** además de la comprobada
   (2026-10-27), para no depender de un único cotejo.
3. Segmentos y concentración de clientes desde el 10-K o los datos XBRL de segmentos.
4. Ampliar la prueba histórica a varios activos y periodos con corrección por comparaciones
   múltiples y un índice de referencia adecuado.
5. Seguimiento de cartera: requiere posiciones y transacciones reales del usuario o una
   cartera explícitamente simulada.

## Bloqueos

- Ningún bloqueo que impida continuar el desarrollo local.
- Lo que falta es **una fuente primaria independiente y precios de mercado oficiales**, no
  capacidad técnica: el adaptador, el contraste, la valoración y la auditoría están
  preparados para recibirlos. La segunda fuente (Nasdaq) ya está conectada, pero aclara la
  distribución, no el origen.
