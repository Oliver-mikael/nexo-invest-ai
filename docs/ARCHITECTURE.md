# ARCHITECTURE — Nexo Invest AI

Versión actual: 0.3.0

## Propósito

Motor de investigación y valoración de inversiones verificable, escrito en Python,
orientado a análisis fundamental, valoración y generación de informes reproducibles.

La plataforma 2.0 añade una cartera real multimercado sobre el motor y el backend v1. El
motor financiero (SEC EDGAR, métricas, DCF, backtest) no se reescribe: se consume como
biblioteca.

## Plataforma multimercado (2.0)

### Capas nuevas

- `app/services/accounting.py` — libro contable puro, sin acceso a base de datos. Trabaja
  con `Decimal`, `LedgerMovement` y `InstrumentInfo`. Implementa FIFO y coste medio,
  dividendos, comisiones, impuestos, splits, traspasos, valoración, XIRR y TWR.
- `app/services/real_portfolio.py` — carga y valora una cuenta con cotizaciones y tipos de
  cambio visibles para el usuario; agrupa el consolidado por moneda base y distribuye por
  mercado, país, tipo de instrumento y divisa.
- `app/services/real_movements.py` — normaliza y valida altas y correcciones. Reproduce el
  libro completo con el candidato antes de guardar; impide sobregiros, ventas en corto no
  autorizadas y duplicados.
- `app/services/imports.py` — CSV/TXT/XLSX, detección de columnas, normalización de fechas y
  decimales, detección de duplicados y confirmación por lotes.
- `app/services/ocr.py` — extracción local con `pypdf` o Tesseract. Devuelve una propuesta
  con `review_required: true`; nunca registra un movimiento.
- `app/api/v1/markets.py`, `real.py`, `imports.py`, `documents.py` — API v1 con aislamiento
  por usuario, límites de peticiones y auditoría.
- `web/src/pages/RealPortfolio.tsx` y `web/src/components/real/*` — resumen, movimientos,
  importación y documentos en la PWA.

### Modelo de datos

- **Referencia:** `markets` (código MIC, país, divisa, zona horaria), `instruments` (`uid`
  estable, mercado + símbolo único, ISIN cuando existe), `quotes` y `fx_rates`. Las
  cotizaciones y tipos con `user_id` nulo son de proveedor (globales); las manuales son del
  usuario y no afectan a terceros.
- **Cartera real:** `real_accounts`, `real_movements`. No comparten tablas con
  `portfolios`, `positions` ni `trades` de la cartera simulada.
- **Registro:** `import_batches` (vista previa y estado) y `documents` (archivo privado,
  SHA-256, extracción y vínculo al movimiento confirmado).
- `documents.storage_key` es aleatorio y el directorio queda fuera de `web/dist`; nunca se
  sirve como estático.

### Reglas contables

1. **Decimal, no float.** La API acepta cadenas decimales y Pydantic las convierte a
   `Decimal`. SQLAlchemy usa `Numeric(28,10)` / `Numeric(24,10)`. SQLite almacena con
   afinidad numérica; PostgreSQL conserva la precisión exacta. Los cálculos del motor son
   siempre `Decimal`.
2. **Efectivo en moneda base.** Cada movimiento se convierte con su `fx_rate` histórico y
   el efectivo de la cuenta se lleva en su moneda base. No se recalcula una operación con
   el tipo de cambio actual.
3. **FIFO y coste medio.** El motor mantiene ambos: los lotes FIFO y una bolsa de coste
   medio. La cuenta elige el método principal; las pruebas numéricas fijan el resultado de
   ambos. Las comisiones de compra se capitalizan en el coste; las de venta reducen el
   importe neto.
4. **Traspasos a coste.** Un traspaso de valores sale del libro por el coste realmente
   retirado (no por un importe declarado) y entra por el coste declarado en la otra cuenta.
   Un traspaso de efectivo no crea capital: se registra como flujo externo en cada cuenta y
   se compensa en el consolidado de la misma divisa.
5. **Sin precio no hay valor.** Si falta una cotización o un tipo de cambio, la posición se
   marca como no valorada y el total se devuelve como parcial. No se usa el coste como si
   fuera mercado.
6. **Resultado y aportes separados.** Aportes, retiros, ajustes de conciliación y traspasos
   son flujos externos para XIRR/TWR. Dividendos, comisiones e impuestos son resultado.
   `net_gain = valor final − aportes netos`.
7. **XIRR** anualiza con base 365 y bisección sobre flujos fechados; **TWR** encadena
   subperiodos entre flujos usando valoraciones completas a cada fecha. Si el histórico de
   precios/divisas no cubre una fecha, TWR se declara no disponible con el motivo.
8. **Atribución cambiaria.** En una posición abierta, el efecto precio es la ganancia local
   valorada al cambio actual y el efecto cambiario es `coste_local × (cambio_actual − coste_base/coste_local)`.
   En una venta, el efecto precio usa el cambio de la venta y el resto es efecto cambiario.

### Aislamiento y seguridad

- Toda consulta de cuentas, movimientos, lotes y documentos filtra por `user_id`; un recurso
  ajeno responde 404.
- Las cotizaciones y tipos manuales incluyen `user_id`; las globales solo las crea el
  sistema/proveedor.
- Los documentos se validan por firma real (PDF/JPEG/PNG/WebP), tamaño máximo y nombre
  saneado. La descarga exige token y pertenencia.
- Un documento vinculado a un movimiento confirmado no se puede borrar. Borrar un
  movimiento exige que el libro restante siga siendo válido.
- Nunca se guardan contraseñas de brókers ni claves de IA en el frontend.

## Capa de datos de mercado automática (Fase 5)

### Adaptadores (`app/services/data/providers/`)

- Cada proveedor es una clase independiente que devuelve **observaciones normalizadas**
  (nunca filas ORM) con `Provenance` completo: proveedor, URL, fecha del dato, fecha de
  consulta, calidad (`close`/`reported`) y naturaleza (`official`/`reference`/`market`).
- **Frankfurter v2** (`frankfurter.py`) — divisas primarias, sin clave, 228 monedas
  (BOB vía BCBO), actuales e históricas. `ExchangeRateApiProvider` (`exchangerate.py`)
  es la segunda fuente, diaria y sin historial: sirve para detectar divergencias.
- **StockAnalysis** (`stockanalysis.py`) — precios históricos diarios US/DE/ES/GB con
  mapa mercado→bolsa explícito; cualquier otro mercado lanza `ProviderDataError`.
- **SEC EDGAR** (`sec_fundamentals.py`) — `companyfacts` para emisores con CIK; extrae
  solo métricas XBRL publicadas (ingresos, beneficio neto, EPS diluido, efectivo, deuda LP,
  acciones) en ventanas anual (340-400 d) y trimestral (80-100 d).
- `base.py` normaliza `Decimal` y fechas sin pasar por `float`, define calidades, kinds y
  errores tipados (`ProviderUnavailable`, `ProviderTimeout`, `ProviderRateLimited`,
  `ProviderDataError`, `ProviderNotConfigured`), todos hijos de `DataError`.
- `http.py` (`HttpFetcher`) centraliza timeout, reintentos acotados, backoff exponencial
  con `sleep` inyectable y el recuento de peticiones para registrarlo en cada run.

### Servicio de sincronización (`sync.py`)

- `DataSyncService.sync_fx / sync_prices / sync_fundamentals`: traen datos, los validan
  y los persisten. Cada ejecución crea un `ProviderRun` con estado, peticiones, registros
  leídos/guardados/descartados y anomalías.
- **Nunca sobrescribe un dato válido sin `force`**: un valor distinto para la misma
  identidad (par/fecha/fuente o instrumento/fecha/fuente) queda como anomalía
  `..._sin_force`. Con `force` se sustituye y también se registra.
- Validaciones: fechas futuras descartadas, saltos diarios >35 % marcados (no borrados),
  datos obsoletos (`data_stale_after_days`) marcados `stale`, divergencias FX >3 % entre
  fuentes registradas con ambos valores.
- Caché `DataCache` por clave con TTL (60 min divisas actuales, 20 h históricos/precios):
  una segunda sincronización idéntica responde `cached` sin tocar red.
- Deduplicación: misma identidad → mismo valor o anomalía, jamás filas duplicadas
  (respaldada por restricciones únicas de las tablas).

### Ejecución y estado

- `runner.py` (`DataSyncRunner`) — cola ligera en proceso con estado persistente:
  `enqueue` anti-duplicados por `task_key` con estado activo, `recover_interrupted` que
  reencola o marca `failed` según `job_max_attempts`, y planificador opcional
  (`data_sync_interval_minutes`, **apagado por defecto**) que programa los pares de
  `data_sync_pairs` y los instrumentos con `auto_sync_prices`.
- `status.py` — `provider_catalog`, `latest_runs`, `pair_status`, `price_status` y
  `data_status`: la interfaz refleja el estado real, sin indicadores decorativos.
- API `app/api/v1/marketdata.py` — `GET /data/status|providers|runs|fx-rates|fundamentals|news`,
  `POST /data/sync/fx|prices|fundamentals` (en segundo plano por defecto) y
  `POST /data/instruments/{uid}/auto-sync`, todo con sesión y límite de peticiones.
- Interfaz: página `/datos` (proveedores, frescura, ejecuciones, automatización, noticias)
  e indicador de calidad (`quote_quality`) en cada posición de la cartera real.

### Modelo de datos nuevo

- `provider_runs` (qué, cuándo, con qué resultado), `data_cache` (TTL por clave),
  `fundamentals` (periodo + métricas reportadas + procedencia) y `news_items` (preparada,
  sin datos hasta que haya proveedor con licencia).
- Columnas nuevas: `quotes.adjusted` (distingue cierre ajustado), `fx_rates.kind`
  (oficial/referencia/mercado) e `instruments.auto_sync_prices`. Datos de proveedor con
  `user_id` nulo; las cotizaciones/tipos manuales siguen siendo privados de cada usuario.
- Migración `2b7d5f3a91e4` sobre `1a0119241c07`.

## Capas actuales del motor

- `src/nexo_invest/core/units.py` — tipos básicos: `Money` (con `Scale` enum y conversión
  explícita), `Period`, `Frequency`, `Scale`. Evita mezclar escalas y periodos sin transformación
  documentada.
- `src/nexo_invest/core/periods.py` — `FiscalCalendar` (regla de año fiscal documentada),
  `growth_rate_strict`, `ttm_periods`, `compute_ttm_from_quarters`.
- `src/nexo_invest/core/metrics.py` — modelos `IncomeStatement`, `BalanceSheet`, `CashFlow`,
  `FinancialState`, `FinancialMetrics`. Calcula solo lo que los datos permiten;
  los valores ausentes se dejan como `None`. `growth_rate` y `margin` validan escalas por defecto.
  `from_state` acepta `fiscal_calendar` opcional para calcular `revenue_ttm`, `revenue_growth_fiscal`,
  `notes_fiscal`. `from_provenance(registry, metric)` convierte `ProvenanceRegistry` en `FinancialState`.
- `src/nexo_invest/core/sources.py` — capa de procedencia:
  `DataType`, `DataOrigin`, `VerificationState`, `DataSource`, `Observation`, `ProvenanceRegistry`.
  Registro por fuente y por observación, validaciones de duplicados y campos requeridos,
  `quality_report`, `to_financial_state(metric)` por métrica (evita importación circular con
  importación bajo demanda).
- `src/nexo_invest/core/dcf.py` — motor DCF reproducible (`run_dcf`), supuestos
  `DCFAssumptions`, proyecciones `ProjectedYear` y tabla de sensibilidad.
- `src/nexo_invest/core/report.py` — generación de informe Markdown estructurado de 9 secciones.
- `src/nexo_invest/cli.py` — CLI mínimo con `nexo --version` y `nexo metrics-demo`.

## Flujo de datos actual

1. Fuente registrada → `DataSource`.
2. Observación registrada → `Observation` (vinculada a una `DataSource` y a un periodo/métrica).
3. `ProvenanceRegistry.to_financial_state(metric)` → `FinancialState` por métrica.
4. `FinancialMetrics.from_state(state, latest_end, fiscal_calendar=optional)` → métricas calculadas
   con validación de escalas, crecimiento fiscal estricto (opcional), TTM (opcional).
5. Opcional: `from_provenance(registry, metric)` como alternativa para construir `FinancialState`.
6. Opcional: `run_dcf` → valoración.
7. `AnalysisReport` → informe Markdown.

## Calendario fiscal

- `FiscalCalendar(close_month)` define el mes de cierre del año fiscal (1-12).
- Regla: `fiscal_year_of_finish(finish)`: si `finish.month <= close_month` entonces `finish.year`,
  de lo contrario `finish.year + 1`.
- Convención: el año fiscal se nombra por el año civil del mes de cierre.
- Ejemplos:
  - close_month=12: diciembre 2024 => FY2024; noviembre 2024 => FY2024; enero 2025 => FY2025.
  - close_month=3: marzo 2024 => FY2024 (mes de cierre); abril 2024 => FY2025.

## TTM

- `compute_ttm_from_quarters(periods, values, latest_end, calendar)` suma los últimos 4 trimestres
  consecutivos disponibles al `latest_end`.
- `ttm_periods` selecciona secuencia estricta consecutiva (diferencia entre fin de trimestre
  y fin del siguiente entre 75 y 120 días).
- TTM devuelve None si hay menos de 4 trimestres consecutivos o algún valor ausente.

## Fiscal growth estricto

- `revenue_growth_fiscal` se calcula cuando hay `fiscal_calendar`.
- Usa `growth_rate_strict` con el periodo fiscal anterior (mismo campo fiscal).
- Cuando hay `revenue_growth_fiscal`, `revenue_growth` se actualiza con él.
- Documentado que `revenue_growth` sin calendario compara con el periodo anterior más reciente,
  que puede no ser el año fiscal anterior.

## Escalas

- `Scale` enum: reported, thousands, millions, units, billions.
- `Money.to_scale(target)` convierte el valor a otra escala compatible.
- `growth_rate` y `margin` exigen por defecto escalas compatibles (`same_scale_required=True`);
  se puede desactivar con flag explícito.

## Procedencia

- `DataType`: income_statement, balance_sheet, cash_flow, share_count, share_price, metric.
- `DataOrigin`: simulated, manual, external_verified, external_unverified.
- `VerificationState`: unverified, pending, partially_verified, verified.
- `DataSource`: identifica la fuente (id, name, entity, url, reference, data_type, fechas,
  currency, scale, extraction_method, verification_state, origin, notes, limitations, hash).
  Valida campos requeridos. Propiedades is_verified, is_external, is_simulated, is_manual.
- `Observation`: vincula una fuente a un periodo y métrica, con valor, value_origin, verified,
  raw_value, notes, limitations. Propiedades is_verified (requiere verified=True, source.verified,
  valor presente/no ausente), is_simulated, is_external, is_manual, is_missing.
- `ProvenanceRegistry`: registra fuentes sin duplicados, observaciones sin duplicados a nivel de
  fuente/métrica/periodo, report de calidad, `to_financial_state(metric)` por métrica.
- Cierre de ciclo de trazabilidad: fuente → observación → FinancialState → FinancialMetrics →
  AnalysisReport.

## Decisiones técnicas principales

- Construcción sobre `hatchling` y `pyproject.toml` estándar.
- Tipos explícitos para valores monetarios y periodos.
- `Scale` enum para evitar mezcla implícita de unidades.
- Cálculos con datos locales desde el inicio; fuentes en línea como adaptadores
  opcionales con fixtures de prueba.
- Informe Markdown primero; HTML solo si tiene sentido.
- CLI primero; interfaz visual después.
- Validación de escalas por defecto en `growth_rate` y `margin` con flag explícito para
  casos controlados.
- FiscalCalendar con regla finish.month <= close_month => finish.year, else finish.year + 1.
- TTM como suma de últimos 4 trimestres consecutivos disponibles.
- Fiscal growth estricto cuando hay calendario fiscal.
- Modelo de procedencia explícito con validaciones de duplicados, campos requeridos,
  datos ausentes, escalas/monedas incompatibles.
- Importación circular evitada con importación bajo demanda en `to_financial_state`.

## Capas añadidas en la versión 0.2.0

- `src/nexo_invest/data/sec_edgar.py` — adaptador del **primer fuente real**: SEC EDGAR
  (API pública `companyfacts`). Aplica las condiciones de acceso de la SEC (`User-Agent`
  identificable con contacto, intervalo mínimo entre peticiones, caché en disco) y guarda
  SHA-256 del documento descargado. Extrae hechos XBRL, excluye periodos acumulados YTD,
  valida por observación y promueve niveles de procedencia.
- `src/nexo_invest/data/prices.py` — adaptador de precios diarios (endpoint público de Yahoo
  Finance). Fuente **no oficial**: toda serie queda en `EXTERNAL_DOWNLOADED` con esa
  limitación registrada. Los huecos se descartan, no se rellenan.
- `src/nexo_invest/analysis.py` — `build_real_report`: une fuente → registro → estado →
  indicadores → escenarios → informe Markdown reproducible de 12 secciones, que separa
  hechos, datos sin validar, estimaciones, supuestos, datos simulados y ausencias.
- `src/nexo_invest/strategies.py` — estrategia de valor con seis criterios objetivos
  (ROIC, margen bruto, crecimiento, conversión de caja, deuda neta/EBITDA, dilución) y
  estado de la estrategia táctica (no lista por falta de precios verificados).
- `src/nexo_invest/backtest.py` — prueba histórica exploratoria: regla de momento con
  ventana y rebalanceo fijados, costes explícitos, separación desarrollo/evaluación,
  comparación con buy & hold y comprobación automática de ausencia de sesgo de anticipación.

## Capas añadidas en la versión 0.3.0 (Ciclo 3)

- `src/nexo_invest/data/nasdaq.py` — adaptador de la **segunda fuente** (Nasdaq,
  `api.nasdaq.com`, gratuita y sin clave): estado de resultados por cierre fiscal y
  cierres diarios `Close/Last`. Mismas condiciones que el resto: `User-Agent`
  identificable, intervalo mínimo, caché en disco y SHA-256. Celdas vacías quedan en
  `None`, nunca en 0. Registra la restricción de acceso observada (un `User-Agent` con
  URL de contacto recibe corte silencioso).
- `src/nexo_invest/verification.py` — contraste entre fuentes y margen de seguridad:
  - `contrast_annual_revenue(...)`: exige **fecha de cierre idéntica** en ambas fuentes e
    infiere la relación de unidad como potencia de diez (la fuente secundaria no la
    declara). Tres resultados posibles: `coincide`, `discrepancia`, `incomparable`.
    Un fallo de descarga (`contrast_failed`) queda en `incomparable`, no en `coincide`.
  - `contrast_close_price(...)`: exige **símbolo y fecha idénticos**; compara el cierre
    sin ajustar con el `Close/Last` de la segunda fuente, nunca con el más cercano.
  - `margin_of_safety(intrinsic, price) = 1 − price / intrinsic`; devuelve `None` si
    falta un término o si el valor por acción no es positivo.
  - `verification_markdown(...)`: informe reproducible con contraste, precio, valoración
    y auditoría de la prueba histórica.
- `src/nexo_invest/backtest.py` — `audit_backtest(...)`: recalcula rentabilidad total,
  anualizada, caída máxima y buy & hold con fórmulas escritas aparte, comprueba el orden
  temporal de las operaciones y **repite la ejecución sobre la serie recortada**: si la
  estrategia leyera datos futuros, las dos curvas divergirían.

## Flujo de verificación (v0.3.0)

```
SEC EDGAR (fuente primaria, companyfacts, SHA-256)
   → observación de ingresos del último ejercicio fiscal completo
      ↔ Nasdaq (segunda fuente, estado de resultados, SHA-256)
         → coincide / discrepancia / incomparable (+ unidad inferida)
            → si coincide: la observación primaria sube a EXTERNAL_CORROBORATED
              y la evidencia (URL, consulta, diferencia) se anota en la observación

Yahoo Finance (cierre sin ajustar, SHA-256)
   ↔ Nasdaq (Close/Last, SHA-256), misma fecha y mismo símbolo
      → coincide / discrepancia / incomparable
         → solo si coincide: precio utilizable para margen de seguridad

DCF por escenarios (supuestos explícitos) + precio comprobado
   → valor por acción, margen de subida y margen de seguridad con fórmula declarada

Prueba histórica → audit_backtest → recálculo independiente + control de anticipación
```

## Escalera de procedencia (v0.2.0)

1. `EXTERNAL_DOWNLOADED` — la descarga funcionó. No dice que la cifra sea correcta.
2. `EXTERNAL_VALIDATED` — superó las comprobaciones internas: unidades homogéneas, fechas
   coherentes e identidad contable Activo = Pasivo + Patrimonio **por periodo**.
3. `EXTERNAL_CORROBORATED` — además, hay una segunda comprobación registrada. Existen dos
   tipos y **no significan lo mismo**:
   - **intra-fuente** (Hito 2): dos rutas internas de la misma presentación coinciden
     (concepto alternativo o suma de cuatro trimestres con duración trimestral real).
   - **entre proveedores** (Ciclo 3): una segunda fuente distinta publica la misma cifra
     para el mismo periodo (SEC ↔ Nasdaq) o el mismo cierre para la misma fecha
     (Yahoo ↔ Nasdaq). Se anota URL, fecha de consulta y diferencia medida.

Ninguno de los dos es una fuente primaria independiente: toda cifra financiera pública
procede de la presentación de la empresa, y los precios agregados proceden del tape de
cada proveedor. Queda escrito en cada informe.

La corroboración es **intra-fuente**: no se ha contrastado con una segunda fuente independiente
ni con el documento original en HTML. Queda escrito en cada informe.

## Flujo de datos real (v0.2.0)

```
SEC EDGAR (companyfacts JSON, SHA-256)
   → extract_observations (XBRL, sin YTD)
      → ProvenanceRegistry (por observación, con nivel)
         → FinancialState (misma escala, sin inventar huecos)
            → FinancialMetrics (indicadores con fórmula y requisito)
               → escenarios DCF (supuestos explícitos)
                  → informe Markdown con trazabilidad y ausencias declaradas
```

## Limitaciones conocidas

- Sin calendario fiscal adjunto a los datos manuales: el crecimiento compara con el periodo
  anterior más reciente de la misma frecuencia, que puede no ser el año fiscal anterior.
- `ROIC` clásico (`operating_income / invested_capital`) queda en `None` si la empresa no
  reporta capital invertido; el indicador que sí se calcula es `roic_nopat`, con capital
  invertido estimado (deuda total + patrimonio) y **marcado como estimación**.
- TTM es `None` cuando la fuente no publica el cuarto trimestre como periodo independiente
  (caso real de Apple en sus 10-K/10-Q): se documenta y no se rellena con acumulados.
- Sin comparables reales ni precios verificados: no hay múltiplos ni margen de seguridad.
- La prueba histórica cubre un único activo y un único periodo; no prueba rentabilidad.
- El modelo de procedencia no rechaza automáticamente monedas incompatibles: las registra
  con la moneda real y deja la decisión al consumidor del dato.
- Los periodos con el mismo cierre y distinta duración (anual y cuarto trimestre) comparten
  clave en `FinancialState`: se conserva uno solo, documentado como sobrescritura.
