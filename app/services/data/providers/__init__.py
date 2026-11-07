"""Adaptadores de proveedores de datos de mercado.

Todos implementan interfaces pequeñas y normalizan a los tipos de `base`:
`FxObservation`, `PriceBar` y `FundamentalObservation`. Cambiar de proveedor no
toca el motor contable ni la valoración: solo cambia quién llena las tablas
`fx_rates` y `quotes` con su procedencia.
"""

from __future__ import annotations

from app.services.data.providers.frankfurter import FrankfurterProvider
from app.services.data.providers.exchangerate import ExchangeRateApiProvider
from app.services.data.providers.sec_fundamentals import SecFundamentalsProvider
from app.services.data.providers.stockanalysis import StockAnalysisProvider

__all__ = [
    "FrankfurterProvider",
    "ExchangeRateApiProvider",
    "StockAnalysisProvider",
    "SecFundamentalsProvider",
]
