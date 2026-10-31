# Prueba histórica exploratoria — AAPL

**Regla evaluada:** momento 12 meses, rebalanceo mensual

**Parámetros fijados antes de mirar los resultados:** sin optimización. Ventana de 252 sesiones (≈ 1.0 años), rebalanceo cada 21 sesiones (≈ 1.0 meses), comisión 10.0 pb por operación y deslizamiento 5.0 pb.

**Fuente de precios:** https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=5y&interval=1d

**Nivel de procedencia de los precios:** external_downloaded

## Metodología

- Sin sesgo de anticipación: cada decisión de la sesión `i` usa únicamente precios con fecha igual o anterior a `i`. No se lee ninguna observación posterior (hay una prueba automática que lo comprueba comparando la serie completa con la serie recortada).
- La regla está invertida (mantiene el activo) cuando el cierre de la sesión supera el cierre de hace N sesiones, y en liquidez en caso contrario. La decisión se toma con datos de la propia sesión y se ejecuta a su cierre: supuesto declarado, no una ventaja.
- Sin ventas en corto, sin apalancamiento y sin relleno de huecos: las sesiones sin precio se descartan.
- El efectivo no remunera intereses. Los precios son ajustados por dividendos y desdoblamientos, y los huecos de negociación se descartan en lugar de rellenarse.
- Comparación con mantener el activo (buy & hold) desde la misma fecha inicial, con los mismos costes de entrada.

## Resultados

| Serie | Sesiones | Rentabilidad total | Anualizada | Volatilidad anualizada | Caída máxima | Sesiones invertido |
| --- | --- | --- | --- | --- | --- | --- |
| Estrategia (periodo completo) | 1253 | 65.07 % | 10.61 % | 21.96 % | -33.36 % | 855 |
| Buy & hold (periodo completo) | 1253 | 132.90 % | 18.53 % | 28.01 % | -33.36 % | 1254 |
| Estrategia (desarrollo) | 751 | 24.63 % | 7.67 % | 16.98 % | -16.61 % | 395 |
| Buy & hold (desarrollo) | 751 | 53.42 % | 15.45 % | 27.60 % | -30.91 % | 752 |
| Estrategia (evaluación) | 501 | 31.97 % | 14.97 % | 27.81 % | -33.36 % | 460 |
| Buy & hold (evaluación) | 501 | 51.25 % | 23.14 % | 28.65 % | -33.36 % | 502 |

Operaciones cerradas: 2. Posición abierta al final: sí.

La separación desarrollo/evaluación busca detectar el ajuste excesivo. Como los parámetros no se han optimizado sobre el tramo de desarrollo, esa separación aquí sirve de control de estabilidad, no de validación formal.

## Limitaciones de esta prueba

- Un solo activo y un solo periodo: no hay evidencia de generalización.
- No se corrige por comparaciones múltiples: cambiar de activo o de periodo cambia el resultado.
- Los resultados son sensibles a la ventana elegida y a los costes aplicados.
- El periodo incluye el comportamiento concreto del mercado en esos años, que no tiene por qué repetirse.
- No se modelan impuestos, ni dividendos cobrados en efectivo (están dentro del precio ajustado), ni la liquidez real de las órdenes.

## Procedencia y limitaciones de los datos

- Fuente no oficial (Yahoo Finance): endpoint público sin garantía de exactitud ni disponibilidad.
- Nivel de procedencia EXTERNAL_DOWNLOADED: la descarga funcionó, la serie no está verificada.
- No se ha contrastado con un proveedor oficial de precios ni con el mercado de origen.
- Los precios ajustados incorporan dividendos y desdoblamientos; el ajuste puede diferir entre proveedores.

**Conclusión:** esta prueba no demuestra que la estrategia sea rentable. Un solo activo, un solo periodo y una única regla no permiten afirmarlo; el resultado sirve para estudiar el comportamiento de la regla y sus costes, no para recomendarla.