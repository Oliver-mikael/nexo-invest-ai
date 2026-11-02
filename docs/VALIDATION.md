# VALIDACIÓN — Nexo Invest AI

Registro de las comprobaciones hechas contra datos reales. La validación comprueba que el
software funciona y que sus cifras son trazables; **no** es una recomendación de inversión.

## 2026-10-31 · Plataforma 2.0 · cartera real multimercado

Entorno: Python 3.10.12, SQLite temporal, Node 22. **Sin red** en todas las pruebas de esta
validación. No se consultaron proveedores externos, no se contrató nada y no se enviaron
documentos a terceros.

### 1. Suite completa

```bash
python3 -m pytest
# 461 tests collected · 460 passed · 1 skipped · 1 warning (Starlette/httpx)
```

La prueba omitida es la histórica que depende de red. Las 461 incluyen el motor, la
plataforma v1 y las nuevas pruebas de cartera real, importación, OCR y documentos.

### 2. Lint, tipos y build

```bash
python3 -m ruff check src app tests
# All checks passed!

cd web && npm run typecheck && npm run build
# TS OK · 58 módulos · JS 298,33 kB (87,67 kB gzip) · CSS 29,39 kB (5,82 kB gzip)
```

### 3. Migraciones

```bash
rm -f var/migration.db
NEXO_DATABASE_URL=sqlite:///./var/migration.db alembic upgrade head
NEXO_DATABASE_URL=sqlite:///./var/migration.db alembic check
# No new upgrade operations detected.
NEXO_DATABASE_URL=sqlite:///./var/migration.db alembic downgrade base
NEXO_DATABASE_URL=sqlite:///./var/migration.db alembic upgrade head
# OK: ciclo completo sin errores.
```

Revisión nueva: `1a0119241c07` sobre `1af6489f6582`.

### 4. Pruebas numéricas verificables

`tests/platform/test_accounting_real.py` fija, entre otros:

- Compra 10 @100 + 10 @200, venta 10 @300 con comisión 10:
  - FIFO: realizado 1.990; coste restante 2.000.
  - Coste medio: realizado 1.490; coste restante 1.500.
- Depósito 1.000, compra 10 @10 con comisión 5, dividendo bruto 20 con retención 2 y venta
  10 @12 con comisión 1: efectivo 1.032; resultado neto 32; dividendos netos 18.
- Instrumento EUR en cuenta USD: coste 1.100 USD, valor 1.440 USD, no realizado 340;
  efecto precio 240 y efecto cambiario 100 (suma exacta).
- Split 2:1: 10 acciones a coste 100 → 20 a coste 50; venta 20 @60 deja realizado 200.
- XIRR 1.000 → 1.100 en 366 días: 9,97 % anualizado a 365 días.
- TWR con aporte intermedio: 1.000 → 1.100 + 100 → 1.320 da 21 %.
- Sin cotización: `total_value_base = None`, `complete = False`, activo en `missing_prices`.
- Traspaso mal declarado (coste 900 sobre un coste real 1.000): no fabrica una pérdida; el
  flujo externo usa el coste retirado y el resultado es 0.

### 5. Aislamiento comprobado

- Otro usuario recibe 404 en cuenta, summary, movimientos, importación y documento.
- Una cotización manual del usuario A no valora la posición del usuario B; la lista de
  cotizaciones de B no muestra la de A.
- El documento descargado exige token y pertenencia; un documento vinculado no se borra.
- La cartera simulada sigue en 0 tras registrar movimientos reales.

### 6. Lo que **no** se validó

- OCR real de extremo a extremo: el binario `tesseract-ocr` no está instalado en el workspace.
  Se probó el flujo con un extractor simulado y la ruta 503. El contenedor sí instala Tesseract.
- Proveedores automáticos de precios, noticias, dividendos o calendarios: no implementados.
- Android/Capacitor: no generado ni probado.
- Ninguna operación financiera real, ninguna conexión a bróker y ninguna publicación.

## 2026-10-31 · Apple y Microsoft con datos en vivo

Entorno: Python 3.10.12, paquete instalado en modo editable, contacto SEC identificable
configurado en `NEXO_SEC_CONTACT` (no se imprime en este documento).

### 1. Descarga y análisis de Apple Inc. (CIK 320193)

```bash
nexo sec-report --ticker AAPL --out reports/aapl-sec-2026-10-31.md --cache-dir .cache/sec
```

- Resultado: 1.591 observaciones (1.582 validadas, 6 corroboradas, 3 sin validar).
- Periodo más reciente: 2025-09-27 (cierre del ejercicio fiscal 2025).
- Estado de calidad: `validada`.
- Informe: `reports/aapl-sec-2026-10-31.md`.

### 2. Descarga y análisis de Microsoft Corporation (CIK 789019)

```bash
nexo sec-report --ticker MSFT --out reports/msft-sec-2026-10-31.md --cache-dir .cache/sec
```

- Resultado: 1.741 observaciones (1.721 validadas, 8 corroboradas, 12 sin validar).
- Periodo más reciente: 2026-06-30.
- Estado de calidad: `validada`.
- Informe: `reports/msft-sec-2026-10-31.md`.

### 3. Documento primario frente a CompanyFacts (Apple, 10-K FY2025)

```bash
nexo primary-verify --ticker AAPL --cik 320193 \
  --accession 0000320193-25-000079 \
  --url https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm \
  --form 10-K --fiscal-year 2025 --period-start 2024-09-29 --period-end 2025-09-27 \
  --concept us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax \
  --out reports/primary-aapl-fy2025-2026-10-31.md --cache-dir .sec_cache
```

- Documento descargado: 10-K de Apple, SHA-256 `943b1a02c71816719ee9f8457016651e2ccd929e7c938da48f6a67d39dd6bca7`
  (idéntico al registrado en la validación del 2026-10-30: el documento no ha cambiado).
- Valor extraído del HTML: 416.161.000.000 USD.
- Valor en CompanyFacts: 416.161.000.000 USD.
- Resultado: **coincide**.

### 4. Sensibilidad (nueva en este ciclo)

El informe de Apple incluye la tabla de sensibilidad del escenario base:

| Tasa de descuento | g = 2,00 % | g = 2,50 % | g = 3,00 % |
| --- | --- | --- | --- |
| 7,50 % | 132,40 | 143,47 | 157,01 |
| 8,50 % (base) | 111,40 | 118,93 | 127,82 |
| 9,50 % | 96,01 | 101,40 | 107,62 |

Valores por acción en USD. Se mueven en la dirección esperada: sube el valor al bajar la tasa
de descuento y al subir el crecimiento terminal. Son sensibilidad a supuestos, no precios
objetivo.

### 5. Qué **no** se validó

- No se ejecutó `nexo verify` (contraste con Nasdaq y precio de Yahoo) contra la red en esta
  fecha: `api.nasdaq.com` corta en silencio los `User-Agent` con URL de contacto (limitación
  ya documentada en `docs/KNOWN_ISSUES.md`). La ruta está cubierta por pruebas con fixtures
  congelados.
- No se verificaron segmentos ni concentración de clientes: la fuente CompanyFacts no los
  publica y el sistema no los inventa.
- La coincidencia HTML/CompanyFacts valida la extracción de dos formatos de la **misma**
  presentación de la SEC, no una medición independiente.

## 2026-11-02 · Fase 5 · datos financieros automáticos

Entorno: Python 3.10.12, Node 22, SQLite temporal. **La suite de pruebas no usa red**
(respuestas simuladas con `httpx.MockTransport`); las comprobaciones contra proveedores
reales se ejecutan aparte y se documentan aquí.

### 1. Suite completa

```bash
python3 -m pytest -o addopts="" -q
# 490 tests collected · 489 passed · 1 skipped · 1 warning (Starlette/httpx)
```

Las 29 pruebas nuevas (`tests/platform/test_market_data.py`, `tests/platform/test_data_automation.py`)
cubren: procedencia de divisas, no sobrescritura sin `force`, caché anti-duplicados,
divergencia entre fuentes, 429 con reintentos acotados, rango histórico, cierres y ajustados,
frescura `stale`, caída del proveedor sin pérdida de datos, mercado no soportado, solo métricas
reportadas en fundamentales, requisito de CIK, aislamiento por usuario en `/data/fx-rates`,
validación de la API, encolado anti-duplicados, recuperación de runs interrumpidos y
planificador apagado por defecto.

### 2. Lint, tipos y build

```bash
python3 -m ruff check src app tests
# All checks passed!

cd web && npm run typecheck && npm run build
# TS OK · 59 módulos · JS 315,98 kB (92,00 kB gzip) · CSS 29,54 kB (5,85 kB gzip)
```

### 3. Migraciones

```bash
NEXO_DATABASE_URL=sqlite:///./var/migration.db alembic upgrade head
NEXO_DATABASE_URL=sqlite:///./var/migration.db alembic check
# No new upgrade operations detected.
NEXO_DATABASE_URL=sqlite:///./var/migration.db alembic downgrade base
NEXO_DATABASE_URL=sqlite:///./var/migration.db alembic upgrade head
# OK: ciclo completo sin errores.
```

Revisión nueva: `2b7d5f3a91e4` sobre `1a0119241c07` (tablas `provider_runs`, `data_cache`,
`fundamentals`, `news_items`; columnas `quotes.adjusted`, `fx_rates.kind`,
`instruments.auto_sync_prices`).

### 4. Integraciones reales verificadas en vivo (2026-11-02)

Ejecutadas con los propios adaptadores y `HttpFetcher` reales (fuera de la suite):

1. **Frankfurter v2** `rates?base=USD&quotes=BOB,EUR` → 200:
   BOB 12,0806 (dato 2026-11-01) y EUR 0,89468 (dato 2026-11-02), calidad `close`.
2. **Frankfurter rango histórico** 2026-10-20 → 2026-10-24 → 4 observaciones
   (2026-10-24 es sábado: sin sesión, no se rellena).
3. **ExchangeRate-API** `latest/USD` → 200: BOB 12,102823 y EUR 0,896073 (dato
   2026-11-02), naturaleza `market` (no se presenta como oficial).
4. **StockAnalysis** histórico diario 26-30 oct 2026 en cuatro mercados:
   AAPL/XNAS 344,63 · SAP/XETR 235,02 · SAN/XMAD 11,19 · VOD/XLON 15,88.
5. **StockAnalysis con mercado no soportado** (XMEX/México) → `ProviderDataError`
   explícito: «El mercado 'XMEX' no está soportado… No se sustituye por otro mercado».
6. **SEC EDGAR companyfacts** (CIK 320193, con `NEXO_SEC_CONTACT`) → 2 periodos:
   anual FY2025 (ingresos 416.161.000.000, beneficio 112.010.000.000, EPS 7,46) y
   trimestre 2026-06-27 (ingresos 109.417.000.000). EBITDA/FCF quedan `null`.

Comprobación adicional del 2026-10-31 (misma rama): Stooq se descartó tras verificar que
exige API key con CAPTCHA y limita el uso a particular; Yahoo devolvió 429 en este entorno.

### 5. Lo que **no** se validó en esta fase

- La automatización en horario: el planificador está apagado por defecto (`interval=0`);
  sus estados se prueban con un servicio falso, no con ejecución cron real.
- Noticias y eventos: no hay proveedor con licencia clara; `available: false` es el estado
  real, no una omisión.
- Cobertura de precios fuera de US/DE/ES/GB y fundamentales fuera de emisores con CIK:
  declarada como no soportada, sin sustituto.
- Sin pruebas de navegador para la página `/datos`; se verifica con TypeScript y build.
