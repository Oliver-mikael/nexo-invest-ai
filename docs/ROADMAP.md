# ROADMAP — Nexo Invest AI

## Estado general

Versión actual: 0.3.0
Rama base: main
Commit base: 0589554ac942059a1b6fa6f1afbe08a766584eaa

## Hito A — Diagnóstico y base reproducible

Estado: COMPLETADO con correcciones

Completado:
- Inventario real del workspace y herramientas.
- Estructura inicial: pyproject.toml, src/, tests/.
- Módulos base con tipado y validaciones.
- Suite de pruebas inicial que pasa.
- CLI mínimo verificable.
- Primer respaldo verificable generado.
- Respaldo actualizado del producto completo (con Hito D integrado).
- Documentación de continuidad creada: SESSION_STATE.md, ARCHITECTURE.md, CHANGELOG.md, ROADMAP.md,
  DECISIONS.md, KNOWN_ISSUES.md.
- README.md actualizado.
- Auditoría del motor financiero realizada y corregida parcialmente (escalas, ROIC, periodo anterior).

Pendiente del hito:
- Ruff o linting opcional.
- Confirmar que el proyecto puede reconstruirse desde estas instrucciones.

## Hito B — Motor de métricas con calendario fiscal y TTM

Estado: COMPLETADO

Completado:
- FiscalCalendar con close_month configurables y regla de año fiscal documentada.
- TTM como suma de últimos 4 trimestres consecutivos disponibles (compute_ttm_from_quarters).
- Selección estricta de secuencia consecutiva (ttm_periods).
- Crecimiento fiscal estricto cuando hay calendario fiscal (revenue_growth_fiscal).
- revenue_ttm calculado cuando hay 4 trimestres consecutivos.
- growth_rate y margin con validación de escalas por defecto.
- Money con Scale enum y to_scale.
- Manejo de valores ausentes (None/NaN) sin inventar datos.
- Periodo duplicado documentado (sobrescritura por fecha de fin).
- Pruebas de regresión para TTM, fiscales, escalas incompatibles, periodo duplicado, calendario fiscal.

Pendiente:
- Ampliar fixture de ejemplo con datos trimestrales consecutivos para ejercitar TTM con datos locales.
- Validaciones de consistencia entre estados (ingresos vs flujo de caja, etc.).
- Ratios de liquidez, rotación de capital, márgenes por periodo.
- Asegurar que TTM en informeMarkdown usa TTM cuando esté disponible.

## Hito C — Valoración

Estado: COMPLETADO

Completado:
- DCF reproducible con horizonte, tasa de descuento, crecimiento terminal.
- Valor terminal (Gordon growth) sobre el último FCF proyectado.
- Valoración por acción cuando hay acciones diluidas.
- Tabla de sensibilidad: par (tasa descuento, crecimiento terminal) → valor por acción.
- Upside vs precio actual.
- Escenarios bajista/base/alcista parametrizados (crecimiento de ingresos, tasa de descuento, crecimiento terminal).
- Comparables con datos simulados: modelo Comparable con revenue, EBITDA y P/E, múltiplos medianos, escalas incompatibles → None.
- build_valuation: valor de empresa, equity, valor por acción, upside y múltiplos por escenario.
- Validación de supuestos: tasa de descuento > crecimiento terminal; terminal_growth >= -1.
- Integración con AnalysisReport (escenario base como valoración, separación de estados de verificación).
- Pruebas independientes de escenarios, comparables, escalas incompatibles, datos insuficientes, valores inválidos.

Pendiente:
- Validar sensibilidad con ejemplos calculados independientemente en evaluaciones reales.
- Validar con datos reales (no simulados) cuando estén disponibles.

## Hito D — Investigación y procedencia

Estado: COMPLETADO

Completado:
- DataType: income_statement, balance_sheet, cash_flow, share_count, share_price, metric.
- DataOrigin: simulated, manual, external_verified, external_unverified.
- VerificationState: unverified, pending, partially_verified, verified.
- DataSource: id, name, entity, url, reference, data_type, publication_date, retrieval_date,
  currency, scale, extraction_method, verification_state, origin, notes, limitations, hash.
  Valida campos requeridos (id, name, entity). Propiedades is_verified, is_external,
  is_simulated, is_manual.
- Observation: source, period, metric, value, value_origin, verified, raw_value, notes, limitations.
  Valida source y metric requeridos. Propiedades is_verified, is_simulated, is_external,
  is_manual, is_missing. is_verified requiere verified=True, source.verified y valor presente/no ausente.
- ProvenanceRegistry: registro por source_id, observación por clave fuente::metrica::periodo_fin,
  validación de duplicados a nivel de registro de fuente y de observación, método quality_report,
  to_financial_state(metric) por métrica (evita importación circular con importación bajo demanda).
- Cierre de ciclo de trazabilidad: fuente → observación → FinancialState → FinancialMetrics →
  AnalysisReport.
- Pruebas: 68 pruebas en total, 0 fallos, incluyendo integración con FinancialMetrics y TTM.
- Datos simulados no producen conclusión presentada como recomendación basada en datos reales.

Pendiente:
- Primeros fixtures con datos trimestrales consecutivos para ejercitar TTM en el informe.
- Validar que el informe refleja la procedencia correctamente.
- Integrar procedencia en el informe (hechos verificados / no verificados / supuestos / estimaciones).

## Hito E — Informe de inversión

Estado: COMPLETADO

Completado:
- Informe Markdown de 9 secciones: resumen, calidad de datos, indicadores, valoración, riesgos,
  supuestos, condiciones de reconsideración, fuentes y limitaciones, conclusión.
- Integración de procedencia: bloques de Hechos verificados, Datos no verificados, Datos simulados (no verificados).
- Estado de calidad de datos explícito (Cobertura + calidad del registro).
- Condiciones objetivas para descartar o marcar insuficiente una tesis.
- Separación de supuestos, estimaciones y datos observados.
- Comportamiento de incompletitud: si faltan ingresos o 4 trimestres consecutivos, el informe lo indica y no genera conclusión de inversión injustificada.
- Aviso legal de no asesoramiento financiero.
- Fixture integrado en el ciclo actual con 5 trimestres consecutivos que ejercita TTM (102.0 USD millones) en el informe.

Pendiente:
- Integrar procedencia en informe (hechos verificados, no verificados, supuestos, estimaciones).
- Estado de calidad de datos explícito.
- Condiciones objetivas para descartar la tesis.
- Contenido cualitativo más rico: ventajas competitivas, concentración, asignación de capital.
- HTML si tiene sentido.
- Validar que cada cifra en el informe puede rastrearse a su fuente.

## Hito F — Preparación para GitHub

No iniciado.

Próximas tareas:
- Instrucciones reproducibles de instalación y uso.
- Registro de cambios y lista de tareas pendientes.
- Generar respaldos descargables verificables con manifiesto SHA-256.
- Comprobar que otro entorno puede reconstruir el proyecto.
- Solo entonces: preparar operaciones de push con permiso explícito.

## Ciclo 2 (0.2.0) — Fuentes reales, informe trazable, estrategias y prueba histórica

### Hito 1 — Auditoría técnica: COMPLETADO

- Suite ejecutada, estado de Git revisado, etiquetas de procedencia comprobadas.
- Defectos reales encontrados y corregidos: `to_financial_state` definido dos veces
  (anulaba balance y flujo de caja), clave de observación sin inicio/frecuencia (colisión
  anual vs trimestral), `ttm_periods` sin exigir duración trimestral real, validación de
  unidades solo sobre hechos anuales, mes de cierre fiscal inferido contando trimestres.

### Hito 2 — Primera fuente financiera real (SEC EDGAR): COMPLETADO

- Adaptador con condiciones de acceso respetadas, caché y SHA-256 del contenido.
- Apple Inc. (CIK 320193): 1 591 observaciones registradas, 1 582 validadas y 6
  corroboradas; 3 periodos históricos retenidos con motivo escrito.
- Niveles separados: descargado ≠ validado ≠ corroborado.

### Hito 3 — Validación financiera: COMPLETADO

- Indicadores con fórmula, requisito y prueba: liquidez, cobertura, NOPAT, ROIC, conversión
  de caja, dilución, deuda neta por componentes, FCF estimado cuando no se reporta.
- Corregidos dos defectos detectados con datos reales: deuda total nunca construida desde
  sus componentes y dilución comparando un anual contra un trimestre.
- No calculables: calidad de ingresos por concentración de clientes y rotación de capital
  (la fuente XBRL usada no publica segmentos ni desglose de clientes).

### Hito 4 — Informe de una empresa real: COMPLETADO

- `nexo sec-report` genera `reports/aapl-sec-2026-10-27.md`, con hechos con documento,
  datos sin validar, información ausente, estimaciones, supuestos, riesgos, condiciones de
  invalidación, limitaciones y trazabilidad.
- Sin precio verificado no se calcula margen de subida y no se emite recomendación.

### Hito 5 — Dos estrategias: COMPLETADO PARCIALMENTE

- Estrategia A (valor): seis criterios objetivos, ordenación documentada y estado por
  empresa; ejecutada sobre 6 empresas reales (`reports/estrategias-2026-10-27.md`).
- Estrategia B (táctica): **no lista**, con la lista exacta de datos que necesita.
- Sin precios verificados no se propone ninguna compra, aunque una empresa cumpla todos
  los criterios de calidad.

### Hito 6 — Pruebas históricas: COMPLETADO EN SU VERSIÓN EXPLORATORIA

- Regla de momento con parámetros fijados de antemano, costes, separación
  desarrollo/evaluación, comparación con buy & hold y prueba de no anticipación.
- Resultado real (AAPL, 2021-10-28 → 2026-10-27): estrategia 65,07 % con caída máxima
  −33,36 %, buy & hold 133,25 % (esta cifra se corrigió en el Ciclo 3 a **132,90 %** al
  detectarse que los costes de entrada solo se descontaban a una de las dos curvas; ver
  decisiones 40 y 41). El informe lo publica tal cual: la regla **no** supera a
  mantener el activo, y nada asegura que sea rentable.
- Pendiente: más activos, múltiples periodos, corrección por comparaciones múltiples y
  seguimiento de cartera (exige posiciones y transacciones reales del usuario).

### Hito 7 — Operación y mejora continua: COMPLETADO PARCIALMENTE

- Comandos documentados en README y `scripts/update_reports.sh` con registro de éxito o fallo.
- **No hay programación persistente** en este entorno: se documenta y el script queda como
  mecanismo reproducible para el programador del sistema del usuario.

## Ciclo 3 (0.3.0) — Segunda fuente, precio comprobado y valoración reproducible

### Tarea 1 — Segunda fuente financiera: COMPLETADA

- `data/nasdaq.py`: Nasdaq `api.nasdaq.com`, **gratuita y sin clave**, condiciones de
  acceso respetadas (User-Agent identificable, intervalo mínimo, caché, SHA-256).
- Restricción descubierta y documentada: un `User-Agent` con URL de contacto recibe corte
  silencioso (timeout) en ese endpoint; se usa la forma corta identificable.
- Contraste del **último ejercicio fiscal completo de Apple**: FY2025 (cierre 2025-09-27),
  SEC `416.161.000.000 USD` frente a Nasdaq `416.161.000` → **coincide** con diferencia
  relativa 0 y unidad inferida ×1000 (el endpoint no declara unidad).
- Fecha de cierre idéntica exigida: sin columna común el resultado es `incomparable`.
- Honestidad de la corroboración: Nasdaq es **distribución independiente del mismo
  documento**, no una fuente primaria distinta. Queda como limitación en el informe.
- Si la fuente secundaria falla, el contraste queda `incomparable` con el motivo; la cifra
  primaria **no** se promueve.

### Tarea 2 — Precio verificable: COMPLETADA

- Cierre de AAPL del **2026-10-27**: Yahoo `347.100006` vs Nasdaq `Close/Last 347.10` →
  **coincide** (diferencia relativa 0,000002 %), cierre sin ajustar, símbolo y fecha
  comprobados, con URL y fecha de consulta de las dos fuentes.
- Fecha no negociada, fecha ausente en una de las fuentes o símbolo distinto →
  `incomparable`, y entonces **no se calcula margen de seguridad**.

### Tarea 3 — Valoración reproducible: COMPLETADA

- Escenarios con el precio comprobado (gasto 1,0 %/4,0 %/7,0 %, descuento 10,5 %/8,5 %/7,5 %,
  terminal 1,5 %/2,5 %/3,0 %):
  - bajista: 56,09 USD/acción · margen de subida −83,84 % · margen de seguridad −518,81 %
  - base: 118,93 USD/acción · margen de subida −65,74 % · margen de seguridad −191,86 %
  - alcista: 197,73 USD/acción · margen de subida −43,03 % · margen de seguridad −75,54 %
- Fórmulas declaradas en el informe (DCF, Gordon, deuda neta, valor por acción, margen de
  subida y `1 − precio / valor por acción`). Margen de seguridad **negativo explicado**: el
  precio supera el valor estimado con esos supuestos, lo que no es una recomendación de
  venta sino una medida de sensibilidad.
- Revisión de deuda neta (resta caja e inversiones corrientes, **no** las de largo plazo,
  documentado), acciones en circulación (`shares_outstanding`, 14.773.260.000) y FCF
  (estimado = flujo operativo − inversiones, etiquetado como estimación).
- `sec-report` ya no afirma en falso que el sistema no consulta precios: con precio
  comprobado lo declara; sin él sigue diciendo que no hay precio.

### Tarea 4 — Revisión de la prueba histórica: COMPLETADA CON UN DEFECTO CORREGIDO

- **Defecto encontrado**: el buy & hold se medía desde el primer valor de su curva, que ya
  tiene descontados los costes de entrada; la estrategia sí los pagaba. Los costes quedaban
  fuera de la comparación.
  - Antes: buy & hold 133,25 % (132,897 % sin costes).
  - Corregido: **132,90 %** (misma fórmula para las dos curvas). La estrategia sigue en
    65,07 %: la corrección no cambia la conclusión de que la regla no supera al hold.
- `audit_backtest` recalcula rentabilidad total, anualizada, caída máxima y buy & hold con
  fórmulas independientes y repite la ejecución sobre la serie recortada (anticipación).
  - Todas las comprobaciones **OK** con la serie real.
  - Se prueba que **detecta** curvas manipuladas (controles negativos incluidos en tests).
- Resultado del periodo (2021-10-28 → 2026-10-27, 1.253 sesiones, comisión 10 pb y
  deslizamiento 5 pb): estrategia 65,07 %, caída máxima −33,36 %, 3 entradas y 2 operaciones
  cerradas; buy & hold 132,90 %. **La regla no supera a comprar y mantener.**

### Resultado del ciclo

- 303 pruebas aprobadas, 1 omitida (de 249 en el ciclo anterior: +54).
- Informes: `reports/verify-aapl-2026-10-28.md` (nuevo) y
  `reports/backtest-aapl-2026-10-28.md` (corregido). Reproducción byte a byte salvo la
  línea de fecha.

## Ciclo 4 (no publicado) — Integridad del repositorio y verificación continua

### Hito 1 — Repositorio completo: COMPLETADO

- `main` contenía 24 de los 63 ficheros; el resto solo existía en el workspace. Se recuperan
  los 13 módulos, 12 ficheros de pruebas, 6 documentos, 6 informes y el script de actualización.
- Verificado importando todos los módulos y ejecutando la suite desde una copia limpia.

### Hito 2 — Defectos de tipado y código muerto: COMPLETADO

- Tres anotaciones con nombres sin importar, cuatro constantes de clase mal tipadas,
  comparación NaN reescrita, 32 imports muertos y una dependencia (`pyyaml`) nunca usada.
- `ruff` pasa sin errores con un conjunto de reglas fijado en `pyproject.toml`.

### Hito 3 — Integración continua: COMPLETADO

- `.github/workflows/ci.yml`: instalación, Ruff, importación de módulos, pruebas y CLI en
  Python 3.10 y 3.12, en cada Pull Request y push a `main`.

### Hito 4 — Instalación aislada verificada: COMPLETADO

- Copia limpia instalada en `venv` y 391 pruebas ejecutadas sin depender del workspace.

## Prioridades inmediatas

- **Fuente primaria realmente independiente** (documento original en HTML de la SEC, otro
  registrador o datos de la propia empresa en su web): es la limitación más importante
  y la única que puede confirmar que la cifra es correcta y no solo bien transmitida.
- Precio de mercado de una fuente oficial (SIP, página de la empresa o regulador) para
  validar el agregado en una segunda fecha además de la ya comprobada.
- Segmentos y concentración de clientes (XBRL `segments` o 10-K), hoy no disponibles.
- Ampliar la prueba histórica a más activos y periodos, con corrección por comparaciones
  múltiples y un índice de referencia adecuado.
- Respaldar al terminar cada ciclo con ZIP + manifiesto + prueba de restauración.
