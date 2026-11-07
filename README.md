# Nexo Invest AI

Motor de investigación y valoración de inversiones verificable, escrito en Python.

Objetivo: investigar empresas con datos reales, calcular indicadores reproducibles y
separar en todo momento los hechos con fuente de los supuestos, las estimaciones y los
datos de prueba. El sistema puede —y debe— concluir que no hay información suficiente
para evaluar una empresa.

## Estado actual

Versión: 2.0.0 (plataforma multimercado) · motor financiero 0.3.0 · Fuentes conectadas: **SEC EDGAR** (primaria, oficial y gratuita), **Nasdaq** (segunda fuente de distribución) y **Yahoo Finance** (precios, no oficial) · Datos automáticos: **Frankfurter** y **ExchangeRate-API** (divisas), **StockAnalysis** (precios históricos US/DE/ES/GB) y **SEC companyfacts** (fundamentales con CIK)

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
- **Datos financieros automáticos (fase 5):** divisas con dos fuentes reales (Frankfurter
  primario, cubre BOB, y ExchangeRate-API para detectar divergencias), precios históricos
  diarios reales en US/DE/ES/GB (StockAnalysis) y fundamentales de SEC EDGAR para emisores
  con CIK. Cada dato lleva fuente, fecha del dato, fecha de consulta y calidad; la
  sincronización se lanza desde `/datos` o por API, con caché, reintentos acotados y
  ejecución en segundo plano. La automatización programada está **apagada por defecto** y
  las noticias se declaran sin proveedor en lugar de inventarse.

Lo que **no** está: fuente primaria independiente de la propia empresa (Nasdaq
repite el mismo documento presentado), precios verificados de mercados oficiales,
comparables reales, señales tácticas y recomendaciones de inversión.

## Cartera real multimercado (v2.0)

La plataforma incorpora un registro contable de inversiones **reales** separado de la
cartera simulada. No ejecuta órdenes ni guarda credenciales de brókers: es una herramienta
de seguimiento, registro y análisis.

- **Identidad multimercado:** mercados con código MIC, instrumentos con identificador
  interno estable (`uid`), símbolo, bolsa, país, moneda, tipo e ISIN. El ticker no es un
  identificador global.
- **Cuentas reales** con bróker, país, moneda base, comisión y método contable (FIFO o coste
  medio). Varias cuentas por usuario y consolidado por moneda base, sin sumar divisas a
  ciegas.
- **Movimientos:** depósitos, retiros, compras, ventas, dividendos, comisiones, impuestos,
  ajustes, splits y traspasos. Cada uno guarda divisa, tipo de cambio histórico, fuente,
  fecha y estado de validación. Los importes se calculan con `Decimal`.
- **Rentabilidad:** FIFO y coste medio, ganancias realizadas y no realizadas, dividendos
  netos, comisiones, impuestos, XIRR y TWR cuando hay datos suficientes. El efecto
  cambiario se separa del efecto precio; una posición sin cotización queda *sin valorar*.
- **Registro:** formulario manual validado, importación CSV/XLSX con mapeo, vista previa,
  duplicados y confirmación, y documentos privados con OCR local (Tesseract) y revisión
  humana obligatoria.
- **Trazabilidad:** cotizaciones y tipos de cambio con fuente, fecha del dato y calidad
  (tiempo real, retrasado, cierre, histórico, estimado). Las cotizaciones manuales son
  privadas: no pueden alterar la cartera de otro usuario. La calidad de cada cierre
  aparece en la cartera (`quote_quality`), junto a fuente y fecha.

Sigue **sin** haber ejecución de órdenes, conexión con brókers, proveedor automático de
noticias/eventos, APK Android ni garantía de que un precio sea el tape oficial. El OCR
requiere el binario `tesseract-ocr` en el servidor. Ver [`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md).

## Plataforma web, móvil y multi-IA (v1.0)

Sobre el motor se construyó un producto completo, con backend, base de datos y PWA:

- **API FastAPI versionada** (`/api/v1`) con autenticación por token, aislamiento por
  usuario, errores uniformes, límites de peticiones y documentación OpenAPI en `/docs`.
- **Persistencia** SQLAlchemy 2 + Alembic: usuarios, sesiones, empresas, instantáneas,
  trabajos, informes, cartera simulada, consumo y auditoría. SQLite en desarrollo,
  PostgreSQL en producción.
- **Orquestador multi-IA** independiente del proveedor (OpenAI y compatibles, Anthropic,
  Gemini, modelos locales): cinco roles —investigador, analista, auditor, contrario y
  coordinador—, presupuesto por trabajo, reintentos, cancelación y recuperación tras
  reinicios. Sin claves funciona en **modo básico**: informe del motor, sin texto inventado.
- **Auditoría de evidencia** determinista: cada cifra citada por la IA se contrasta con el
  expediente; las que no tienen respaldo se marcan en el informe.
- **Informe de 18 secciones** con etiquetas por sección (hecho, fuente, interpretación de
  IA, supuesto, estimación, no disponible) y exportación a Markdown, CSV y HTML imprimible.
- **Cartera simulada**: compras y ventas ficticias, coste medio, beneficio realizado y no
  realizado. Sin dinero real ni órdenes.
- **PWA instalable**: manifest, iconos, service worker propio y página offline. El service
  worker **no cachea** `/api`: las cifras financieras no quedan en el dispositivo.

Arquitectura, decisiones, tabla de endpoints y límites: [`docs/PLATFORM.md`](docs/PLATFORM.md).

### Arranque rápido

```bash
# 1. Backend
pip install -e "[dev]"
alembic upgrade head
export NEXO_SEC_CONTACT="tu-correo@dominio.com"
uvicorn app.main:app --host 0.0.0.0 --port 8000
# API y documentación: http://localhost:8000/docs

# 2. Interfaz (otra terminal)
cd web && npm install && npm run dev     # http://localhost:5173 con proxy a /api

# 3. Build servido por el propio backend
cd web && npm run build                  # genera web/dist; FastAPI lo sirve en /
```

Docker (API + PostgreSQL + PWA en una sola imagen):

```bash
docker compose up -d --build
```

### Pruebas

```bash
pytest              # 461 pruebas recolectadas: 460 aprobadas, 1 omitida (red), sin red
ruff check src app tests
cd web && npm run typecheck && npm run build
```

## Instalación

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"      # o: python3 -m pip install -e ".[dev]"
```

El motor financiero sigue sin dependencias externas. El backend necesita el extra `api`
(FastAPI, SQLAlchemy, Alembic, OCR local e importación XLSX) y el extra `dev` añade además
`pytest` y `ruff`. Para producción usa `requirements.txt`, que incluye el driver de
PostgreSQL. En el contenedor se instala `tesseract-ocr` con el paquete de español.

## Integración continua

`.github/workflows/ci.yml` ejecuta en cada Pull Request y en cada push a `main`: instalación
editable del paquete, `ruff check`, importación de todos los módulos, la suite de pruebas y
una comprobación de la CLI, sobre Python 3.10 y 3.12.

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

## Validación E2E con navegador (Fase 1.2)

La rama `feat/e2e-browser-validation` incluye una suite end-to-end con Playwright y
Chromium real, ejecutada en dos proyectos: escritorio (1440×900) y móvil (Pixel 7).

La suite arranca por sí misma el backend FastAPI con una base SQLite desechable
(`var/e2e/`) y el servidor de Vite en un puerto propio; no toca la base de desarrollo
ni requiere servicios externos. Cubre autenticación, protección de rutas, panel,
empresas, investigación, informes, ajustes, cartera simulada y cartera real, más
comprobaciones de seguridad (autorización en API, aislamiento entre usuarios,
revocación de sesión, ausencia de secretos en la interfaz) y de móvil (menú, barra
inferior, formularios y desbordamiento horizontal).

```bash
# Requisitos: Node 22, Python con el backend instalado y Chromium de Playwright
cd web
npm ci
npx playwright install --with-deps chromium
npm run e2e          # 35 casos por proyecto; informes en web/playwright-report/
```

El workflow `.github/workflows/ci.yml` incluye el job `e2e`, que instala Chromium con
sus dependencias de sistema, ejecuta typecheck, build y la suite completa, y publica
trazas, capturas, vídeos e informe HTML como artefacto.

Ver [`docs/E2E_VALIDATION.md`](docs/E2E_VALIDATION.md) para arquitectura, rutas
cubiertas, resultados exactos, defectos detectados, pendientes y limitaciones.
