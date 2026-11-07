"""Cartera simulada: creación, operaciones ficticias y rendimiento."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, rate_limit
from app.errors import ApiError
from app.models import AuditEvent, Portfolio, Trade, User, utcnow
from app.schemas import PortfolioCreate, TradeCreate
from app.services.portfolio import TradeError, replay, summary, sync_positions, trade_payload

router = APIRouter(prefix="/portfolios", tags=["cartera simulada"])


def _portfolio_or_404(db: Session, user: User, portfolio_id: int) -> Portfolio:
    portfolio = db.execute(
        select(Portfolio).where(
            Portfolio.id == portfolio_id, Portfolio.user_id == user.id
        )
    ).scalar_one_or_none()
    if portfolio is None:
        raise ApiError(404, "not_found", "La cartera no existe.")
    return portfolio


def _summary_for(db: Session, portfolio: Portfolio, request: Request) -> Dict[str, Any]:
    trades: List[Trade] = list(
        db.execute(
            select(Trade)
            .where(Trade.portfolio_id == portfolio.id)
            .order_by(Trade.executed_at, Trade.id)
        )
        .scalars()
        .all()
    )
    result = replay(portfolio.starting_cash, trades)
    provider = request.app.state.prices
    return summary(
        name=portfolio.name,
        starting_cash=portfolio.starting_cash,
        cash=result.cash,
        holdings=result.holdings,
        realized=result.realized,
        provider=provider,
        benchmark=portfolio.benchmark,
    )


@router.post("", status_code=201, summary="Crear cartera simulada")
def create_portfolio(
    payload: PortfolioCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    portfolio = Portfolio(
        user_id=user.id,
        name=payload.name.strip() or "Cartera",
        currency=payload.currency.upper(),
        starting_cash=payload.starting_cash,
        cash=payload.starting_cash,
        benchmark=payload.benchmark.upper(),
    )
    db.add(portfolio)
    db.flush()
    db.add(
        AuditEvent(
            user_id=user.id,
            action="portfolio.created",
            subject=str(portfolio.id),
            meta={"starting_cash": payload.starting_cash},
        )
    )
    return {
        "id": portfolio.id,
        "name": portfolio.name,
        "currency": portfolio.currency,
        "starting_cash": portfolio.starting_cash,
        "cash": portfolio.cash,
        "benchmark": portfolio.benchmark,
    }


@router.get("", summary="Listar carteras")
def list_portfolios(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    rows = (
        db.execute(
            select(Portfolio)
            .where(Portfolio.user_id == user.id)
            .order_by(Portfolio.created_at)
        )
        .scalars()
        .all()
    )
    items = []
    for portfolio in rows:
        data = _summary_for(db, portfolio, request)
        items.append(
            {
                "id": portfolio.id,
                "name": portfolio.name,
                "currency": portfolio.currency,
                "total_value": data["total_value"],
                "total_return": data["total_return"],
                "positions": len(data["positions"]),
            }
        )
    return {"items": items, "total": len(items)}


@router.get("/{portfolio_id}", summary="Detalle y rendimiento de la cartera")
def get_portfolio(
    portfolio_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    portfolio = _portfolio_or_404(db, user, portfolio_id)
    data = _summary_for(db, portfolio, request)
    data.update({"id": portfolio.id, "currency": portfolio.currency})
    return data


@router.post(
    "/{portfolio_id}/trades",
    status_code=201,
    summary="Registrar compra o venta ficticia",
    dependencies=[Depends(rate_limit("portfolio-trade", 60))],
)
def create_trade(
    portfolio_id: int,
    payload: TradeCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    portfolio = _portfolio_or_404(db, user, portfolio_id)
    trades: List[Trade] = list(
        db.execute(select(Trade).where(Trade.portfolio_id == portfolio.id))
        .scalars()
        .all()
    )
    candidate = Trade(
        portfolio_id=portfolio.id,
        symbol=payload.symbol,
        side=payload.side,
        quantity=payload.quantity,
        price=payload.price,
        fee=payload.fee,
        note=payload.note,
        executed_at=utcnow(),
    )
    try:
        result = replay(portfolio.starting_cash, trades + [candidate])
    except TradeError as exc:
        raise ApiError(422, "invalid_trade", str(exc)) from exc
    db.add(candidate)
    db.flush()
    portfolio.cash = result.cash
    if payload.thesis:
        holding = result.holdings.get(payload.symbol)
        if holding is not None:
            holding.thesis = payload.thesis[:4000]
    sync_positions(db, portfolio, result)
    db.add(
        AuditEvent(
            user_id=user.id,
            action="portfolio.trade",
            subject=f"{portfolio.id}:{payload.symbol}",
            meta={
                "side": payload.side,
                "quantity": payload.quantity,
                "price": payload.price,
            },
        )
    )
    return {
        "trade": trade_payload(candidate),
        "portfolio": {
            "id": portfolio.id,
            "cash": round(portfolio.cash, 2),
        },
    }


@router.get("/{portfolio_id}/trades", summary="Historial de operaciones ficticias")
def list_trades(
    portfolio_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    portfolio = _portfolio_or_404(db, user, portfolio_id)
    rows = (
        db.execute(
            select(Trade)
            .where(Trade.portfolio_id == portfolio.id)
            .order_by(Trade.executed_at.desc(), Trade.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return {"items": [trade_payload(row) for row in rows], "total": len(rows)}


@router.delete("/{portfolio_id}", summary="Eliminar una cartera simulada")
def delete_portfolio(
    portfolio_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    portfolio = _portfolio_or_404(db, user, portfolio_id)
    db.delete(portfolio)
    return {"ok": True, "deleted": portfolio_id}
