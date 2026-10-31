"""Precios para la cartera simulada.

La cartera no es dinero real. Aun así, valorar posiciones con precios de mercado
exige declarar de dónde salen:

- `YahooPriceProvider` usa la serie diaria de Yahoo Finance (fuente no oficial),
  con caché en disco y sin rellenar huecos. Si la descarga falla, devuelve `None`
  y la interfaz muestra la posición a coste con el aviso correspondiente.
- `StaticPriceProvider` se usa en pruebas y en modo demostración.

Nunca se inventa un precio: sin precio, la posición se marca como no valorada.
"""

from __future__ import annotations

import threading
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Optional, Protocol, Sequence

from nexo_invest.data.prices import PriceSeries, YahooPriceClient


class PriceProvider(Protocol):
    name: str

    def last_price(self, symbol: str) -> Optional[float]: ...

    def history(self, symbol: str, start: date) -> Optional[Dict[date, float]]: ...


class StaticPriceProvider:
    name = "static"

    def __init__(self, prices: Dict[str, float], history: Optional[Dict[str, Dict[date, float]]] = None) -> None:
        self.prices = {k.upper(): v for k, v in prices.items()}
        self._history = history or {}

    def last_price(self, symbol: str) -> Optional[float]:
        return self.prices.get(symbol.upper())

    def history(self, symbol: str, start: date) -> Optional[Dict[date, float]]:
        series = self._history.get(symbol.upper())
        if not series:
            return None
        return {day: value for day, value in series.items() if day >= start}


class YahooPriceProvider:
    name = "yahoo"

    def __init__(self, cache_dir: Optional[str] = None, *, ttl_seconds: float = 600.0) -> None:
        self.client = YahooPriceClient(
            cache_dir=Path(cache_dir) if cache_dir else None
        )
        self.ttl = ttl_seconds
        self._cache: Dict[str, tuple[float, PriceSeries]] = {}
        self._lock = threading.Lock()

    def _series(self, symbol: str, range_: str) -> Optional[PriceSeries]:
        key = f"{symbol.upper()}:{range_}"
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] < self.ttl:
                return cached[1]
        try:
            series = self.client.fetch_series(symbol.upper(), range_=range_)
        except Exception:
            return None
        with self._lock:
            self._cache[key] = (time.monotonic(), series)
        return series

    def last_price(self, symbol: str) -> Optional[float]:
        series = self._series(symbol, "1mo")
        if series is None or not series.closes:
            return None
        for value in reversed(series.closes):
            if value is not None:
                return float(value)
        return None

    def history(self, symbol: str, start: date) -> Optional[Dict[date, float]]:
        series = self._series(symbol, "5y")
        if series is None:
            return None
        points: Dict[date, float] = {}
        for day, value in zip(series.dates, series.closes):
            if value is not None and day >= start:
                points[day] = float(value)
        return points or None


def price_on_or_before(history: Sequence[tuple[date, float]], when: date) -> Optional[float]:
    best: Optional[float] = None
    for day, value in history:
        if day <= when:
            best = value
    return best


def default_provider(name: str, cache_dir: str) -> PriceProvider:
    if name == "yahoo":
        return YahooPriceProvider(cache_dir)
    return StaticPriceProvider({})


def benchmark_return(
    provider: PriceProvider, symbol: str, start: date, end: Optional[date] = None
) -> Optional[float]:
    history = provider.history(symbol, start)
    if not history:
        return None
    days = sorted(history)
    if len(days) < 2:
        return None
    first = history[days[0]]
    last_day = max(d for d in days if end is None or d <= end)
    last = history[last_day]
    if not first:
        return None
    return last / first - 1.0


def window_start(days: int = 365) -> date:
    return date.today() - timedelta(days=days)
