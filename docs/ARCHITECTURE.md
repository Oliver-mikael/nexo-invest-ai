# ARCHITECTURE — Nexo Invest AI

Versión actual: 0.3.0

## Propósito

Motor de investigación y valoración de inversiones verificable, escrito en Python,
orientado a análisis fundamental, valoración y generación de informes reproducibles.

## Capas actuales

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
