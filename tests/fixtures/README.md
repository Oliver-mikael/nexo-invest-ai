# Fixtures de pruebas

## `sec_companyfacts_aapl_subset.json`

**Qué es**: subconjunto reducido de un documento real de SEC EDGAR, guardado para que
las pruebas unitarias no dependan de Internet. Es un **fixture de prueba**
(`ProvenanceLevel.LOCAL_FIXTURE`): nunca debe presentarse como dato vivo verificado.

| Campo | Valor |
| --- | --- |
| Fuente | SEC EDGAR, API pública de hechos XBRL |
| URL original | `https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json` |
| Entidad | Apple Inc. (CIK 320193) |
| Fecha de consulta | 2026-10-27 (UTC) |
| SHA-256 del documento completo descargado | `73a86c6aedc31f77cac2ea4df5f80f0b3bd7e6eb58bb4e01444fbedf3afb9c43` |
| SHA-256 de este subconjunto | `c01b587260d900f9fb7cfc7491cd9dcd0fe7269212eff4d2cfd0bf755ba8e382` |
| Tamaño | ~136 KB, 588 entradas de hechos, 26 conceptos us-gaap |

**Transformaciones aplicadas** (documentadas para que nadie confunda el subconjunto con
el documento original):

1. Se conservan solo los conceptos usados por `nexo_invest.data.sec_edgar.CONCEPT_MAP`.
2. Se conservan solo hechos con `form` igual a `10-K`; para tres conceptos
   (ingresos, resultado neto y flujo de caja operativo) se conservan también `10-Q`
   para poder probar el cálculo de TTM sobre trimestres consecutivos reales.
3. Se conservan solo los años fiscales 2020-2025.
4. Se conservan solo las unidades `USD` y `shares`.
5. Se eliminan las cláusulas `label`, `description` y demás metadatos no usados.

**Lo que este fixture NO es**: no es una copia completa del documento, no permite
verificar la ausencia de conceptos que sí existían en el original y no sustituye la
consulta real. Para trabajar con datos actuales hay que usar el cliente contra SEC EDGAR
(`nexo sec-report`).

## `yahoo_aapl_5y.json`

**Qué es**: descarga real de la serie diaria de AAPL guardada para que las pruebas no usen
red. Es una copia de una descarga real, con nivel `EXTERNAL_DOWNLOADED` conservado: la
fuente (Yahoo Finance) es **no oficial**.

| Campo | Valor |
| --- | --- |
| Fuente | Yahoo Finance, endpoint público `chart` (sin clave) |
| URL original | `https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=5y&interval=1d` |
| Símbolo | AAPL · moneda USD |
| Sesiones | 1 254, de 2021-10-28 a 2026-10-27 |
| Fecha de descarga | 2026-10-27 |
| SHA-256 | `dc47cd4772ae8a6929d7ff5d0fd01c574cdf29c95dec56b6216f24de182fdecd` |
| Tamaño | 139.709 bytes |
| Transformaciones | ninguna: respuesta JSON completa tal cual se recibió |

**Lo que este fixture NO es**: no es una fuente oficial de precios, no refleja sesiones
posteriores a la descarga y no sustituye la comprobación contra el mercado de origen.

## `nasdaq_aapl_financials.json`

**Qué es**: descarga real del estado de resultados anual de AAPL desde la API pública de
Nasdaq, usada como **segunda fuente** en el contraste de ingresos.

| Campo | Valor |
| --- | --- |
| Fuente | Nasdaq (`api.nasdaq.com`), endpoint público sin clave |
| URL original | `https://api.nasdaq.com/api/company/AAPL/financials?assetclass=stocks` |
| Entidad | AAPL (Apple Inc.) |
| Cierres publicados | 2025-09-27, 2024-09-28, 2023-09-30, 2022-09-24 |
| Fecha de consulta | 2026-10-28 |
| SHA-256 | `a424b826d7bf153b8fc12825383119bae2955be277a78519b9e173b49fdc50dd` |
| Tamaño | 10.680 bytes |
| Transformaciones | ninguna: respuesta JSON completa tal cual se recibió |

**Unidad**: el endpoint **no declara** la unidad de las cifras (llegan como `$416,161,000`
para unos ingresos de 416.161 millones de USD). La relación ×1000 se infiere por contraste
con SEC EDGAR y se registra como inferida, nunca como declarada.

**Lo que este fixture NO es**: no es una fuente primaria. Nasdaq redistribuye cifras
derivadas de los mismos documentos que presenta la empresa.

## `nasdaq_aapl_historical_2026-10.json`

**Qué es**: descarga real de cierres diarios (`Close/Last`) de AAPL durante octubre de 2026,
usada como segunda fuente en la comprobación del precio de 2026-10-27.

| Campo | Valor |
| --- | --- |
| Fuente | Nasdaq (`api.nasdaq.com`), endpoint público sin clave |
| URL original | `https://api.nasdaq.com/api/quote/AAPL/historical?assetclass=stocks&fromdate=2026-10-01&todate=2026-10-28&limit=20` |
| Símbolo | AAPL |
| Sesiones | 19, de 2026-10-01 a 2026-10-27 |
| Fecha de consulta | 2026-10-28 |
| SHA-256 | `36f8bfd511652ca1f5e1cb73e0c93842c95d48872d89c65228fc4b9ef9bf554a` |
| Tamaño | 2.412 bytes |
| Transformaciones | ninguna: respuesta JSON completa tal cual se recibió |

**Lo que este fixture NO es**: no es el tape oficial ni una fuente de precio verificada por
sí sola; sirve para el contraste con otra fuente. Cierre 2026-10-27: `347,10`.
