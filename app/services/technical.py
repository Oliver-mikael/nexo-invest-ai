"""Indicadores técnicos deterministas sobre cotizaciones almacenadas (Fase 7).

Nada aquí invoca proveedores: los indicadores se calculan con los cierres con
procedencia que ya están en la base. Cada bloque declara qué datos necesita y
cuántos hay; con historial insuficiente devuelve `available: false` con el
motivo en lugar de números parciales con apariencia de resumen.

Definiciones (con ficha para reproducibilidad):

- SMA de N observaciones: media aritmética de los últimos N cierres por fecha.
- RSI de Wilder con N=14: primer paso media simple de las primeras 14
  variaciones, después suavizado 1/N.
- Momentum: variación total de precio entre dos fechas separadas N días.
- Máximo retroceso (drawdown): caída acumulada máxima respecto al máximo
  previo dentro del historial analizado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple


SMA_FAST = 20
SMA_SLOW = 50
SMA_LONG = 200
RSI_DAYS = 14
MOMENTUM_DAYS = 20

_MIN_FOR_DRAWDOWN = 2


@dataclass
class PricePoint:
    as_of: date
    price: Decimal


@dataclass
class IndicatorResult:
    observations: int = 0
    first_day: Optional[date] = None
    last_day: Optional[date] = None
    last_price: Optional[Decimal] = None
    sma_fast: Optional[Decimal] = None
    sma_slow: Optional[Decimal] = None
    sma_long: Optional[Decimal] = None
    rsi: Optional[Decimal] = None
    momentum_pct: Optional[Decimal] = None
    max_drawdown_pct: Optional[Decimal] = None
    trend: str = ""
    missing: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        def text(value: Optional[Decimal]) -> Optional[str]:
            return None if value is None else str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

        return {
            "observations": self.observations,
            "first_day": self.first_day.isoformat() if self.first_day else None,
            "last_day": self.last_day.isoformat() if self.last_day else None,
            "last_price": text(self.last_price),
            "sma_fast": text(self.sma_fast),
            "sma_slow": text(self.sma_slow),
            "sma_long": text(self.sma_long),
            "rsi": text(self.rsi),
            "momentum_pct": text(self.momentum_pct),
            "max_drawdown_pct": text(self.max_drawdown_pct),
            "trend": self.trend,
            "missing": list(self.missing),
            "available": not self.missing,
        }


def _sma(values: List[Decimal], days: int) -> Optional[Decimal]:
    if len(values) < days:
        return None
    window = values[-days:]
    return sum(window) / Decimal(days)


def _rsi(points: List[Tuple[date, Decimal]], days: int) -> Optional[Decimal]:
    if len(points) < days + 1:
        return None
    changes: List[Tuple[Decimal, Decimal]] = []
    for previous, current in zip(points, points[1:days + 1]):
        change = current[1] - previous[1]
        changes.append((change if change > 0 else Decimal(0), -change if change < 0 else Decimal(0)))
    total_gains = sum(g for g, _ in changes) / Decimal(days)
    total_losses = sum(loss for _, loss in changes) / Decimal(days)
    for previous, current in zip(points[days:], points[days + 1:]):
        change = current[1] - previous[1]
        gain = change if change > 0 else Decimal(0)
        loss = -change if change < 0 else Decimal(0)
        total_gains = (total_gains * (Decimal(days - 1)) + gain) / Decimal(days)
        total_losses = (total_losses * (Decimal(days - 1)) + loss) / Decimal(days)
    if total_losses == 0:
        return Decimal(100)
    rs = total_gains / total_losses
    return Decimal(100) - Decimal(100) / (Decimal(1) + rs)


def _max_drawdown_pct(points: List[Tuple[date, Decimal]]) -> Optional[Decimal]:
    if len(points) < _MIN_FOR_DRAWDOWN:
        return None
    peak = points[0][1]
    worst: Optional[Decimal] = None
    for _, price in points:
        if price > peak:
            peak = price
        if peak > 0:
            drawdown = (price - peak) / peak * Decimal(100)
            if worst is None or drawdown < worst:
                worst = drawdown
    return worst


def analyze(points: List[PricePoint]) -> IndicatorResult:
    """Points en orden ascendente por fecha y sin duplicados."""
    clean = [(p.as_of, p.price) for p in points]
    clean.sort(key=lambda item: item[0])
    values = [price for _, price in clean]
    result = IndicatorResult(
        observations=len(clean),
    )
    if not clean:
        result.missing.append("sin cotizaciones almacenadas de proveedor")
        return result
    result.first_day = clean[0][0]
    result.last_day = clean[-1][0]
    result.last_price = clean[-1][1]

    result.sma_fast = _sma(values, SMA_FAST)
    result.sma_slow = _sma(values, SMA_SLOW)
    result.sma_long = _sma(values, SMA_LONG)
    if result.sma_fast is None:
        result.missing.append(f"media de {SMA_FAST} días: faltan sesiones ({result.observations})")
    if result.sma_slow is None:
        result.missing.append(f"media de {SMA_SLOW} días: faltan sesiones ({result.observations})")
    result.rsi = _rsi(clean, RSI_DAYS)
    if result.rsi is None:
        result.missing.append(f"RSI de {RSI_DAYS} días: faltan observaciones ({result.observations})")

    # Momentum: el cierre más cercano a hace MOMENTUM_DAYS días dentro del set.
    target = clean[-1][0] - timedelta(days=MOMENTUM_DAYS)
    base = None
    for day, price in clean:
        if day >= target:
            base = (day, price)
            break
    if base is None:
        result.missing.append(f"momentum de {MOMENTUM_DAYS} días: historial demasiado corto")
    else:
        if base[1] > 0:
            result.momentum_pct = (clean[-1][1] - base[1]) / base[1] * Decimal(100)
        else:
            result.missing.append("momentum no computable: precio base nulo")

    result.max_drawdown_pct = _max_drawdown_pct(clean)
    if result.max_drawdown_pct is None:
        result.missing.append("retroceso máximo: hace falta más de una fecha")

    if result.sma_fast is not None and result.sma_slow is not None:
        if result.sma_fast > result.sma_slow and (result.sma_long is None or clean[-1][1] > result.sma_long):
            result.trend = "alcista"
        elif result.sma_fast < result.sma_slow and (result.sma_long is None or clean[-1][1] < result.sma_long):
            result.trend = "bajista"
        else:
            result.trend = "lateral"
    return result
