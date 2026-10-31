# Nexo Invest AI

Motor de investigación y valoración de inversiones verificable, escrito en Python.

Objetivo: investigar empresas con datos reales, calcular indicadores reproducibles y
separar en todo momento los hechos con fuente de los supuestos, las estimaciones y los
datos de prueba. El sistema puede —y debe— concluir que no hay información suficiente
para evaluar una empresa.

## Estado actual

Versión: 0.3.0 · Rama: `main` · Fuentes conectadas: **SEC EDGAR** (primaria, oficial y gratuita), **Nasdaq** (segunda fuente de distribución) y **Yahoo Finance** (precios, no oficial)

Lo que hoy funciona de verdad:

- Descarga real de estados financieros presentados (XBRL) de empresas estadounidenses
  desde SEC EDGAR, con `User-Agent` identificable, límite de peticiones, caché en disco
  y SHA-256 del contenido descargado.
- Registro de procedencia por observación: fuente, URL, periodo fiscal, fecha de
  presentación, accession number, moneda, escala, método de extracción y **nivel de
  procedencia** (`descargado`, `validado`, `corroborado`).
- Validación interna: unidades homogéneas, fechas coherentes e identidad contable
  Activo = Pasivo + Patrimonio evaluada **por periodo**.
- Indicadores: ingresos, crecimiento, márgenes, FCF (estimado si no se reporta), deuda
  y deuda neta por componentes, liquidez, cobertura, NOPAT, ROIC, conversión de caja y
  dilución. Cada uno con fórmula, requisito de datos y valor esperado en pruebas.
- Valoración por escenarios bajista/base/alcista con supuestos explícitos, sin margen de
  subida si no hay precio verificado.
- **Segunda fuente conectada (Nasdaq, gratuita y sin clave):** contraste del último
  ejercicio fiscal completo de la empresa entre SEC EDGAR y Nasdaq, con URL, fechas de
  consulta, unidad inferida y diferencia medida. Si no coinciden, se declara discrepancia;
  si no hay periodo común, se declara incomparable. En ningún caso se rellena el hueco.
- **Precio comprobado en dos fuentes** para una fecha de negociación concreta: cierre sin
  ajustar de Yahoo Finance frente a `Close/Last` de Nasdaq, con comprobación de símbolo y
  fecha. Solo entonces se calcula margen de seguridad, con la fórmula declarada.
- Auditoría de la prueba histórica que recalcula rentabilidad, anualizada, caída máxima y
  buy & hold con fórmulas independientes, y repite la ejecución sobre la serie recortada
  para comprobar que no hay sesgo de anticipación.
- Estrategias: cribado de valor por criterios objetivos y declaración explícita de que
  la estrategia táctica **no está lista** (faltan series de precios verificadas).
- Prueba histórica exploratoria sobre precios reales (Yahoo Finance, fuente **no
  oficial**), con costes, separación desarrollo/evaluación y una prueba automática de
  ausencia de sesgo de anticipación.
- Informes Markdown reproducibles con trazabilidad fuente → dato → cálculo → conclusión.

Lo que **no** está: fuente primaria independiente de la propia empresa (Nasdaq
repite el mismo documento presentado), precios verificados de mercados oficiales,
comparables reales, señales tácticas, cartera personal y recomendaciones de inversión.

## Instalación

```bash
pip install -e ".[dev]"      # o: python3 -m pip install -e ".[dev]"
```

Si `venv` no está disponible, ver `docs/KNOWN_ISSUES.md`.

## Uso

```bash
# Pruebas (no usan red: todo va contra fixtures locales)
pytest

# Versión y demo local con datos sintéticos
nexo --version
nexo metrics-demo

# Informe de una empresa real (descarga de SEC EDGAR)
export NEXO_SEC_CONTACT="tu-correo@dominio.com"      # lo exige la SEC en el User-Agent
nexo sec-report --ticker AAPL --out reports/aapl.md --cache-dir .cache/sec

# Cribado de la estrategia de valor sobre varias empresas reales
nexo screen --tickers AAPL,MSFT,KO,JNJ --out reports/estrategias.md --cache-dir .cache/sec

# Prueba histórica exploratoria con precios reales
nexo backtest --symbol AAPL --out reports/backtest-aapl.md --cache-dir .cache/prices

# Contraste de ingresos y precio con una segunda fuente + valoración con precio comprobado
nexo verify --ticker AAPL --out reports/verify-aapl.md --cache-dir .cache/sec \
    --price-date 2026-10-27 --backtest-fixture tests/fixtures/yahoo_aapl_5y.json
```

`nexo verify` acepta `--nasdaq-financials-fixture`, `--nasdaq-history-fixture`,
`--price-fixture` y `--price-date` para reproducir el informe sin red y para fijar la
fecha de negociación que se quiere comprobar.

### Actualización periódica de informes

`sh scripts/update_reports.sh` regenera informes y prueba histórica y deja un registro de
éxito o fallo en `reports/update-log.txt`. **No hay programación persistente** en este
entorno: el script debe lanzarse a mano (o desde el Programador de tareas o `cron` del
sistema del usuario). Ver `docs/KNOWN_ISSUES.md`.

## Estructura

```
src/nexo_invest/
  cli.py                  CLI: version, metrics-demo, sec-report, screen, backtest
  analysis.py             informe reproducible de una empresa real
  strategies.py           estrategia de valor y estado de la estrategia táctica
  backtest.py             prueba histórica exploratoria (sin sesgo de anticipación)
  core/units.py           Money, Period, Frequency, Scale
  core/periods.py         FiscalCalendar, TTM, crecimiento estricto
  core/metrics.py         estados financieros e indicadores
  core/dcf.py             DCF, escenarios, comparables, sensibilidad
  core/sources.py         procedencia: DataSource, Observation, ProvenanceRegistry
  core/report.py          informe Markdown clásico
  verification.py         contraste entre fuentes y margen de seguridad
  data/sec_edgar.py       adaptador real de SEC EDGAR (fuente primaria)
  data/nasdaq.py          adaptador de la segunda fuente (Nasdaq)
  data/prices.py          adaptador de precios (Yahoo Finance, no oficial)
tests/                    suite completa con fixtures locales
docs/                     arquitectura, decisiones, problemas conocidos, hoja de ruta
reports/                  informes reales generados (Apple, estrategias, prueba histórica)
```

## Procedencia de los datos

| Nivel | Significado |
| --- | --- |
| `local_fixture` | dato de prueba del repositorio; nunca es información real |
| `synthetic` | dato simulado para demostraciones |
| `manual_input` | dato introducido a mano |
| `external_downloaded` | descargado correctamente; **no** implica que la cifra sea correcta |
| `external_validated` | además superó las comprobaciones internas documentadas |
| `external_corroborated` | corroboración intra-fuente (concepto alternativo o suma de trimestres) |

Una respuesta HTTP 200 solo autoriza el nivel `external_downloaded`.

## Limitaciones destacadas

- La segunda fuente es una **distribución independiente del mismo documento**, no una
  fuente primaria distinta: la coincidencia comprueba la cadena de distribución, no una
  medición independiente. La coincidencia de una cifra no dice que la empresa la reportara
  bien, solo que dos proveedores la transmiten igual.
- La unidad de Nasdaq **no la declara** el endpoint: la relación (miles de USD) se infiere
  por contraste y se registra como inferida.
- Los precios vienen de agregadores, no del mercado oficial: se comprobó una fecha
  concreta, no toda la historia ni el tape real.
- No hay comparables reales: el modelo existe y no produce múltiplos sin precios de
  mercado verificados.
- Los periodos acumulados (6 y 9 meses) se excluyen; sin cuatro trimestres consecutivos
  reales no hay TTM.
- La prueba histórica cubre un solo activo y un solo periodo: no demuestra rentabilidad.
  En el periodo analizado la regla **no** supera a comprar y mantener.

Detalle completo en `docs/KNOWN_ISSUES.md`.

## Nota legal

Este software no constituye asesoramiento financiero personalizado ni garantía de
rentabilidad. No ejecuta órdenes ni utiliza dinero real. Sus conclusiones son herramientas
de análisis, no recomendaciones de inversión.
