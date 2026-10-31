"""Cartera simulada: reproducción de operaciones, coste medio y rendimiento.

Reglas explícitas:

- Coste medio ponderado. Una compra actualiza cantidad y coste medio; una venta
  reduce cantidad y realiza beneficio/pérdida contra el coste medio vigente.
- El efectivo no puede quedar negativo y no se pueden vender más acciones de las
  que se tienen: el servidor lo valida antes de guardar la operación.
- Nada de esto toca dinero real ni envía órdenes a ningún bróker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from app.models import Trade
from app.services.prices import PriceProvider


@dataclass
class Holding:
    symbol: str
    quantity: float = 0.0
    avg_cost: float = 0.0
    realized: float = 0.0
    thesis: str = ""

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_cost


@dataclass
class ReplayResult:
    cash: float
    holdings: Dict[str, Holding] = field(default_factory=dict)
    realized: float = 0.0
    invested: float = 0.0
    trades: int = 0

    def holding(self, symbol: str) -> Holding:
        key = symbol.upper()
        if key not in self.holdings:
            self.holdings[key] = Holding(symbol=key)
        return self.holdings[key]


class TradeError(ValueError):
    pass


def _sort_key(trade: "Trade") -> tuple:
    moment = trade.executed_at
    if moment is not None and moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment, trade.id or 0)


def replay(starting_cash: float, trades: Sequence[Trade]) -> ReplayResult:
    result = ReplayResult(cash=float(starting_cash))
    for trade in sorted(trades, key=_sort_key):
        symbol = trade.symbol.upper()
        holding = result.holding(symbol)
        gross = trade.quantity * trade.price
        if trade.side == "buy":
            total = gross + trade.fee
            if total > result.cash + 1e-9:
                raise TradeError(
                    f"Efectivo insuficiente para comprar {trade.quantity} {symbol}"
                )
            new_quantity = holding.quantity + trade.quantity
            holding.avg_cost = (
                (holding.quantity * holding.avg_cost + gross + trade.fee) / new_quantity
                if new_quantity
                else 0.0
            )
            holding.quantity = new_quantity
            result.cash -= total
            result.invested += gross
        else:
            if trade.quantity > holding.quantity + 1e-9:
                raise TradeError(
                    f"No puedes vender {trade.quantity} {symbol}: tienes {holding.quantity:.4f}"
                )
            proceeds = gross - trade.fee
            pnl = (trade.price - holding.avg_cost) * trade.quantity - trade.fee
            holding.realized += pnl
            result.realized += pnl
            holding.quantity -= trade.quantity
            if holding.quantity <= 1e-9:
                holding.quantity = 0.0
                holding.avg_cost = 0.0
            result.cash += proceeds
        result.trades += 1
    return result


def summary(
    *,
    name: str,
    starting_cash: float,
    cash: float,
    holdings: Dict[str, Holding],
    realized: float,
    provider: PriceProvider,
    benchmark: str,
    benchmark_start: Optional[date] = None,
) -> Dict[str, Any]:
    positions: List[Dict[str, Any]] = []
    market_value = 0.0
    cost_basis = 0.0
    for holding in holdings.values():
        if holding.quantity <= 0:
            continue
        price = provider.last_price(holding.symbol)
        value = holding.quantity * (price if price is not None else holding.avg_cost)
        market_value += value
        cost_basis += holding.cost_basis
        positions.append(
            {
                "symbol": holding.symbol,
                "quantity": round(holding.quantity, 6),
                "avg_cost": round(holding.avg_cost, 4),
                "price": price,
                "priced": price is not None,
                "market_value": round(value, 2),
                "unrealized": (
                    round(value - holding.cost_basis, 2) if price is not None else None
                ),
                "weight": None,
                "thesis": holding.thesis,
            }
        )
    total = cash + market_value
    equity_return = (total / starting_cash - 1.0) if starting_cash else None
    for position in positions:
        position["weight"] = (
            round(position["market_value"] / total, 6) if total else None
        )
    benchmark_value = None
    if benchmark_start is not None:
        from app.services.prices import benchmark_return

        benchmark_value = benchmark_return(provider, benchmark, benchmark_start)
    return {
        "name": name,
        "starting_cash": round(starting_cash, 2),
        "cash": round(cash, 2),
        "invested_at_cost": round(cost_basis, 2),
        "market_value": round(market_value, 2),
        "total_value": round(total, 2),
        "total_return": round(equity_return, 6) if equity_return is not None else None,
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(market_value - cost_basis, 2),
        "positions": positions,
        "benchmark": {"symbol": benchmark, "return": benchmark_value},
        "prices_source": provider.name,
        "priced_positions": sum(1 for p in positions if p["priced"]),
        "total_positions": len(positions),
        "warning": (
            "Cartera simulada con fines de aprendizaje. No hay dinero real, órdenes ni "
            "conexión con ningún bróker."
        ),
    }


def trade_payload(trade: Trade) -> Dict[str, Any]:
    return {
        "id": trade.id,
        "symbol": trade.symbol,
        "side": trade.side,
        "quantity": trade.quantity,
        "price": trade.price,
        "fee": trade.fee,
        "note": trade.note,
        "executed_at": trade.executed_at.isoformat() if trade.executed_at else None,
    }


def sync_positions(session, portfolio, result: ReplayResult) -> None:  # noqa: ANN001
    """Sincroniza la tabla de posiciones con el resultado reproducido."""
    from sqlalchemy import select

    from app.models import Position

    existing = {
        row.symbol: row
        for row in session.execute(
            select(Position).where(Position.portfolio_id == portfolio.id)
        )
        .scalars()
        .all()
    }
    for symbol, holding in result.holdings.items():
        row = existing.pop(symbol, None)
        if holding.quantity <= 0:
            if row is not None:
                session.delete(row)
            continue
        if row is None:
            row = Position(portfolio_id=portfolio.id, symbol=symbol)
            session.add(row)
        row.quantity = holding.quantity
        row.avg_cost = holding.avg_cost
        if holding.thesis:
            row.thesis = holding.thesis
    for row in existing.values():
        session.delete(row)


def as_datetime(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None
