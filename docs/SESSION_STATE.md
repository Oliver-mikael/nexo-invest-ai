# Estado de la sesión — Nexo Invest AI

Fecha de esta sesión: 2026-10-28 (Ciclo 3)
Espacio de trabajo: `/home/daytona/codebase`
Repositorio remoto: `Oliver-mikael/nexo-invest-ai` (privado)
Versión del producto: 0.3.0

Documento de continuidad: lo que necesitas para retomar el trabajo sin reconstruir contexto.

## Qué es hoy el proyecto

CLI en Python que descarga estados financieros presentados de SEC EDGAR, los contrasta con
una segunda fuente independiente, comprueba el precio de mercado en dos orígenes, registra
la procedencia de cada cifra, calcula indicadores con fórmula y requisito declarados, valora
por escenarios y genera informes Markdown reproducibles que separan hechos, datos sin
validar, estimaciones, supuestos y ausencias.

No es asesoramiento financiero. No ejecuta órdenes. No emite recomendaciones mientras no haya
precio de mercado comprobado, y aun con él no recomienda.

## Inventario real del workspace

Raíz:
- `README.md` — propósito, uso, estructura, niveles de procedencia, limitaciones.
- `pyproject.toml` — Python 3.10, hatchling, CLI `nexo`, `pyyaml`, `pytest` como dev dependency.
- `scripts/update_reports.sh` — regenera informes y prueba histórica con registro de éxito/fallo.
- `reports/` — informes reales generados (ver abajo).
- `backups/` — respaldos históricos por fecha (los anteriores no se tocan).
- `.cache/`, `.sec_cache/` — caché de descargas (no versionar).

`src/nexo_invest/`:
- `__init__.py` — versión 0.3.0 y API pública.
- `cli.py` — `version`, `metrics-demo`, `sec-report`, `screen`, `backtest`, **`verify`**.
- `analysis.py` — `build_real_report`: fuente → registro → estado → indicadores → escenarios → informe.
- `verification.py` — **nuevo**: contraste entre fuentes (`contrast_annual_revenue`,
  `contrast_close_price`, `contrast_failed`), `margin_of_safety` e informe de verificación.
- `strategies.py` — estrategia de valor (seis criterios) y estado de la estrategia táctica.
- `backtest.py` — prueba histórica + **`audit_backtest`** (recálculo independiente y control
  de anticipación sobre la serie recortada).
- `core/units.py`, `core/periods.py`, `core/metrics.py`, `core/sources.py`, `core/dcf.py`,
  `core/report.py` — sin cambios estructurales en este ciclo.
- `data/sec_edgar.py` — adaptador de la fuente primaria (condiciones de acceso, caché, SHA-256).
- `data/nasdaq.py` — **nuevo**: segunda fuente (estado de resultados y cierres diarios).
- `data/prices.py` — adaptador de precios (Yahoo Finance, fuente declarada no oficial).

`tests/` — 14 archivos, **304 pruebas** (303 aprobadas, 1 omitida por red). Fixtures locales:
`sec_companyfacts_aapl_subset.json`, `yahoo_aapl_5y.json`, **`nasdaq_aapl_financials.json`**,
**`nasdaq_aapl_historical_2026-10.json`**. Ninguna prueba usa Internet.

`docs/` — ARCHITECTURE, DECISIONS, ROADMAP, KNOWN_ISSUES, CHANGELOG, SESSION_STATE.

## Informes reales generados

- `reports/verify-aapl-2026-10-28.md` — **nuevo**: contraste de ingresos, precio comprobado,
  valoración con margen de seguridad y auditoría de la prueba histórica. Reproducido byte a
  byte salvo la línea de fecha.
- `reports/backtest-aapl-2026-10-28.md` — prueba histórica con el coste de entrada corregido.
- `reports/aapl-sec-2026-10-27.md` — informe de empresa (Ciclo 2, 1 591 observaciones).
- `reports/estrategias-2026-10-27.md` — cribado de valor sobre seis empresas reales.
- `reports/backtest-aapl-2026-10-27.md` — **superado** por la corrección del Ciclo 3.

## Resultados reales que no hay que olvidar

- Apple, SEC EDGAR (CIK 320193), consultado 2026-10-27:
  SHA-256 `73a86c6aedc31f77cac2ea4df5f80f0b3bd7e6eb58bb4e01444fbedf3afb9c43`.
- **Ingresos FY2025** (cierre 2025-09-27): SEC `416.161.000.000 USD` vs Nasdaq `416.161.000`
  → coinciden, diferencia relativa 0, unidad inferida ×1000. Consultas: SEC 2026-10-27,
  Nasdaq 2026-10-28. La observación primaria sube a `EXTERNAL_CORROBORATED` con la evidencia
  en sus notas; la fuente secundaria queda registrada (26 fuentes, 1 591 observaciones).
- **Precio AAPL 2026-10-27**: Yahoo `347,100006` vs Nasdaq `Close/Last 347,10` → coinciden
  (0,000002 %), cierre sin ajustar, `external_corroborated`.
- **Valoración con ese precio**: bajista 56,09 USD/acción (margen de subida −83,84 %, margen
  de seguridad −518,81 %), base 118,93 USD (−65,74 %, −191,86 %), alcista 197,73 USD
  (−43,03 %, −75,54 %). Fórmula: `1 − precio / valor por acción`. Margen negativo = el precio
  supera el valor estimado con esos supuestos; no es recomendación de venta.
- **Prueba histórica corregida** (AAPL 2021-10-28 → 2026-10-27, 1 253 sesiones): estrategia
  65,07 % (anualizada 10,61 %, caída máxima −33,36 %, 3 entradas, 2 cerradas), buy & hold
  **132,90 %** (antes 133,25 % por un coste de entrada mal descontado). La regla **no** supera
  a mantener el activo; está publicado así.
- TTM de Apple es `None`: la fuente no publica el cuarto trimestre como periodo independiente.
- FCF base usado: 98.767.000.000 USD (estimado: flujo operativo − inversiones). Deuda neta
  43.960.000.000 USD (no resta inversiones a largo plazo: limitación documentada).
  Acciones: 14.773.260.000.

## Estado de las pruebas

```
python3 -m pytest        →  303 passed, 1 skipped
```

Reparto por archivo: analysis_report 26, backtest 26, backtest_audit 10, dcf 21, metrics 21,
metrics_extended 34, nasdaq 14, periods 15, report 4, sec_edgar 29, sources 42, strategies 16,
units 17, verification 25, verify_cli 4. El test omitido depende de red por diseño.

## Estado de Git

- Rama: `main`. Commit base: `0589554` (Initial commit, solo README.md).
- Esta sesión **no** ha hecho commit ni push. Todo el trabajo está sin stagear.
- No se ha modificado ninguna rama remota.
- El panel de cambios de Freebuff es el que gestiona guardar, commit y push.

## Restricciones activas

- Sin `venv`: instalación con `pip3 install -e ".[dev]"` sobre el Python del sistema.
- Sin programación persistente de tareas: `scripts/update_reports.sh` se lanza a mano.
- `NEXO_SEC_CONTACT` debe contener un correo real antes de consultar la SEC; sin él responde 403.
- **`api.nasdaq.com` corta en silencio (timeout) los `User-Agent` con URL de contacto**;
  verificado con peticiones repetidas. El adaptador usa la forma corta identificable.
- No hay claves ni secretos en el workspace; ninguna integración de pago.

## Lo que está implementado y probado

- Todo lo del Ciclo 2 más:
- Segunda fuente conectada (Nasdaq) con contraste de un ejercicio fiscal completo: estados
  `coincide` / `discrepancia` / `incomparable`, unidad inferida y limitación explícita de
  que no es fuente primaria.
- Precio comprobado en dos fuentes con símbolo y fecha obligatorios; sin coincidencia no se
  calcula margen de seguridad.
- Margen de seguridad con fórmula declarada y negativo explicado.
- Auditoría de la prueba histórica con recálculo independiente, control de anticipación y
  controles negativos que demuestran que detecta curvas manipuladas.
- Corrección real del coste de entrada en la comparación con buy & hold.

## Lo que está solo preparado

- Fuente primaria **independiente**: no hay ninguna. Nasdaq repite el mismo documento.
- Precio oficial de mercado: los agregados coinciden entre sí, pero no es el tape oficial ni
  se ha comprobado en más de una fecha.
- Comparables reales: el modelo existe, los datos de mercado verificados no.
- Estrategia táctica: requisitos definidos, señales no calculadas.
- Seguimiento de cartera: requiere datos reales del usuario.

## Respaldo

- Ciclo 2: `backups/2026-10-28/` + `nexo-invest-ai-backup-2026-10-28.zip`
  (SHA-256 `485ed0836820dbdd1ef482780aed70aa66b3cff12ef22976d6ae04b8057d8ff7`) y los del
  2026-10-27. **Conservados intactos.**
- Ciclo 3: `backups/2026-10-28-ciclo3/` + `nexo-invest-ai-backup-2026-10-28-ciclo3.zip`,
  con manifiesto SHA-256 por archivo y prueba de restauración (ver `MANIFEST.txt`).

## Próximo paso concreto

Ciclo 4: fuente primaria independiente y precio oficial.

Criterio objetivo para declararlo completado:
1. Los ingresos de un ejercicio de Apple coinciden entre SEC EDGAR y una fuente que **no**
   sea un redistribuidor del mismo documento (documento HTML original de la SEC, otro
   registrador o la web de la propia empresa), con ambas URLs, SHAs y fechas de consulta.
2. Un precio de cierre de AAPL comprobado en una segunda fecha además de 2026-10-27, y una
   tercera fuente de precios que permita desacreditar o confirmar el agregado.
3. Suite completa en verde con pruebas nuevas para ambos puntos, y el informe de verificación
   regenerado y reproducible.

No haré push a GitHub ni modificaré ramas remotas sin permiso explícito.
