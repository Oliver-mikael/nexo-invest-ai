# VALIDACIÓN — Nexo Invest AI

Registro de las comprobaciones hechas contra datos reales. La validación comprueba que el
software funciona y que sus cifras son trazables; **no** es una recomendación de inversión.

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
