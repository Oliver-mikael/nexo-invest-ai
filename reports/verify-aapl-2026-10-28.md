# Nexo Invest AI — Verificación de datos y valoración: Apple Inc.

**Generado:** 2026-10-28T14:29:18.064427+00:00 · **Ticker:** AAPL

**Naturaleza del documento:** comprobación reproducible de datos y sensibilidad de la valoración a supuestos. No es asesoramiento financiero ni recomendación de compra o venta.

## 1. Contraste de ingresos: fuente primaria vs. segunda fuente

| Campo | Fuente primaria | Segunda fuente |
| --- | --- | --- |
| Origen | SEC EDGAR (XBRL, documento presentado) | Nasdaq (api.nasdaq.com, estado de resultados) |
| URL | https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json | https://api.nasdaq.com/api/company/AAPL/financials?assetclass=stocks |
| Fecha de consulta | 2026-10-27 | 2026-10-28 |
| Periodo fiscal (cierre) | 2025-09-27 | 2025-09-27 |
| Cifra | 416,161,000,000 USD (units) | 416,161,000,000 USD (celda original 416,161,000 USD, unidad inferida ×1000) |
| Referencia | rol=anual form=10-K fy=2025 fp=FY filed=2025-10-31 accn=0000320193-25-000079 concepto=RevenueFromContractWithCustomerExcludingAssessedTax | AAPL · columna Total Revenue · cierres: 2025-09-27, 2024-09-28, 2023-09-30, 2022-09-24 |

**Resultado:** coincide con la segunda fuente.

- Coinciden dentro de la tolerancia 0.1000% con la relación de unidad inferida ×1000.
- Trazabilidad: fuente secundaria registrada en el registro de procedencia «nasdaq-financials-aapl» y la observación primaria de ingresos del cierre 2025-09-27 pasó a external_corroborated con esa evidencia en sus notas.

Limitaciones de este contraste:

- Nasdaq es una distribución independiente del mismo documento presentado por la empresa, no una fuente primaria distinta: la coincidencia comprueba la cadena de distribución, no una medición independiente.
- La relación de unidad (×1000) está inferida; el endpoint no la declara.
- Las cifras de ambas fuentes están en distinta escala; el valor alineado se obtuvo multiplicando el de la segunda fuente por 1000.

## 2. Precio de cierre verificado

| Campo | Valor |
| --- | --- |
| Símbolo | AAPL |
| Fecha de negociación | 2026-10-27 |
| Cierre sin ajustar | 347.10 USD |
| Cierre ajustado (misma sesión) | 347.10 USD |
| Primera fuente | Yahoo Finance · chart (cierre sin ajustar) (https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=6mo&interval=1d) |
| Fecha de consulta (primera) | 2026-10-28 |
| Segunda fuente | Nasdaq · Close/Last · AAPL (https://api.nasdaq.com/api/quote/AAPL/historical?assetclass=stocks&fromdate=2026-04-28&todate=2026-10-28&limit=4000) |
| Fecha de consulta (segunda) | 2026-10-28 |
| Diferencia relativa | 0.000002% |
| Resultado | coincide con la segunda fuente |
| Nivel de procedencia | external_corroborated |

- Coinciden dentro de la tolerancia 0.0500% (diferencia relativa 0.000002%).

Limitaciones del precio:

- Yahoo Finance y Nasdaq son agregadores: ninguno es el mercado oficial ni el SIP. La coincidencia comprueba dos distribuciones independientes, no el tape oficial.
- El cierre comparado es sin ajustar. Los ajustes por dividendo o desdoblamiento se aplican en momentos distintos según el proveedor.

## 3. Valoración por escenarios con el precio comprobado

Precio usado en la comparación: **347.10 USD** (2026-10-27, cierre sin ajustar, coincidente en dos fuentes).

**Fórmulas declaradas** (ninguna es una predicción):

- Valor de empresa = Σ FCF proyectado / (1 + t)^t + valor terminal descontado (Gordon Growth: FCF_terminal = FCF_último × (1 + g) / (r − g)).
- Valor de patrimonio = valor de empresa − deuda neta (cuando la deuda neta está observada; si no, se declara y no se asume cero).
- Valor por acción = valor de patrimonio / acciones en circulación.
- Margen de subida = valor por acción / precio − 1.
- **Margen de seguridad = 1 − precio / valor por acción** (Graham). Solo se muestra con precio comprobado y valor por acción positivo.

### Escenario: bajista — crecimiento bajo, presion en margenes y descuento alto

- **Crecimiento aplicado al flujo de caja libre:** 1.00%, 1.00%, 1.00%, 1.00%, 1.00% (durante 5 años). El motor proyecta el flujo, no los ingresos: este porcentaje no es un crecimiento de ventas medido.
- **Tasa de descuento:** 10.50%
- **Crecimiento terminal:** 1.50%
- **Valor terminal (VP):** 568,487,423,169.05 USD
- **Valor de empresa:** 872,612,756,577.74 USD
- **Valor de equity:** 828,652,756,577.74 USD
- **Valor estimado por acción:** 56.0914 USD
- **Precio actual (verificado):** 347.10 USD
- **Margen de subida/bajada:** -83.84%

**Múltiplos de comparables (mediana, simulados):**
  - revenue_multiple: no disponible
  - ebitda_multiple: no disponible
  - pe_multiple: no disponible

Notas:
  - base_fcf_scale: units
  - base_fcf_currency: USD
  - comparables_origen: desconocido
  - net_debt: incluida en el calculo del valor de patrimonio

- **Margen de seguridad:** -518.81 % — **negativo**, es decir: con estos supuestos el precio supera el valor estimado por acción. No hay margen de seguridad y, aun así, esto no es una recomendación de venta: la cifra mide la sensibilidad a los supuestos, no el precio justo.

### Escenario: base — crecimiento moderado y margenes estables

- **Crecimiento aplicado al flujo de caja libre:** 4.00%, 4.00%, 4.00%, 4.00%, 4.00% (durante 5 años). El motor proyecta el flujo, no los ingresos: este porcentaje no es un crecimiento de ventas medido.
- **Tasa de descuento:** 8.50%
- **Crecimiento terminal:** 2.50%
- **Valor terminal (VP):** 1,365,219,500,636.52 USD
- **Valor de empresa:** 1,800,903,514,951.56 USD
- **Valor de equity:** 1,756,943,514,951.56 USD
- **Valor estimado por acción:** 118.9273 USD
- **Precio actual (verificado):** 347.10 USD
- **Margen de subida/bajada:** -65.74%

**Múltiplos de comparables (mediana, simulados):**
  - revenue_multiple: no disponible
  - ebitda_multiple: no disponible
  - pe_multiple: no disponible

Notas:
  - base_fcf_scale: units
  - base_fcf_currency: USD
  - comparables_origen: desconocido
  - net_debt: incluida en el calculo del valor de patrimonio

- **Margen de seguridad:** -191.86 % — **negativo**, es decir: con estos supuestos el precio supera el valor estimado por acción. No hay margen de seguridad y, aun así, esto no es una recomendación de venta: la cifra mide la sensibilidad a los supuestos, no el precio justo.

### Escenario: alcista — crecimiento alto sostenido y mejora de margen

- **Crecimiento aplicado al flujo de caja libre:** 7.00%, 7.00%, 7.00%, 7.00%, 7.00% (durante 5 años). El motor proyecta el flujo, no los ingresos: este porcentaje no es un crecimiento de ventas medido.
- **Tasa de descuento:** 7.50%
- **Crecimiento terminal:** 3.00%
- **Valor terminal (VP):** 2,429,438,030,917.23 USD
- **Valor de empresa:** 2,965,123,580,691.12 USD
- **Valor de equity:** 2,921,163,580,691.12 USD
- **Valor estimado por acción:** 197.7332 USD
- **Precio actual (verificado):** 347.10 USD
- **Margen de subida/bajada:** -43.03%

**Múltiplos de comparables (mediana, simulados):**
  - revenue_multiple: no disponible
  - ebitda_multiple: no disponible
  - pe_multiple: no disponible

Notas:
  - base_fcf_scale: units
  - base_fcf_currency: USD
  - comparables_origen: desconocido
  - net_debt: incluida en el calculo del valor de patrimonio

- **Margen de seguridad:** -75.54 % — **negativo**, es decir: con estos supuestos el precio supera el valor estimado por acción. No hay margen de seguridad y, aun así, esto no es una recomendación de venta: la cifra mide la sensibilidad a los supuestos, no el precio justo.

Los escenarios son sensibilidad a supuestos, no previsiones. El escenario base no es una predicción segura y este documento no recomienda comprar ni vender.

## 4. Comprobaciones adicionales

- Prueba histórica (2021-10-28 → 2026-10-27, 1253 sesiones): estrategia 65.07%, buy & hold 132.90%, caída máxima -33.36%, 3 entradas y 2 operaciones cerradas, comisión 10 pb y deslizamiento 5 pb por operación.
- La regla **no supera** a comprar y mantener en este periodo: la diferencia no se oculta ni se reencuadra.
- - **[OK]** rentabilidad total de la estrategia: publicado 0.6507210439067821 vs recalculado 0.6507210439
- - **[OK]** rentabilidad anualizada: publicado 0.10605811991531455 vs recalculado 0.10605811991531455
- - **[OK]** caída máxima de la estrategia: publicado -0.33360517686285596 vs recalculado -0.33360517686285596
- - **[OK]** rentabilidad del buy & hold: publicado 1.3289703525403191 vs recalculado 1.3289703525
- - **[OK]** orden temporal de las operaciones: 3 operaciones, 2 cerradas, todas dentro de la serie
- - **[OK]** ausencia de sesgo de anticipación: curva idéntica hasta 2024-04-29 con la serie recortada
- - **[informativo]** tratamiento de dividendos: ambas series usan precios ajustados por dividendos y desdoblamientos; el efectivo en liquidez no genera rendimiento (limitación declarada)

Nota de procedencia del precio: Cierre sin ajustar de 2026-10-27 coincidente en Yahoo Finance y Nasdaq; nivel EXTERNAL_CORROBORATED. Ninguna de las dos fuentes es el mercado oficial.