# CHANGELOG — Nexo Invest AI

## 0.3.0 — 2026-10-28 (Ciclo 3)

Objetivo: demostrar que los datos de la empresa, el precio de mercado y la valoración
son fiables, sin añadir arquitectura innecesaria.

### Tarea 1 — Segunda fuente financiera

- `src/nexo_invest/data/nasdaq.py`: adaptador de `api.nasdaq.com` (gratuita, sin clave),
  con `User-Agent` identificable, límite de peticiones, caché y SHA-256.
  - Restricción de acceso observada y documentada: un `User-Agent` con URL de contacto
    recibe corte silencioso; verificado con peticiones repetidas.
  - Celdas vacías → `None`, nunca 0. Símbolo distinto al solicitado → error, sin datos.
- Fixtures reales congelados: `nasdaq_aapl_financials.json` (4 ejercicios),
  `nasdaq_aapl_historical_2026-10.json` (19 sesiones de octubre de 2026).
- Contraste de ingresos del último ejercicio completo de Apple: FY2025 (cierre
  2025-09-27), SEC `416.161.000.000 USD` vs Nasdaq `416.161.000` → **coincide**,
  diferencia relativa 0, unidad inferida ×1000.
- Tres estados posibles: `coincide`, `discrepancia`, `incomparable`. Un fallo de descarga
  queda `incomparable` con el motivo; sin fecha común no se elige el periodo más cercano.
- La limitación clave va en el informe: Nasdaq es **distribución independiente del mismo
  documento**, no una fuente primaria distinta.
- La fuente secundaria se registra como `DataSource`; la evidencia se anota en la
  observación primaria, que sube a `EXTERNAL_CORROBORATED` solo si hay coincidencia.

### Tarea 2 — Precio verificable

- `contrast_close_price`: exige símbolo y fecha exactos en ambas fuentes y compara
  cierre sin ajustar con `Close/Last`.
- Resultado real: AAPL 2026-10-27, Yahoo `347,100006` vs Nasdaq `347,10` → **coincide**
  (diferencia relativa 0,000002 %), nivel `external_corroborated`, con URL y fecha de
  consulta de las dos fuentes y la distinción ajustado/sin ajustar declarada.
- Sin coincidencia no hay precio y no se calcula margen de seguridad.

### Tarea 3 — Valoración reproducible

- Escenarios con precio comprobado: bajista 56,09 USD (margen de seguridad −518,81 %),
  base 118,93 USD (−191,86 %), alcista 197,73 USD (−75,54 %). Margen de subida −83,84 % /
  −65,74 % / −43,03 %.
- Fórmulas declaradas en el informe (DCF, Gordon, deuda neta, valor por acción, margen de
  subida y `1 − precio / valor por acción`), con explicación del margen **negativo**: el
  precio supera el valor estimado con esos supuestos, lo que no es recomendación de venta.
- `analysis.py`: el informe de `sec-report` ya no afirma siempre que el sistema no
  consulta precios; con precio comprobado lo declara y sin él lo sigue diciendo.
- Prueba nueva que exige coherencia entre el precio mostrado y el upside de los escenarios.

### Tarea 4 — Revisión de la prueba histórica

- `audit_backtest` en `backtest.py`: recalcula rentabilidad total, anualizada, caída
  máxima y buy & hold con fórmulas independientes, comprueba el orden de las operaciones
  y repite la ejecución sobre la serie recortada para detectar anticipación.
- **Defecto encontrado y corregido**: el buy & hold se medía desde su primer valor, con
  los costes de entrada ya descontados, mientras la estrategia partía del capital inicial.
  Corregido para que ambas curvas se midan desde el capital inicial.
  - Buy & hold corregido: 133,25 % → **132,90 %**. Estrategia: 65,07 % (sin cambios).
  - La conclusión no cambia: la regla no supera a comprar y mantener, y se publica así.
- Controles negativos en las pruebas: la auditoría detecta curvas manipuladas.
- `reports/backtest-aapl-2026-10-28.md` regenerado con la corrección; el del 2026-10-27
  es anterior y queda superado.

### Pruebas y documentación

- 304 pruebas definidas: **303 aprobadas, 1 omitida** (de 249 + 1 del ciclo anterior).
  Nuevos: `test_nasdaq.py` (14), `test_verification.py` (25), `test_backtest_audit.py` (10),
  `test_verify_cli.py` (4, integración sin red) y +1 en `test_analysis_report.py`.
- Informe de verificación generado en vivo y **reproducido byte a byte** salvo la línea de
  fecha (`reports/verify-aapl-2026-10-28.md`).
- `reports/aapl-sec-2026-10-28.md` regenerado con la versión actual (reproducción idéntica);
  el del 2026-10-27 queda como registro del Ciclo 2.
- `scripts/update_reports.sh` incluye ahora el paso de verificación con la segunda fuente.
- README, ARCHITECTURE, ROADMAP, DECISIONS, KNOWN_ISSUES y SESSION_STATE actualizados.

## 0.2.0 — 2026-10-28

Ciclo de conversión del prototipo en sistema con una fuente real conectada.

### Auditoría (hito 1)

- Suite ejecutada antes de tocar código; etiquetas de procedencia revisadas.
- Defectos reales encontrados y corregidos:
  - `to_financial_state` estaba definido dos veces y la segunda definición anulaba el balance
    y el flujo de caja.
  - La clave de observación no incluía inicio ni frecuencia: un anual y un cuarto trimestre con
    el mismo cierre colisionaban.
  - `ttm_periods` solo medía la distancia entre cierres y podía sumar un periodo anual.
  - La validación de unidades se aplicaba solo a hechos anuales, dejando vacíos los balances.
  - El mes de cierre fiscal se infería contando trimestres en lugar de cierres anuales
    (Apple salía junio en vez de septiembre).

### Fuente real (hito 2)

- `src/nexo_invest/data/sec_edgar.py`: adaptador de SEC EDGAR `companyfacts`, con `User-Agent`
  identificable, intervalo mínimo entre peticiones, caché en disco y SHA-256 del documento.
- Escalera de niveles por observación: `EXTERNAL_DOWNLOADED` → `EXTERNAL_VALIDATED` →
  `EXTERNAL_CORROBORATED`, con motivo escrito cuando un periodo no se promueve.
- Exclusión de periodos acumulados YTD (6 y 9 meses).
- Ejecución real sobre Apple Inc. (CIK 320193): 1 591 observaciones, 1 582 validadas,
  6 corroboradas, 3 retenidas.

### Validación financiera (hito 3)

- Indicadores nuevos en `core/metrics.py`: liquidez corriente y prueba ácida, cobertura de
  intereses, NOPAT y ROIC sobre NOPAT, conversión de caja, dilución y deuda neta construida
  desde componentes.
- Corregidos con datos reales: deuda total nunca construida desde sus componentes y dilución
  comparando un ejercicio anual contra un trimestre.
- No calculables y declarados: concentración de clientes y rotación de capital (la fuente
  XBRL usada no publica segmentos ni desglose de clientes).

### Informe real (hito 4)

- `src/nexo_invest/analysis.py`: informe Markdown reproducible de 12 secciones con hechos
  documentados, datos sin validar, información ausente, estimaciones, supuestos, riesgos y
  condiciones de invalidación.
- `reports/aapl-sec-2026-10-27.md` generado a partir de la consulta real.

### Estrategias (hito 5)

- `src/nexo_invest/strategies.py`: estrategia de valor con seis criterios objetivos, ordenación
  documentada y estado por empresa; ejecutada sobre seis empresas reales.
- Estrategia táctica declarada **no lista** con la lista exacta de datos que necesita.
- `can_recommend = False` mientras no haya precio verificado.

### Prueba histórica (hito 6)

- `src/nexo_invest/data/prices.py` y `src/nexo_invest/backtest.py`: regla de momento con
  parámetros fijados antes de ver resultados, costes explícitos, separación
  desarrollo/evaluación y comparación con buy & hold.
- Prueba automática de ausencia de sesgo de anticipación (serie completa vs. serie recortada).
- Resultado real publicado sin adornos: la regla no supera a mantener el activo.

### Operación (hito 7)

- `scripts/update_reports.sh` con registro de éxito o fallo en `reports/update-log.txt`.
- Sin programación persistente en este entorno: documentado como limitación.

### Pruebas y documentación

- 250 pruebas definidas, 249 aprobadas y 1 omitida (requiere red).
- README, ARCHITECTURE, ROADMAP, DECISIONS, KNOWN_ISSUES y SESSION_STATE actualizados a 0.2.0.
- Respaldo `nexo-invest-ai-backup-2026-10-28.zip` (42 archivos, manifiesto SHA-256 y hash por
  archivo en `backups/2026-10-28/SHA256SUMS`). Verificado: `testzip` OK, restauración limpia con
  0 discrepancias y suite completa ejecutada desde la copia restaurada (249 aprobadas, 1 omitida).
  Los respaldos del 2026-10-27 se conservan sin sobrescribir.

## 0.1.0 — 2026-10-27

- Nueva estructura inicial desde cero: pyproject.toml, src/nexo_invest/, tests/.
- Módulos implementados:
  - core/units.py (Money con Scale enum y to_scale, Period, Frequency)
  - core/metrics.py (IncomeStatement, BalanceSheet, CashFlow, FinancialState, FinancialMetrics,
    growth_rate con validación de escalas, margin con validación de escalas, summarize,
    from_provenance(registry, metric) para construir FinancialState desde registro de procedencia)
  - core/dcf.py (DCFAssumptions, ProjectedYear, DCFRun, run_dcf, discount_factor, sensitivity_table)
  - core/report.py (AnalysisReport, ReportSection, markdown generation de 9 secciones)
  - core/periods.py (FiscalCalendar, growth_rate_strict, ttm_periods, compute_ttm_from_quarters)
  - core/sources.py (DataType, DataOrigin, VerificationState, DataSource, Observation, ProvenanceRegistry,
    quality_report, to_financial_state por métrica)
  - cli.py (nexo CLI entry point)
- Pruebas implementadas:
  - tests/test_units.py (Money, Period, Frequency, Scale, to_scale, conversión)
  - tests/test_metrics.py (crecimiento, márgenes, FCF, deuda neta, ROIC, escalas incompatibles,
    resumen)
  - tests/test_dcf.py (DCF, valor terminal, equity, upside, sensibilidad)
  - tests/test_report.py (informe Markdown)
  - tests/test_periods.py (FiscalCalendar, ttm_periods, compute_ttm_from_quarters,
    growth_rate_strict, periodo duplicado)
  - tests/test_sources.py (DataSource, Observation, ProvenanceRegistry, integración con FinancialMetrics,
    TTM desde registro, datos manuales no verificados, casos límite)
- Primer respaldo verificable generado en backups/2026-10-27/ (solo README.md, ya existente).
- Respaldo descargable copiado a la raíz: nexo-invest-ai-backup.zip (134 bytes, luego 47708 bytes,
  luego 78983 bytes, luego 119405 bytes) con src/, tests/, docs/, pyproject.toml, README.md y manifiesto SHA-256.
- Respaldo actualizado del producto completo: nexo-invest-ai-backup.zip (119405 bytes, 25 archivos,
  199062 bytes sin comprimir, restaurado y verificado) con src/, tests/, docs/, pyproject.toml,
  README.md y manifiesto SHA-256.
- Git bundle de respaldo: backups/2026-10-27-product/nexo-invest-ai.bundle.
- Auditoría del motor financiero realizada:
  - Introducido Scale enum para evitar mezcla implícita de unidades.
  - growth_rate y margin ahora exigen por defecto mismas escalas.
  - Money.to_scale() para conversión documentada.
  - ROIC documentado como aproximación.
  - Periodo anterior documentado como limitación (no filtro estricto de año fiscal).
  - Añadidas pruebas de regresión para escalas incompatibles.
- Hito B completado:
  - FiscalCalendar con regla finish.month <= close_month => finish.year, else finish.year + 1.
  - TTM como suma de últimos 4 trimestres consecutivos disponibles.
  - ttm_periods selecciona secuencia estrictamente consecutiva (diferencia 75-120 días).
  - revenue_growth_fiscal calculado cuando hay calendario fiscal.
  - revenue_ttm calculado cuando hay 4 trimestres consecutivos.
  - CLI metrics-demo mostrando fiscal growth y TTM.
  - Pruebas de regresión para TTM, fiscales, escalas incompatibles, periodo duplicado, calendario fiscal.
- Hito D completado:
  - DataType, DataOrigin, VerificationState, DataSource, Observation, ProvenanceRegistry.
  - Validaciones de duplicados a nivel de fuente y observación.
  - Campos requeridos validados en DataSource e Observation.
  - is_verified, is_simulated, is_external, is_manual, is_missing en Observation.
  - quality_report para resumen de procedencia.
  - to_financial_state(metric) en ProvenanceRegistry (evita importación circular con importación bajo demanda).
  - Integración con FinancialMetrics y TTM.
  - Datos simulados no presentados como recomendación basada en datos reales.
  - Pruebas: 68 pruebas en total, 0 fallos.
- No se ha hecho commit ni push en esta sesión.
- No se ha recuperado código anterior; el desarrollo parte de construcción limpia.

## Pendiente antes del siguiente hito

- Hito C completado: DCF, sensibilidad, escenarios bajista/base/alcista, comparables con datos simulados, integración con informe.
- Hito E completado: informe Markdown con procedencia integrada, separación de hechos verificados / no verificados / simulados / supuestos / estimaciones, calidad de datos explícita, condiciones de descarte, incompletitud sin conclusión injustificada.
- 109 pruebas definidas en este ciclo, 0 fallos.
- Fixture con datos trimestrales consecutivos para ejercer TTM con datos locales en el informe (ya demostrado mediante integración informe + registro con TTM = 102.0 USD millones).
- Ruff / linting opcional.
- Respaldo actualizado y verificado: nexo-invest-ai-backup-2026-10-27.zip, 56948 bytes, SHA-256 77f0fd4d40fa85bdd75dd1c85a3d77490a5a34d1ecc61f44935fecf3ee19b204; testzip OK; restauración limpia; manifiesto incluido.
- Confirmación de descarga externa del respaldo por tu parte.
- Hito F solo tras validación de descarga y con permiso explícito.
