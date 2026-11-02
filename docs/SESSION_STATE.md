# Estado de la sesión — Nexo Invest AI 2.0

Fecha: 2026-11-02 · Plataforma 2.0.0 · Motor 0.3.0
Repositorio: `Oliver-mikael/nexo-invest-ai`
Rama de trabajo: `feat/multi-market-real-money` (independiente de `main`)
Base: `f5b87c4` (PR #2, abierto y **sin fusionar**)

Documento de continuidad: lo necesario para retomar sin reconstruir contexto.

## Qué existe hoy

- **Motor financiero** `src/nexo_invest` sin reescribir: SEC EDGAR, Nasdaq, Yahoo, métricas,
  DCF, escenarios, sensibilidad, backtest, estrategias e informes.
- **Backend** `app/`: FastAPI v1, SQLAlchemy 2 + Alembic, autenticación por token, trabajos
  persistentes, orquestador multi-IA, auditoría de cifras, cartera simulada y exportaciones.
- **Cartera real multimercado (nuevo)**: mercados MIC, instrumentos con `uid` estable, ISIN,
  cuentas reales, movimientos, contabilidad Decimal, divisas históricas, importación y
  documentos con OCR local.
- **Web/PWA** `web/`: React + TypeScript + Vite + Tailwind; panel, empresas, investigación,
  informes, cartera real (resumen/movimientos/importar/documentos), cartera simulada y ajustes.
- **Datos de mercado automáticos (nuevo, fase 5)**: adaptadores Frankfurter y
  ExchangeRate-API (divisas, BOB incluido), StockAnalysis (precios históricos US/DE/ES/GB)
  y SEC EDGAR (fundamentales con CIK); runs con procedencia, caché con TTL, anomalías,
  cola ligera con recuperación y anti-duplicados, API `/api/v1/data/*` y página `/datos`.
  Planificador apagado por defecto; noticias declaradas sin proveedor.
- **Despliegue**: Dockerfile multi-stage con Tesseract, compose con PostgreSQL, caché y volumen
  de documentos privados.

## Fases de la evolución 2.0

| Fase | Estado |
| --- | --- |
| 1. Consolidación (rama, PR, CI, migraciones) | Completada |
| 2. Cartera real multimercado | Completada |
| 3. Rentabilidad: FIFO/media, TWR, XIRR, divisas | Completada |
| 4. Registro manual, CSV/XLSX y OCR con confirmación | Completada; OCR real condicionado a Tesseract |
| 5. Datos financieros automáticos y multimercado | Completada: divisas, precios históricos y fundamentales reales; noticias sin proveedor declarado |
| 6. Workers, scheduler y alertas | Pendiente |
| 7. Multiagentes por horizonte y tesis versionadas | Pendiente |
| 8. Backtesting multimercado | Pendiente |
| 9. Interfaz completa, watchlist, oportunidades y Android | Parcial: cartera real; APK no generado |
| 10. Producción, backups, monitorización y Bolivia | Pendiente |

No se presenta ninguna fase pendiente como terminada.

## Modelo y reglas contables

Tablas nuevas: `markets`, `instruments`, `quotes`, `fx_rates`, `real_accounts`,
`real_movements`, `import_batches`, `documents`.

Tablas de datos automáticos (fase 5): `provider_runs`, `data_cache`, `fundamentals`,
`news_items`; columnas nuevas `quotes.adjusted`, `fx_rates.kind` e
`instruments.auto_sync_prices`.

- Identidad: `instruments.uid`; unicidad `(market_id, symbol)`; ISIN opcional.
- Importes: `Numeric(28,10)` y `Numeric(24,10)`; cálculos con `Decimal`.
- Efectivo en la moneda base de la cuenta, convertido con el `fx_rate` histórico del
  movimiento. Una operación histórica nunca se recalcula con el cambio actual.
- FIFO y coste medio en paralelo; la cuenta elige el método principal.
- Comisiones de compra capitalizadas; comisiones/impuestos de venta reducen el neto;
  dividendos netos de retención.
- Traspaso de valores sale por el coste retirado y entra por el coste declarado; no genera
  plusvalía. Traspaso de efectivo se compensa en el consolidado de la misma divisa.
- Sin cotización o sin cambio, la posición queda sin valorar y el total es parcial.
- XIRR/TWR solo se publican con datos suficientes; TWR explica el motivo cuando no.
- Cotizaciones/tipos manuales llevan `user_id`; las globales (proveedor) tienen `user_id`
  nulo. Un usuario no puede alterar la valoración de otro.

## API nueva (resumen)

- `GET /api/v1/markets`, `GET/POST /api/v1/instruments`, `POST/GET .../quotes`, `POST/GET /fx-rates`.
- `GET/POST /api/v1/real/accounts`, `GET/PATCH/DELETE .../{id}`.
- `GET .../{id}/summary`, `GET/POST .../{id}/movements`, `PATCH/DELETE .../movements/{mid}`.
- `GET /api/v1/real/overview`, `GET /api/v1/real/performance`.
- `POST .../{id}/imports/preview`, `POST .../imports/{batch}/confirm`, `DELETE .../imports/{batch}`.
- `POST/GET /api/v1/real/documents`, `POST .../{id}/extract`, `POST .../{id}/confirm`,
  `GET .../{id}/file`, `DELETE .../{id}`.
- `GET /api/v1/data/status|providers|runs|fx-rates|fundamentals|news`.
- `POST /api/v1/data/sync/fx|prices|fundamentals` (segundo plan por defecto) y
  `POST /api/v1/data/instruments/{uid}/auto-sync`.

## Migración y esquema

- Revisión inicial: `1af6489f6582`.
- Nueva revisión: `1a0119241c07` — mercados, instrumentos, cotizaciones, divisas, cuentas
  reales, movimientos, importaciones y documentos.
- Nueva revisión: `2b7d5f3a91e4` — runs de proveedor, caché, fundamentales, noticias y
  columnas `quotes.adjusted` / `fx_rates.kind` / `instruments.auto_sync_prices`.
- Verificada con `alembic upgrade head`, `alembic check` (sin operaciones pendientes) y
  `alembic downgrade base && alembic upgrade head` sobre SQLite temporal.
- Los mercados de referencia se siembran al arrancar (`app/services/reference.py`) de forma
  idempotente.

## Verificación exacta

```bash
python3 -m pytest
# 490 tests collected · 489 passed · 1 skipped (red) · 1 warning
# StarletteDeprecationWarning por httpx/testclient; no afecta al resultado.

python3 -m ruff check src app tests
# All checks passed!

cd web && npm run typecheck && npm run build
# typecheck OK; build OK: 59 módulos, JS 315,98 kB (92,00 kB gzip), CSS 29,54 kB (5,85 kB gzip)

rm -f var/migration.db
NEXO_DATABASE_URL=sqlite:///./var/migration.db alembic upgrade head
NEXO_DATABASE_URL=sqlite:///./var/migration.db alembic check
# No new upgrade operations detected.
```

Pruebas nuevas destacadas:

- `tests/platform/test_accounting_real.py`: FIFO vs media, dividendos, splits, traspasos,
  XIRR conocido, TWR, atribución cambiaria, ausencia de precio y rechazo de sobregiros.
- `tests/platform/test_api_real.py`: CRUD, aislamiento por usuario, cotizaciones privadas,
  `as_of`, overview por divisa e importación con duplicados/parcial.
- `tests/platform/test_imports_ocr.py`: decimales y fechas, CSV/XLSX, campos OCR.
- Documentos: firma real, 404 cruzado, OCR con extractor simulado, vínculo y bloqueo de borrado.
- `tests/platform/test_market_data.py` (20): procedencia de divisas, no sobrescritura sin
  `force`, caché, divergencias, 429 con reintentos, histórico, cierres/ajustados, frescura,
  caída de proveedor sin pérdida de datos, mercado no soportado, fundamentales solo
  reportados, requisito de CIK, aislamiento por usuario y validación de la API.
- `tests/platform/test_data_automation.py` (9): anti-duplicados en encolado, recuperación
  de runs interrumpidos, agotamiento de intentos, planificador apagado por defecto y
  programación de pares + instrumentos con auto-sync.

## Arranque local

```bash
python3 -m pip install -e ".[dev]"
export NEXO_SEC_CONTACT="tu-correo@dominio.com"
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
# API: http://localhost:8000/docs
cd web && npm install && npm run dev
```

Docker:

```bash
docker compose up -d --build
```

El contenedor instala `tesseract-ocr` y `tesseract-ocr-spa`, monta
`nexo-documents:/app/var/documents` y ejecuta `alembic upgrade head` antes de arrancar.

## Limitaciones y riesgos abiertos

1. Datos automáticos: cubiertos divisas (Frankfurter + ExchangeRate-API), precios
   históricos (StockAnalysis, US/DE/ES/GB) y fundamentales (SEC con CIK). Siguen sin
   proveedor dividendos, noticias, eventos y calendarios; LATAM sin cobertura de precios.
   No se declara tiempo real sin serlo.
2. OCR real no probado en este workspace: falta el binario Tesseract. El flujo con extractor
   simulado y la ruta de error 503 sí están probados.
3. Sin APK/Capacitor probado; la PWA es instalable, nada más.
4. La recopilación de datos tiene su cola ligera en proceso con recuperación y
   anti-duplicados; la investigación sigue con `JobRunner`. Ninguna soporta varias
   réplicas sin una cola compartida, y siguen sin haber alertas ni notificaciones.
5. Sin tesis versionadas, oportunidades por horizonte ni backtesting multimercado.
6. Consolidado multi-divisa solo por grupos; no hay total único sin tipo de cambio explícito.
7. SQLite no conserva precisión decimal exacta en almacenamiento; producción debe usar
   PostgreSQL.
8. No hay pruebas de navegador; la UI se verificó con TypeScript y build.
9. No se ha investigado la disponibilidad real de brókers desde Bolivia ni implicaciones
   fiscales; requiere trabajo documental y asesoría profesional, no código.
10. `main` no se ha tocado, el PR #2 no se ha fusionado y no se ha desplegado nada.

## Próximo paso recomendado

Fase 6: cola compartida (Redis/RQ o Celery) cuando haya varias réplicas, scheduler de
alertas y notificaciones PWA/Android, reintentos con criterios de negocio y ampliación de
la cobertura de datos (dividendos, eventos y noticias solo con un proveedor de licencia
clara; más mercados de precios). Cualquier proveedor de pago, OCR externo o envío de
documentos a terceros requiere autorización explícita.
