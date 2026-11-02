"""Backtesting determinista sobre datos con procedencia (fase 8).

Reglas que el motor respeta y declara:

- Sin look-ahead: la señal calculada en el cierre del día *t* se ejecuta en el
  cierre del día *t+1* (si existe); sin ese cierre no se opera jamás.
- Costes explícitos: comisión y slippage en puntos básicos por operación,
  aplicados al precio de ejecución.
- Divisas: conversión con las tasas históricas de `fx_rates` (última tasa
  conocida a fecha de operación). Nunca se usa la tasa actual sobre el
  histórico; si falta la pareja se avisa en `warnings`.
- Ajustes: si la fuente suministra cierres ajustados (splits/dividendos) se
  usan esos; si no, se ejecuta con cierres sin ajustar y se advierte.
- Historial: describe lo que habría pasado con esos datos y costes. No es
  garantía de resultados futuros, y la cobertura solo alcanza instrumentos con
  datos presentes (posible sesgo de supervivencia).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FxRate, Instrument, Quote

MONEY = Decimal("0.01")
BPS = Decimal("10000")
MIN_POINTS = 30
MAX_CURVE_POINTS = 400

STRATEGIES = ("buy_hold", "sma_cross")
# Rejilla de walk-forward (entrenamiento): se elige en el bloque de
# entrenamiento y se congela antes de simular la evaluación.
WF_FASTS = (5, 10, 15)
WF_SLOWS = (20, 30, 40)


@dataclass
class CloseSeries:
    dates: List[date]
    closes: List[Decimal]  # en la moneda del instrumento
    currency: str
    adjusted: bool
    warnings: List[str] = field(default_factory=list)


def load_closes(session: Session, instrument: Instrument) -> Optional[CloseSeries]:
    """Cierres del proveedor: ajustados si la fuente los trae, si no sin ajustar."""
    rows = (
        session.execute(
            select(Quote)
            .where(
                Quote.instrument_id == instrument.id,
                Quote.user_id.is_(None),
            )
            .order_by(Quote.as_of.asc())
        )
        .scalars()
        .all()
    )
    adjusted_rows = [row for row in rows if row.adjusted]
    raw_rows = [row for row in rows if not row.adjusted]
    warnings: List[str] = []
    if len(adjusted_rows) >= MIN_POINTS:
        chosen, adjusted = adjusted_rows, True
        warnings.append(
            "Serie ajustada por splits/dividendos según la fuente; los eventos "
            "no ajustados manualmente no se corrigen aquí."
        )
    else:
        chosen, adjusted = raw_rows, False
        if len(chosen) >= MIN_POINTS:
            warnings.append(
                "Sin cierres ajustados de la fuente: los efectos de splits y "
                "dividendos NO están reflejados en la rentabilidad simulada."
            )
    if len(chosen) < MIN_POINTS:
        return None
    return CloseSeries(
        dates=[row.as_of for row in chosen],
        closes=[Decimal(row.price) for row in chosen],
        currency=chosen[0].currency,
        adjusted=adjusted,
        warnings=warnings,
    )


class FxConverter:
    """Conversión histórica: última tasa conocida ≤ fecha (nunca la tasa actual).

    Acepta la pareja en cualquiera de las dos orientaciones almacenadas en
    `fx_rates`: si solo existe la inversa, se aplica el recíproco. El factor
    devuelto siempre convierte de `from_currency` a `to_currency`.
    """

    def __init__(self, rates: Sequence[Tuple[date, Decimal]], warnings: List[str]):
        self._rates = rates
        self._warnings = warnings
        self._warned_missing = False

    @classmethod
    def build(
        cls, session: Session, from_currency: str, to_currency: str
    ) -> "FxConverter":
        if from_currency == to_currency:
            return cls([], [])

        def _rows(base: str, quote: str) -> List[Tuple[date, Decimal]]:
            found = (
                session.execute(
                    select(FxRate)
                    .where(
                        FxRate.base_currency == base,
                        FxRate.quote_currency == quote,
                        FxRate.user_id.is_(None),
                    )
                    .order_by(FxRate.as_of.asc())
                )
                .scalars()
                .all()
            )
            return [(row.as_of, Decimal(row.rate)) for row in found]

        direct = _rows(from_currency, to_currency)
        if direct:
            return cls(direct, [])
        inverse = _rows(to_currency, from_currency)
        if inverse:
            # rate está en la orientación opuesta: se usa el recíproco.
            return cls(
                [(day, Decimal("1") / rate) for day, rate in inverse if rate > 0], []
            )
        return cls([], [])

    @property
    def empty(self) -> bool:
        return not self._rates

    def rate_for(self, day: date) -> Optional[Decimal]:
        if not self._rates:
            if not self._warned_missing:
                self._warnings.append(
                    "Sin tasas históricas para la pareja de divisas solicitada: "
                    "las operaciones en moneda ajena no se convierten."
                )
                self._warned_missing = True
            return None
        chosen = self._rates[0][1]
        for rate_day, rate in self._rates:
            if rate_day <= day:
                chosen = rate
            else:
                break
        return chosen


@dataclass
class SimResult:
    dates: List[date]
    equity: List[Decimal]
    trades: List[Dict[str, Any]]
    warnings: List[str] = field(default_factory=list)


def sma(values: Sequence[Decimal], window: int, index: int) -> Optional[Decimal]:
    if index + 1 < window:
        return None
    chunk = values[index + 1 - window : index + 1]
    return sum(chunk) / Decimal(window)


def build_signals(
    strategy: str, dates: Sequence[date], closes: Sequence[Decimal], params: Dict[str, Any]
) -> List[int]:
    """Posición objetivo al cierre de cada día (1 = invertido, 0 = efectivo)."""
    n = len(closes)
    if strategy == "buy_hold":
        return [1] * n
    fast = int(params.get("fast", 10))
    slow = int(params.get("slow", 50))
    signals: List[int] = []
    for index in range(n):
        fast_ma = sma(closes, fast, index)
        slow_ma = sma(closes, slow, index)
        if fast_ma is None or slow_ma is None:
            signals.append(0)
        else:
            signals.append(1 if fast_ma > slow_ma else 0)
    return signals


def simulate(
    dates: Sequence[date],
    base_closes: Sequence[Decimal],
    signals: Sequence[int],
    *,
    initial_cash: Decimal,
    commission_bps: Decimal,
    slippage_bps: Decimal,
) -> SimResult:
    """Simula all-in/out con ejecución al cierre del día siguiente a la señal."""
    n = len(base_closes)
    commission = commission_bps / BPS
    slippage = slippage_bps / BPS
    cash = initial_cash
    qty = Decimal("0")
    position = 0
    trades: List[Dict[str, Any]] = []
    equity: List[Decimal] = []
    for index in range(n):
        target = signals[index]
        if target != position and index + 1 < n:
            exec_day = dates[index + 1]
            raw_price = base_closes[index + 1]
            if target == 1:
                price = (raw_price * (Decimal("1") + slippage)).quantize(MONEY, ROUND_HALF_UP)
                affordable = cash / (price * (Decimal("1") + commission))
                bought = (affordable).quantize(Decimal("0.00000001"), ROUND_HALF_UP)
                if bought > 0:
                    spent = (bought * price).quantize(MONEY, ROUND_HALF_UP)
                    fee = (spent * commission).quantize(MONEY, ROUND_HALF_UP)
                    cash -= spent + fee
                    qty = bought
                    position = 1
                    trades.append(
                        {"day": exec_day.isoformat(), "side": "buy",
                         "price": str(price), "qty": str(bought), "fee": str(fee)}
                    )
            else:
                price = (raw_price * (Decimal("1") - slippage)).quantize(MONEY, ROUND_HALF_UP)
                sold = qty
                gross = (sold * price).quantize(MONEY, ROUND_HALF_UP)
                fee = (gross * commission).quantize(MONEY, ROUND_HALF_UP)
                cash += gross - fee
                qty = Decimal("0")
                position = 0
                trades.append(
                    {"day": exec_day.isoformat(), "side": "sell",
                     "price": str(price), "qty": str(sold), "fee": str(fee)}
                )
        equity.append((cash + qty * base_closes[index]).quantize(MONEY, ROUND_HALF_UP))
    return SimResult(dates=list(dates), equity=equity, trades=trades)


class BacktestError(ValueError):
    """Solicitud de backtest inválida o con datos insuficientes (HTTP 400)."""


def max_drawdown(equity: Sequence[Decimal]) -> float:
    peak = float(equity[0])
    worst = 0.0
    for value in equity:
        current = float(value)
        peak = max(peak, current)
        if peak > 0:
            worst = min(worst, current / peak - 1.0)
    return round(worst, 6)


def metrics_from_curve(
    dates: Sequence[date], equity: Sequence[Decimal], *, rf_rate: float = 0.0
) -> Dict[str, Any]:
    """CAGR, volatilidad, Sharpe, Sortino y drawdown sobre la curva de equity."""
    if len(equity) < 2:
        raise BacktestError("Serie demasiado corta para calcular métricas.")
    eq = [float(value) for value in equity]
    total_return = eq[-1] / eq[0] - 1.0 if eq[0] else 0.0
    days = max((dates[-1] - dates[0]).days, 1)
    years = days / 365.25
    cagr = None
    if years >= 1.0 and eq[-1] > 0 and eq[0] > 0:
        cagr = (eq[-1] / eq[0]) ** (1.0 / years) - 1.0
    returns = [
        eq[index] / eq[index - 1] - 1.0
        for index in range(1, len(eq))
        if eq[index - 1] > 0
    ]
    ann_vol = None
    sharpe = None
    sortino = None
    if len(returns) >= 3:
        mean_daily = statistics.fmean(returns)
        stdev = statistics.stdev(returns)
        ann_vol = stdev * math.sqrt(252)
        if ann_vol > 0:
            sharpe = (mean_daily * 252 - rf_rate) / ann_vol
        downside = [min(value, 0.0) ** 2 for value in returns]
        downside_dev = math.sqrt(statistics.fmean(downside)) * math.sqrt(252)
        if downside_dev > 0:
            sortino = (mean_daily * 252 - rf_rate) / downside_dev

    def _rounded(value: Optional[float]) -> Optional[float]:
        return None if value is None else round(value, 6)

    return {
        "total_return": round(total_return, 6),
        "cagr": _rounded(cagr),
        "ann_volatility": _rounded(ann_vol),
        "sharpe": _rounded(sharpe),
        "sortino": _rounded(sortino),
        "max_drawdown": max_drawdown(equity),
        "final_equity": str(equity[-1]),
        "initial_equity": str(equity[0]),
        "trading_days": len(eq),
    }


def downsample_curve(
    dates: Sequence[date], equity: Sequence[Decimal], limit: int = MAX_CURVE_POINTS
) -> List[Dict[str, str]]:
    count = len(equity)
    if count <= limit:
        indices = range(count)
    else:
        step = math.ceil(count / limit)
        indices = list(range(0, count, step))
        if indices[-1] != count - 1:
            indices.append(count - 1)
    return [
        {"date": dates[index].isoformat(), "equity": str(equity[index])}
        for index in indices
    ]


def _to_base_prices(
    series: CloseSeries,
    base_currency: str,
    converter: FxConverter,
    warnings: List[str],
) -> List[Decimal]:
    if series.currency == base_currency:
        return list(series.closes)
    converted: List[Decimal] = []
    for day, price in zip(series.dates, series.closes):
        rate = converter.rate_for(day)
        if rate is None:
            # Sin tasa no se inventa conversión: se repite el último valor
            # conocido y se avisa; si nunca hubo tasa, se detiene.
            if not converted:
                raise BacktestError(
                    f"Sin tasas históricas {base_currency}/{series.currency} para "
                    "convertir la serie a la moneda base."
                )
            rate = Decimal("1")
        converted.append((price * rate).quantize(MONEY, ROUND_HALF_UP))
    if converter.empty:
        warnings.append(
            f"Sin tasas para {base_currency}/{series.currency}: conversión "
            "incompleta, revisar antes de usar las métricas."
        )
    return converted


def _validate_strategy(strategy: str, params: Dict[str, Any], points: int) -> None:
    if strategy not in STRATEGIES:
        raise BacktestError(f"Estrategia no soportada: {strategy}.")
    if strategy == "sma_cross":
        fast = int(params.get("fast", 10))
        slow = int(params.get("slow", 50))
        if fast < 2 or slow <= fast:
            raise BacktestError("Parámetros SMA inválidos: fast >= 2 y slow > fast.")
        if points <= slow + 5:
            raise BacktestError(
                f"Datos insuficientes: se necesitan más de {slow + 5} cierres "
                "para la ventana lenta."
            )
    elif points < MIN_POINTS:
        raise BacktestError(f"Datos insuficientes: mínimo {MIN_POINTS} cierres.")


def _walk_forward(
    dates: Sequence[date],
    raw_closes: Sequence[Decimal],
    base_closes: Sequence[Decimal],
    *,
    initial_cash: Decimal,
    commission_bps: Decimal,
    slippage_bps: Decimal,
) -> Tuple[Dict[str, Any], List[int], List[date], List[Decimal]]:
    """Elige (fast, slow) en el bloque de entrenamiento y lo congela.

    La evaluación se simula con los parámetros ya elegidos: los datos de
    evaluación nunca entran en la selección (sin look-ahead).
    """
    split_index = int(len(dates) * 0.6)
    train_dates, eval_dates = dates[:split_index], dates[split_index:]
    # Las señales se calculan con la serie en moneda del instrumento; la
    # simulación usa los valores convertidos a la moneda base.
    train_raw, eval_raw = raw_closes[:split_index], raw_closes[split_index:]
    train_base, eval_base = base_closes[:split_index], base_closes[split_index:]
    candidates = [
        (fast, slow)
        for fast in WF_FASTS
        for slow in WF_SLOWS
        if fast < slow and split_index > slow + 5
    ]
    if not candidates:
        return (
            {"applied": False, "reason": "Bloque de entrenamiento demasiado corto para la rejilla."},
            build_signals("buy_hold", eval_dates, eval_raw, {}),
            list(eval_dates),
            list(eval_base),
        )
    best: Optional[Tuple[Decimal, int, int]] = None
    for fast, slow in candidates:
        signals = build_signals("sma_cross", train_dates, train_raw, {"fast": fast, "slow": slow})
        result = simulate(
            train_dates, train_base, signals,
            initial_cash=initial_cash,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
        )
        # Empate determinista: más rápido (menos costes) y luego ventana corta.
        key = (result.equity[-1], -fast, -slow)
        if best is None or key > (best[0], -best[1], -best[2]):
            best = (result.equity[-1], fast, slow)
    assert best is not None
    _, chosen_fast, chosen_slow = best
    eval_signals = build_signals(
        "sma_cross", eval_dates, eval_raw, {"fast": chosen_fast, "slow": chosen_slow}
    )
    info = {
        "applied": True,
        "split_date": train_dates[-1].isoformat(),
        "train_points": len(train_dates),
        "eval_points": len(eval_dates),
        "chosen": {"fast": chosen_fast, "slow": chosen_slow},
        "grid": [{"fast": fast, "slow": slow} for fast, slow in candidates],
        "note": (
            "Parámetros elegidos solo con el bloque de entrenamiento; la "
            "evaluación usa datos que no participaron en la selección."
        ),
    }
    return info, eval_signals, list(eval_dates), list(eval_base)


def run_backtest(
    session: Session,
    *,
    instrument: Instrument,
    strategy: str,
    params: Dict[str, Any],
    base_currency: str,
    initial_cash: Decimal,
    commission_bps: Decimal,
    slippage_bps: Decimal,
    start: Optional[date] = None,
    end: Optional[date] = None,
    benchmark: Optional[Instrument] = None,
    walk_forward: bool = False,
    rf_rate: float = 0.0,
) -> Dict[str, Any]:
    """Ejecuta el backtest y devuelve el resultado serializable (sin persistir)."""
    series = load_closes(session, instrument)
    if series is None:
        raise BacktestError(
            f"Sin datos suficientes para {instrument.symbol}: se requieren "
            f"al menos {MIN_POINTS} cierres del proveedor."
        )
    mask = [
        (start is None or day >= start) and (end is None or day <= end)
        for day in series.dates
    ]
    dates = [day for day, keep in zip(series.dates, mask) if keep]
    closes = [price for price, keep in zip(series.closes, mask) if keep]
    if len(dates) < MIN_POINTS:
        raise BacktestError(
            f"Solo {len(dates)} cierres en el periodo solicitado (mínimo {MIN_POINTS})."
        )
    _validate_strategy(strategy, params, len(dates))

    warnings: List[str] = list(series.warnings)
    # Pareja invertida: la tasa se busca como "unidades de base por una unidad
    # de la moneda del instrumento", para que price * rate quede en la base.
    converter = FxConverter.build(session, series.currency, base_currency)
    base_closes = _to_base_prices(series.__class__(dates, closes, series.currency, series.adjusted),
                                  base_currency, converter, warnings)

    walk_info: Dict[str, Any] = {"applied": False}
    if walk_forward and strategy == "sma_cross":
        walk_info, signals, run_dates, run_closes = _walk_forward(
            dates, closes, base_closes,
            initial_cash=initial_cash,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
        )
    else:
        if walk_forward:
            walk_info = {
                "applied": False,
                "reason": "Walk-forward solo aplica a estrategias paramétricas (sma_cross).",
            }
        signals = build_signals(strategy, dates, closes, params)
        run_dates, run_closes = list(dates), base_closes

    result = simulate(
        run_dates, run_closes, signals,
        initial_cash=initial_cash,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
    )
    metrics = metrics_from_curve(result.dates, result.equity, rf_rate=rf_rate)

    benchmark_block: Dict[str, Any] = {"available": False}
    if benchmark is not None:
        bench_series = load_closes(session, benchmark)
        if bench_series is None:
            warnings.append(
                f"Benchmark {benchmark.symbol} sin datos suficientes: se omite."
            )
        else:
            # El benchmark se corta al mismo periodo calendario.
            bmask = [
                (start is None or day >= start) and (end is None or day <= end)
                for day in bench_series.dates
            ]
            b_dates = [day for day, keep in zip(bench_series.dates, bmask) if keep]
            b_closes_src = [price for price, keep in zip(bench_series.closes, bmask) if keep]
            if len(b_dates) >= MIN_POINTS:
                b_warn: List[str] = []
                b_converter = FxConverter.build(session, bench_series.currency, base_currency)
                b_closes = _to_base_prices(
                    bench_series.__class__(b_dates, b_closes_src, bench_series.currency, bench_series.adjusted),
                    base_currency, b_converter, b_warn,
                )
                warnings.extend(b_warn)
                bench_equity = [
                    (initial_cash * price / b_closes[0]).quantize(MONEY, ROUND_HALF_UP)
                    for price in b_closes
                ]
                benchmark_block = {
                    "available": True,
                    "symbol": benchmark.symbol,
                    "metrics": metrics_from_curve(b_dates, bench_equity, rf_rate=rf_rate),
                }
            else:
                warnings.append(
                    f"Benchmark {benchmark.symbol} sin datos en el periodo: se omite."
                )

    notes = [
        "Backtest sobre histórico con datos de la plataforma: no garantiza "
        "resultados futuros.",
        "Cobertura limitada a instrumentos con datos presentes (posible sesgo "
        "de supervivencia).",
    ]
    return {
        "strategy": strategy,
        "params": dict(params),
        "base_currency": base_currency,
        "period_start": result.dates[0].isoformat(),
        "period_end": result.dates[-1].isoformat(),
        # Cierres observados en el periodo completo (la curva puede cubrir solo
        # el bloque de evaluación en walk-forward; metrics.trading_days lo dice).
        "points": len(dates),
        "trades": len(result.trades),
        "metrics": metrics,
        "walk_forward": walk_info,
        "benchmark": benchmark_block,
        "curve": downsample_curve(result.dates, result.equity),
        "last_trades": result.trades[-10:],
        "warnings": warnings,
        "notes": notes,
    }


