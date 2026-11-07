"""API de datos de mercado: estado, sincronización y consulta (Fase 5).

Endpoints protegidos por sesión. Las sincronizaciones se encolan en segundo
plan por defecto (`background: true`) para no bloquear la API; con
`background: false` se ejecutan de forma síncrona, útil para pruebas manuales.

Ningún endpoint expone claves de proveedor: los adaptadores no las necesitan
por defecto, y si algún día las hay viven solo en el proceso del servidor.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, rate_limit
from app.errors import ApiError
from app.models import FundamentalFact, FxRate, Instrument, ProviderRun, User
from app.schemas import (
    AutoSyncToggle,
    DataSyncFundamentalsRequest,
    DataSyncFxRequest,
    DataSyncPricesRequest,
)
from app.services.data.base import DataError
from app.services.data.status import data_status, latest_runs, run_payload
from app.services.data.sync import DataSyncService

router = APIRouter(prefix="/data", tags=["datos de mercado"])


def _service(request: Request) -> DataSyncService:
    return request.app.state.data


def _runner(request: Request) -> Any:
    return request.app.state.data_jobs


def _run_or_404(db: Session, run_id: int) -> ProviderRun:
    row = db.execute(select(ProviderRun).where(ProviderRun.id == run_id)).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "La ejecución no existe.")
    return row


# -- estado -------------------------------------------------------------------


@router.get("/status", summary="Estado de proveedores, ejecuciones y frescura")
def status(
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    settings = request.app.state.settings
    return data_status(db, settings)


@router.get("/providers", summary="Catálogo de proveedores y sus límites")
def providers(
    request: Request,
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from app.services.data.status import provider_catalog

    return {"items": provider_catalog(request.app.state.settings)}


@router.get("/runs", summary="Últimas ejecuciones de recopilación")
def runs(
    db: Session = Depends(get_db),
    limit: int = Query(default=15, ge=1, le=50),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    items = latest_runs(db, limit)
    return {"items": items, "total": len(items)}


@router.get("/runs/{run_id}", summary="Detalle de una ejecución")
def run_detail(
    run_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return run_payload(_run_or_404(db, run_id))


@router.get("/fx-rates", summary="Tipos de cambio globales y propios")
def fx_rates(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    base: Optional[str] = Query(default=None, min_length=3, max_length=3),
    quote: Optional[str] = Query(default=None, min_length=3, max_length=3),
    limit: int = Query(default=100, ge=1, le=500),
) -> Dict[str, Any]:
    query = select(FxRate).where(
        (FxRate.user_id.is_(None)) | (FxRate.user_id == user.id)
    )
    if base:
        query = query.where(FxRate.base_currency == base.upper())
    if quote:
        query = query.where(FxRate.quote_currency == quote.upper())
    rows = (
        db.execute(query.order_by(FxRate.as_of.desc(), FxRate.retrieved_at.desc()).limit(limit))
        .scalars().all()
    )
    items = [
        {
            "base_currency": row.base_currency,
            "quote_currency": row.quote_currency,
            "rate": str(row.rate),
            "as_of": row.as_of.isoformat(),
            "retrieved_at": row.retrieved_at.isoformat() if row.retrieved_at else None,
            "source": row.source,
            "quality": row.quality,
            "kind": row.kind,
            "private": row.user_id is not None,
        }
        for row in rows
    ]
    return {"items": items, "total": len(items)}


# -- sincronización -----------------------------------------------------------


@router.post(
    "/sync/fx",
    status_code=202,
    summary="Sincronizar tipos de cambio (segundo plan por defecto)",
    dependencies=[Depends(rate_limit("data_sync_fx", 30))],
)
def sync_fx(
    payload: DataSyncFxRequest,
    request: Request,
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    settings = request.app.state.settings
    provider = settings.fx_provider
    if payload.providers:
        provider = settings.fx_provider  # rangos con proveedor concreto: solo el primario
    body: Dict[str, Any] = {
        "type": "fx",
        "provider": provider,
        "base": payload.base,
        "quotes": payload.quotes,
        "start": payload.start.isoformat() if payload.start else None,
        "end": payload.end.isoformat() if payload.end else None,
        "providers": payload.providers,
        "force": payload.force,
    }
    if payload.background:
        run_id = _runner(request).enqueue(body)
        return {"run_id": run_id, "status": "queued", "background": True}
    try:
        result = _service(request).sync_fx(
            payload.base,
            payload.quotes,
            start=payload.start,
            end=payload.end,
            providers=payload.providers,
            provider_name=provider,
            force=payload.force,
        )
    except DataError as exc:
        raise ApiError(400, "data_error", str(exc)) from exc
    result["background"] = False
    return result


@router.post(
    "/sync/prices",
    status_code=202,
    summary="Sincronizar precios históricos de un instrumento",
    dependencies=[Depends(rate_limit("data_sync_prices", 60))],
)
def sync_prices(
    payload: DataSyncPricesRequest,
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    instrument = db.execute(
        select(Instrument).where(Instrument.uid == payload.instrument_uid)
    ).scalar_one_or_none()
    if instrument is None:
        raise ApiError(404, "not_found", "El instrumento no existe.")
    settings = request.app.state.settings
    body: Dict[str, Any] = {
        "type": "prices",
        "provider": settings.prices_provider,
        "instrument_uid": payload.instrument_uid,
        "start": payload.start.isoformat() if payload.start else None,
        "end": payload.end.isoformat() if payload.end else None,
        "force": payload.force,
    }
    if payload.background:
        run_id = _runner(request).enqueue(body)
        return {"run_id": run_id, "status": "queued", "background": True}
    try:
        result = _service(request).sync_prices(
            payload.instrument_uid,
            start=payload.start,
            end=payload.end,
            force=payload.force,
        )
    except DataError as exc:
        raise ApiError(400, "data_error", str(exc)) from exc
    result["background"] = False
    return result


@router.post(
    "/sync/fundamentals",
    status_code=202,
    summary="Sincronizar fundamentales (emisores con CIK)",
    dependencies=[Depends(rate_limit("data_sync_fundamentals", 30))],
)
def sync_fundamentals(
    payload: DataSyncFundamentalsRequest,
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    instrument = db.execute(
        select(Instrument).where(Instrument.uid == payload.instrument_uid)
    ).scalar_one_or_none()
    if instrument is None:
        raise ApiError(404, "not_found", "El instrumento no existe.")
    body: Dict[str, Any] = {
        "type": "fundamentals",
        "provider": "sec",
        "instrument_uid": payload.instrument_uid,
        "force": payload.force,
    }
    if payload.background:
        run_id = _runner(request).enqueue(body)
        return {"run_id": run_id, "status": "queued", "background": True}
    try:
        result = _service(request).sync_fundamentals(
            payload.instrument_uid, force=payload.force
        )
    except DataError as exc:
        raise ApiError(400, "data_error", str(exc)) from exc
    result["background"] = False
    return result


@router.post(
    "/instruments/{instrument_uid}/auto-sync",
    summary="Activar o desactivar la actualización automática de un instrumento",
)
def toggle_auto_sync(
    instrument_uid: str,
    payload: AutoSyncToggle,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    instrument = db.execute(
        select(Instrument).where(Instrument.uid == instrument_uid)
    ).scalar_one_or_none()
    if instrument is None:
        raise ApiError(404, "not_found", "El instrumento no existe.")
    instrument.auto_sync_prices = payload.enabled
    db.flush()
    db.commit()
    return {
        "instrument_uid": instrument.uid,
        "auto_sync": instrument.auto_sync_prices,
        "note": "Preferencia global del instrumento de referencia (los datos de "
                "proveedor son globales).",
    }


# -- consulta -----------------------------------------------------------------


@router.get("/fundamentals/{instrument_uid}", summary="Fundamentales guardados")
def fundamentals(
    instrument_uid: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    period: Optional[str] = Query(default=None, pattern="^(annual|quarter)$"),
) -> Dict[str, Any]:
    instrument = db.execute(
        select(Instrument).where(Instrument.uid == instrument_uid)
    ).scalar_one_or_none()
    if instrument is None:
        raise ApiError(404, "not_found", "El instrumento no existe.")
    query = select(FundamentalFact).where(FundamentalFact.instrument_id == instrument.id)
    if period:
        query = query.where(FundamentalFact.period_type == period)
    rows = (
        db.execute(query.order_by(FundamentalFact.fiscal_end.desc()).limit(24))
        .scalars().all()
    )
    items = [
        {
            "period_type": row.period_type,
            "fiscal_start": row.fiscal_start.isoformat() if row.fiscal_start else None,
            "fiscal_end": row.fiscal_end.isoformat(),
            "reported_at": row.reported_at.isoformat() if row.reported_at else None,
            "currency": row.currency,
            "revenue": str(row.revenue) if row.revenue is not None else None,
            "net_income": str(row.net_income) if row.net_income is not None else None,
            "eps_diluted": str(row.eps_diluted) if row.eps_diluted is not None else None,
            "shares_outstanding": (
                str(row.shares_outstanding) if row.shares_outstanding is not None else None
            ),
            "total_debt": str(row.total_debt) if row.total_debt is not None else None,
            "cash": str(row.cash) if row.cash is not None else None,
            "source": row.source,
            "quality": row.quality,
            "retrieved_at": row.retrieved_at.isoformat() if row.retrieved_at else None,
        }
        for row in rows
    ]
    return {
        "instrument_uid": instrument_uid,
        "items": items,
        "total": len(items),
        "note": "Solo magnitudes publicadas por el emisor. EBITDA y flujo de caja "
                "libre no se muestran: la fuente no los publica como concepto.",
    }


@router.get("/news", summary="Noticias y eventos corporativos")
def news(_: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Sin proveedor configurado: se informa, no se inventa contenido."""
    return {
        "items": [],
        "available": False,
        "reason": "No hay proveedor de noticias con licencia clara configurado en "
                  "esta versión. No se muestran titulares inventados ni copiados.",
    }
