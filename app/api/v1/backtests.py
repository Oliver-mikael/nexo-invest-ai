"""API de backtests (fase 8): ejecución determinista y consulta aislada por usuario."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.errors import ApiError
from app.models import BacktestRun, Instrument, User
from app.services.backtest import (
    BacktestError,
    STRATEGIES,
    run_backtest,
)

router = APIRouter(prefix="/backtests", tags=["backtests"])


class BacktestRequest(BaseModel):
    instrument_uid: str
    strategy: str = "buy_hold"
    params: Dict[str, Any] = Field(default_factory=dict)
    base_currency: str = Field(default="USD", min_length=3, max_length=3)
    initial_cash: Decimal = Field(default=Decimal("10000"), gt=0)
    commission_bps: Decimal = Field(default=Decimal("5"), ge=0, le=1000)
    slippage_bps: Decimal = Field(default=Decimal("5"), ge=0, le=1000)
    start: Optional[date] = None
    end: Optional[date] = None
    benchmark_uid: Optional[str] = None
    walk_forward: bool = False
    rf_rate: float = Field(default=0.0, ge=0, le=0.5)


def _instrument(session: Session, user: User, uid: str) -> Instrument:
    instrument = session.execute(
        select(Instrument).where(Instrument.uid == uid, Instrument.status == "active")
    ).scalar_one_or_none()
    if instrument is None:
        raise ApiError(404, "instrument_not_found", "Instrumento no encontrado.")
    return instrument


def _symbols(session: Session, runs: List[BacktestRun]) -> Dict[int, Dict[str, str]]:
    """uid y símbolo de los instrumentos referenciados (una sola consulta)."""
    ids = {run.instrument_id for run in runs} | {
        run.benchmark_instrument_id for run in runs if run.benchmark_instrument_id
    }
    if not ids:
        return {}
    instruments = (
        session.execute(select(Instrument).where(Instrument.id.in_(ids))).scalars().all()
    )
    return {row.id: {"uid": row.uid, "symbol": row.symbol} for row in instruments}


def _run_view(
    run: BacktestRun,
    symbols: Dict[int, Dict[str, str]],
    *,
    include_curve: bool = False,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": run.id,
        "instrument": symbols.get(run.instrument_id, {"uid": None, "symbol": None}),
        "benchmark": symbols.get(run.benchmark_instrument_id) if run.benchmark_instrument_id else None,
        "strategy": run.strategy,
        "params": run.params,
        "base_currency": run.base_currency,
        "period_start": run.period_start.isoformat(),
        "period_end": run.period_end.isoformat(),
        "points": run.points,
        "trades": run.trades,
        "metrics": run.metrics,
        "walk_forward": run.walk_forward,
        "warnings": run.warnings,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
    if include_curve:
        payload["curve"] = run.curve
    return payload


@router.post("")
def create_backtest(
    body: BacktestRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Ejecuta y persiste un backtest. Determinista: mismo input, mismos números."""
    instrument = _instrument(session, user, body.instrument_uid)
    benchmark = None
    if body.benchmark_uid:
        benchmark = _instrument(session, user, body.benchmark_uid)
    if body.strategy not in STRATEGIES:
        raise ApiError(400, "invalid_strategy", f"Estrategia no soportada: {body.strategy}.")
    if body.start and body.end and body.start >= body.end:
        raise ApiError(400, "invalid_period", "El inicio debe ser anterior al fin.")
    try:
        result = run_backtest(
            session,
            instrument=instrument,
            strategy=body.strategy,
            params=body.params,
            base_currency=body.base_currency.upper(),
            initial_cash=body.initial_cash,
            commission_bps=body.commission_bps,
            slippage_bps=body.slippage_bps,
            start=body.start,
            end=body.end,
            benchmark=benchmark,
            walk_forward=body.walk_forward,
            rf_rate=body.rf_rate,
        )
    except BacktestError as exc:
        raise ApiError(400, "backtest_error", str(exc)) from exc

    run = BacktestRun(
        user_id=user.id,
        instrument_id=instrument.id,
        benchmark_instrument_id=benchmark.id if benchmark else None,
        strategy=result["strategy"],
        base_currency=result["base_currency"],
        params=result["params"],
        period_start=date.fromisoformat(result["period_start"]),
        period_end=date.fromisoformat(result["period_end"]),
        points=result["points"],
        trades=result["trades"],
        metrics=result["metrics"],
        walk_forward=result["walk_forward"],
        curve=result["curve"],
        warnings=result["warnings"],
    )
    session.add(run)
    session.flush()
    payload = _run_view(run, _symbols(session, [run]), include_curve=True)
    payload["benchmark_result"] = result["benchmark"]
    payload["last_trades"] = result["last_trades"]
    payload["notes"] = result["notes"]
    return payload


@router.get("")
def list_backtests(
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    runs: List[BacktestRun] = (
        session.execute(
            select(BacktestRun)
            .where(BacktestRun.user_id == user.id)
            .order_by(BacktestRun.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    symbols = _symbols(session, runs)
    return {"items": [_run_view(run, symbols) for run in runs]}


@router.get("/{run_id}")
def get_backtest(
    run_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    run = session.execute(
        select(BacktestRun).where(BacktestRun.id == run_id, BacktestRun.user_id == user.id)
    ).scalar_one_or_none()
    if run is None:
        raise ApiError(404, "backtest_not_found", "Backtest no encontrado.")
    return _run_view(run, _symbols(session, [run]), include_curve=True)
