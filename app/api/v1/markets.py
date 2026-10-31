"""Mercados, instrumentos, cotizaciones y tipos de cambio."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, rate_limit
from app.errors import ApiError
from app.models import FxRate, Instrument, Market, Quote, User, utcnow
from app.schemas import FxRateCreate, InstrumentCreate, MarketOut, QuoteCreate
from app.services.real_movements import instrument_payload

router = APIRouter(tags=["mercados"])


@router.get("/markets", response_model=List[MarketOut], summary="Listar mercados")
def list_markets(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> List[Market]:
    return list(
        db.execute(select(Market).order_by(Market.country_code, Market.code)).scalars().all()
    )


@router.get("/instruments", summary="Buscar instrumentos por símbolo, nombre o ISIN")
def search_instruments(
    q: str = Query(default="", max_length=80),
    market: str = Query(default="", max_length=16),
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    query = select(Instrument, Market).join(Market, Market.id == Instrument.market_id)
    term = q.strip()
    if term:
        pattern = f"%{term}%"
        query = query.where(
            or_(
                Instrument.symbol.ilike(pattern),
                Instrument.name.ilike(pattern),
                Instrument.isin.ilike(pattern),
            )
        )
    if market.strip():
        query = query.where(Market.code == market.strip().upper())
    rows = db.execute(query.order_by(Instrument.symbol).limit(limit)).all()
    return {
        "items": [instrument_payload(db, instrument) for instrument, _ in rows],
        "total": len(rows),
        "query": term,
    }


@router.post("/instruments", status_code=201, summary="Crear un instrumento")
def create_instrument(
    payload: InstrumentCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    market = db.execute(
        select(Market).where(Market.code == payload.market_code)
    ).scalar_one_or_none()
    if market is None:
        raise ApiError(
            404,
            "market_not_found",
            "El mercado no existe. Consulta /markets para ver los códigos admitidos.",
        )
    existing = db.execute(
        select(Instrument).where(
            Instrument.market_id == market.id, Instrument.symbol == payload.symbol
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError(
            409,
            "instrument_exists",
            "Ese símbolo ya existe en el mercado.",
            {"instrument_uid": existing.uid},
        )
    instrument = Instrument(
        uid=str(uuid.uuid4()),
        symbol=payload.symbol,
        name=payload.name.strip(),
        market_id=market.id,
        country_code=payload.country_code or market.country_code,
        currency=payload.currency,
        instrument_type=payload.instrument_type,
        isin=payload.isin,
        cik=payload.cik,
        status="active",
    )
    db.add(instrument)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ApiError(
            409,
            "instrument_conflict",
            "El ISIN o la combinación mercado/símbolo ya están registrados.",
        ) from exc
    return instrument_payload(db, instrument)


@router.get("/instruments/{uid}", summary="Detalle de un instrumento")
def get_instrument(
    uid: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    instrument = db.execute(
        select(Instrument).where(Instrument.uid == uid)
    ).scalar_one_or_none()
    if instrument is None:
        raise ApiError(404, "instrument_not_found", "El instrumento no existe.")
    return instrument_payload(db, instrument)


@router.post(
    "/instruments/{uid}/quotes",
    status_code=201,
    summary="Registrar una cotización con fuente y calidad",
    dependencies=[Depends(rate_limit("quotes", 120))],
)
def create_quote(
    uid: str,
    payload: QuoteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    instrument = db.execute(
        select(Instrument).where(Instrument.uid == uid)
    ).scalar_one_or_none()
    if instrument is None:
        raise ApiError(404, "instrument_not_found", "El instrumento no existe.")
    currency = (payload.currency or instrument.currency).upper()
    if currency != instrument.currency.upper():
        raise ApiError(
            422,
            "currency_mismatch",
            "La cotización debe estar en la moneda del instrumento.",
        )
    existing = db.execute(
        select(Quote).where(
            Quote.user_id == user.id,
            Quote.instrument_id == instrument.id,
            Quote.as_of == payload.as_of,
            Quote.source == payload.source.strip(),
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = Quote(
            user_id=user.id,
            instrument_id=instrument.id,
            price=payload.price,
            currency=currency,
            as_of=payload.as_of,
            source=payload.source.strip(),
            quality=payload.quality,
            retrieved_at=utcnow(),
        )
        db.add(existing)
    else:
        existing.price = payload.price
        existing.quality = payload.quality
        existing.retrieved_at = utcnow()
    db.flush()
    return {
        "instrument_uid": instrument.uid,
        "price": str(existing.price),
        "currency": existing.currency,
        "as_of": existing.as_of.isoformat(),
        "source": existing.source,
        "quality": existing.quality,
        "retrieved_at": existing.retrieved_at.isoformat(),
    }


@router.get("/instruments/{uid}/quotes", summary="Historial de cotizaciones")
def list_quotes(
    uid: str,
    limit: int = Query(default=120, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    instrument = db.execute(
        select(Instrument).where(Instrument.uid == uid)
    ).scalar_one_or_none()
    if instrument is None:
        raise ApiError(404, "instrument_not_found", "El instrumento no existe.")
    rows = (
        db.execute(
            select(Quote)
            .where(
                Quote.instrument_id == instrument.id,
                or_(Quote.user_id.is_(None), Quote.user_id == user.id),
            )
            .order_by(Quote.as_of.desc(), Quote.retrieved_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return {
        "instrument_uid": instrument.uid,
        "items": [
            {
                "price": str(row.price),
                "currency": row.currency,
                "as_of": row.as_of.isoformat(),
                "source": row.source,
                "quality": row.quality,
                "retrieved_at": row.retrieved_at.isoformat(),
            }
            for row in rows
        ],
        "total": len(rows),
    }


@router.post(
    "/fx-rates",
    status_code=201,
    summary="Registrar un tipo de cambio histórico con fuente",
    dependencies=[Depends(rate_limit("fx-rates", 120))],
)
def create_fx_rate(
    payload: FxRateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    if payload.base_currency == payload.quote_currency:
        raise ApiError(422, "invalid_pair", "El par de divisas debe ser distinto.")
    existing = db.execute(
        select(FxRate).where(
            FxRate.user_id == user.id,
            FxRate.base_currency == payload.base_currency,
            FxRate.quote_currency == payload.quote_currency,
            FxRate.as_of == payload.as_of,
            FxRate.source == payload.source.strip(),
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = FxRate(
            user_id=user.id,
            base_currency=payload.base_currency,
            quote_currency=payload.quote_currency,
            rate=payload.rate,
            as_of=payload.as_of,
            source=payload.source.strip(),
            quality=payload.quality,
            retrieved_at=utcnow(),
        )
        db.add(existing)
    else:
        existing.rate = payload.rate
        existing.quality = payload.quality
        existing.retrieved_at = utcnow()
    db.flush()
    return {
        "base_currency": existing.base_currency,
        "quote_currency": existing.quote_currency,
        "rate": str(existing.rate),
        "as_of": existing.as_of.isoformat(),
        "source": existing.source,
        "quality": existing.quality,
        "retrieved_at": existing.retrieved_at.isoformat(),
    }


@router.get("/fx-rates", summary="Consultar tipos de cambio")
def list_fx_rates(
    base: str = Query(min_length=3, max_length=3),
    quote: str = Query(min_length=3, max_length=3),
    as_of: Optional[date] = None,
    limit: int = Query(default=120, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    query = select(FxRate).where(
        FxRate.base_currency == base.upper(),
        FxRate.quote_currency == quote.upper(),
        or_(FxRate.user_id.is_(None), FxRate.user_id == user.id),
    )
    if as_of is not None:
        query = query.where(FxRate.as_of <= as_of)
    rows = (
        db.execute(
            query.order_by(FxRate.as_of.desc(), FxRate.retrieved_at.desc()).limit(limit)
        )
        .scalars()
        .all()
    )
    return {
        "base_currency": base.upper(),
        "quote_currency": quote.upper(),
        "items": [
            {
                "rate": str(row.rate),
                "as_of": row.as_of.isoformat(),
                "source": row.source,
                "quality": row.quality,
                "retrieved_at": row.retrieved_at.isoformat(),
            }
            for row in rows
        ],
        "total": len(rows),
    }
