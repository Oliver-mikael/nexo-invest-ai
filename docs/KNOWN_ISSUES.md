# KNOWN_ISSUES — Nexo Invest AI

Actualizado: 2026-11-02 · Plataforma 2.0 · Motor 0.3.0

Este documento recoge las limitaciones **reales y comprobadas** del sistema, no las que
existían en ciclos anteriores. Lo que ya está resuelto no se repite aquí.

## Cartera real multimercado (2.0)

- **Los proveedores automáticos cubren divisas, precios históricos y fundamentales
  (fase 5); dividendos, noticias, eventos y calendarios siguen sin proveedor.**
  La valoración de la cartera sigue pudiendo usar cotizaciones manuales o importadas; los
  datos de proveedor entran por `POST /api/v1/data/sync/*` con `source`, `as_of` y `quality`.
  No se presenta un precio retrasado como tiempo real; la nueva columna `quote_quality`
  aparece en cada posición de la cartera real.
- **El OCR no está verificado de extremo a extremo en este workspace** porque el binario
  `tesseract-ocr` no está instalado. La lógica de extracción, el flujo de revisión y la
  confirmación están implementados y probados con un extractor simulado; el contenedor
  instala Tesseract. Si falta, la API devuelve 503 y no finge una extracción.
- **No hay APK Android.** La PWA es instalable, pero Capacitor no se ha generado ni probado
  en dispositivo/emulador; no se declara un APK inexistente.
- **No hay alertas ni notificaciones.** La recopilación de datos ya tiene su propia cola
  ligera en proceso (`DataSyncRunner`, con recuperación y anti-duplicados), pero sigue sin
  haber workers independientes para la investigación, scheduler de alertas ni avisos
  PWA/Android. La cola actual es un `ThreadPoolExecutor` en proceso y no sirve para varias
  réplicas: eso es trabajo de la fase 6.
- **No hay ejecución de órdenes ni conexión con brókers.** El nombre del bróker es texto; no
  se guardan credenciales. La plataforma es de seguimiento y registro.
- **TWR depende del histórico de precios/divisas.** Si falta una valoración en una fecha de
  aporte, se devuelve `twr_available: false` con el motivo; no se interpola ni se usa el
  coste como mercado. XIRR necesita al menos un flujo de cada signo.
- **Traspasos entre divisas distintas** no se compensan automáticamente en el consolidado:
  cada cuenta los ve como flujo externo en su moneda base. Los traspasos de la misma divisa
  sí se compensan.
- **La consolidación no suma monedas distintas.** El overview agrupa por divisa base; no hay
  un total único multi-divisa sin un tipo de cambio explícito y una fecha de conversión.
- **SQLite no es una base contable exacta a nivel de almacenamiento.** Los cálculos usan
  `Decimal`, pero SQLite guarda con afinidad numérica. Para producción contable, PostgreSQL
  con `Numeric` es el entorno previsto.
- **El tipo de cambio histórico** puede venir del usuario, del importador o de la
  sincronización de divisas (Frankfurter, histórico con `force` para corregir). No se
  corrige retroactivamente en silencio: cualquier sustitución queda registrada como
  anomalía en el run con el valor anterior y el nuevo.
- **La importación no guarda el archivo original**, solo el hash y las filas normalizadas de
  la previsualización. Para auditoría documental de importaciones hará falta una fase
  posterior.
- **No hay pruebas de navegador.** La interfaz se verifica con TypeScript y build, no con
  Playwright ni capturas automatizadas. Afecta también a la página `/datos`.

## Datos automáticos (fase 5)

- **Precios solo en US, DE, ES y GB (verificados).** StockAnalysis devuelve error explícito
  para el resto (LATAM incluida): no se sustituye por otro mercado ni se inventa un precio.
  Su API es **no oficial y sin clave**: puede cambiar, requerir credencial o limitar acceso;
  los términos asumen uso personal sin redistribución (caché propia, sin reexposición).
- **StockAnalysis no es el tape oficial ni tiempo real:** solo cierres diarios `close`. El
  cierre sin ajustar y el ajustado se guardan aparte y no se mezclan.
- **Frankfurter publica fecha de calendario, no instante intradía:** `as_of` es la fecha del
  dato. Los datos son diarios (`close`), jamás `realtime`. Las consultas pinneadas a un
  proveedor concreto (p. ej. BCBO) quedan sujetas a los términos de esa fuente.
- **ExchangeRate-API es una tasa agregada de mercado:** se guarda con `kind=market` y en
  Bolivia no se presenta como oficial. Sus términos exigen atribución y prohíben
  redistribuir: solo se almacena para uso interno. 1 petición/24 h recomendada (429 con
  bloqueo de 20 min si se excede); la caché con TTL evita el abuso.
- **Las divergencias entre fuentes se registran, no se resuelven.** Si Frankfurter y
  ER-API difieren más del 3 % para el mismo par y fecha, se guarda la anomalía con ambos
  valores y fuentes; el sistema no elige «la tasa correcta».
- **Durante la vigencia de la caché no se reconsulta** (60 min divisas actuales, 20 h
  históricos y precios): el dato en pantalla puede tener hasta esa antigüedad además de la
  fecha real que ya muestra.
- **Fundamentales solo para emisores con CIK (EDGAR, EE. UU.).** EBITDA y flujo de caja
  libre quedan en `null` porque la fuente no los publica como concepto; no se calculan y se
  presentan como reportados. El resto de mercados se declara «no disponible».
- **Sin proveedor de noticias, eventos ni calendarios.** El catálogo lo marca
  `configured: false` y `GET /data/news` devuelve `available: false` con el motivo.
- **El planificador está apagado por defecto** (`NEXO_DATA_SYNC_INTERVAL_MINUTES=0`): no
  hay recopilación automática sin que se active explícitamente. La anti-duplicación por
  `task_key` protege dentro de un proceso; entre varias réplicas queda una carrera
  documentada hasta que haya un índice único y una cola compartida (fase 6).

Las limitaciones históricas del motor financiero (procedencia, TTM, valoración, backtesting)
se mantienen y se listan a continuación.

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

## Seguridad de red y sesiones

- **Los límites por IP necesitan conocer el proxy.** La identidad del cliente sale de la
  conexión TCP; `X-Forwarded-For` solo se cree si la conexión llega de una red declarada en
  `NEXO_TRUSTED_PROXIES`. Desplegado detrás de nginx, Traefik o un balanceador sin declarar
  esa variable, todos los clientes comparten el cupo de la IP del proxy: el límite se vuelve
  más estricto, nunca más laxo. Es el comportamiento seguro por defecto.
- **Cerrar sesión revoca la sesión actual, no todas.** El resto de dispositivos siguen
  autenticados hasta su TTL (`NEXO_SESSION_TTL_HOURS`, 72 h por defecto). No hay botón de
  «cerrar todas las sesiones» ni revocación al cambiar la contraseña.
- **El cierre de sesión local no depende de la red.** El navegador elimina el token antes de
  llamar al servidor; si la revocación falla, el token caduca por TTL en el servidor y el
  usuario queda fuera en ese navegador de inmediato.

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
