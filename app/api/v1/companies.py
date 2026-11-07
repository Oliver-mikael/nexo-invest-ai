"""Explorador de empresas, análisis, valoración e informe del motor."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, rate_limit
from app.errors import ApiError
from app.models import AuditEvent, Company, CompanySnapshot, Report, User, utcnow
from app.schemas import CompanyOut, CompanySearchResponse, ValuationRequest
from app.services.engine import EngineService, EngineUnavailable, InvalidAssumption

router = APIRouter(prefix="/companies", tags=["empresas"])


def engine_of(request: Request) -> EngineService:
    return request.app.state.engine


def _persist_company(db: Session, ticker: str, payload: Dict[str, Any]) -> Company:
    identity = payload["identity"]
    company = db.execute(
        select(Company).where(Company.ticker == ticker.upper())
    ).scalar_one_or_none()
    if company is None:
        company = Company(ticker=ticker.upper())
        db.add(company)
    company.cik = identity.get("cik")
    company.name = identity.get("name") or company.name
    company.currency = identity.get("currency") or company.currency
    company.fiscal_year_end = str(identity.get("fiscal_close_month") or "")
    company.updated_at = utcnow()
    db.flush()
    return company


def _store_snapshot(db: Session, company: Company, payload: Dict[str, Any]) -> None:
    db.add(
        CompanySnapshot(
            company_id=company.id,
            payload={k: v for k, v in payload.items() if k != "ledger"},
            source_url=payload["provenance"].get("source_url") or "",
            content_sha256=payload["provenance"].get("content_sha256") or "",
            data_quality=payload["provenance"].get("quality_label") or "",
        )
    )


@router.get("", response_model=CompanySearchResponse, summary="Buscar empresas")
def search_companies(
    q: str = Query(default="", max_length=80),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> CompanySearchResponse:
    query = q.strip()
    statement = select(Company)
    if query:
        pattern = f"%{query}%"
        statement = statement.where(
            or_(
                Company.ticker.ilike(pattern),
                Company.name.ilike(pattern),
                Company.sector.ilike(pattern),
                Company.industry.ilike(pattern),
            )
        )
    total = db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
    rows = (
        db.execute(statement.order_by(Company.ticker).limit(limit)).scalars().all()
    )
    return CompanySearchResponse(
        items=[CompanyOut.model_validate(row) for row in rows],
        total=int(total),
        query=query,
    )


@router.get("/{ticker}", response_model=CompanyOut, summary="Ficha de la empresa")
def get_company(
    ticker: str,
    request: Request,
    refresh: bool = False,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> CompanyOut:
    ticker = ticker.upper()
    company = db.execute(select(Company).where(Company.ticker == ticker)).scalar_one_or_none()
    if company is not None and not refresh:
        return CompanyOut.model_validate(company)
    engine: EngineService = request.app.state.engine
    try:
        payload = engine.payload(ticker, refresh=refresh)
    except EngineUnavailable as exc:
        raise ApiError(503, "engine_unavailable", str(exc)) from exc
    company = _persist_company(db, ticker, payload)
    if refresh:
        _store_snapshot(db, company, payload)
    return CompanyOut.model_validate(company)


@router.post(
    "/{ticker}/refresh",
    summary="Volver a descargar y recalcular",
    dependencies=[Depends(rate_limit("company-refresh", 10))],
)
def refresh_company(
    ticker: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    engine: EngineService = request.app.state.engine
    try:
        payload = engine.payload(ticker, refresh=True)
    except EngineUnavailable as exc:
        raise ApiError(503, "engine_unavailable", str(exc)) from exc
    company = _persist_company(db, ticker, payload)
    _store_snapshot(db, company, payload)
    db.add(
        AuditEvent(
            user_id=user.id,
            action="company.refresh",
            subject=ticker.upper(),
            meta={"sha256": payload["provenance"].get("content_sha256")},
        )
    )
    return {"ok": True, "company": CompanyOut.model_validate(company).model_dump()}


@router.get("/{ticker}/analysis", summary="Análisis completo del motor")
def company_analysis(
    ticker: str,
    request: Request,
    refresh: bool = False,
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    engine: EngineService = request.app.state.engine
    try:
        return engine.payload(ticker, refresh=refresh)
    except EngineUnavailable as exc:
        raise ApiError(503, "engine_unavailable", str(exc)) from exc


@router.post(
    "/{ticker}/valuation",
    summary="Valoración con supuestos propios",
    dependencies=[Depends(rate_limit("company-valuation", 60))],
)
def custom_valuation(
    ticker: str,
    payload: ValuationRequest,
    request: Request,
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    engine: EngineService = request.app.state.engine
    try:
        return engine.custom_valuation(
            ticker,
            forecast_years=payload.forecast_years,
            discount_rate=payload.discount_rate,
            terminal_growth=payload.terminal_growth,
            growth_rate=payload.growth_rate,
            fcf_adjustment=payload.fcf_adjustment,
            share_price=payload.share_price,
            sensitivity_steps=payload.sensitivity_steps,
        )
    except InvalidAssumption as exc:
        raise ApiError(422, "invalid_assumption", str(exc)) from exc
    except EngineUnavailable as exc:
        raise ApiError(503, "engine_unavailable", str(exc)) from exc


@router.get("/{ticker}/report", summary="Informe reproducible del motor (Markdown)")
def engine_report(
    ticker: str,
    request: Request,
    save: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    engine: EngineService = request.app.state.engine
    try:
        markdown = engine.report_markdown(ticker)
    except EngineUnavailable as exc:
        raise ApiError(503, "engine_unavailable", str(exc)) from exc
    saved_id: Optional[int] = None
    if save:
        company = db.execute(
            select(Company).where(Company.ticker == ticker.upper())
        ).scalar_one_or_none()
        report = Report(
            user_id=user.id,
            company_id=company.id if company else None,
            kind="engine",
            ticker=ticker.upper(),
            title=f"Informe del motor {ticker.upper()}",
            markdown=markdown,
            payload={"base_per_share": None, "currency": "USD", "sections": []},
        )
        db.add(report)
        db.flush()
        saved_id = report.id
    return {"ticker": ticker.upper(), "format": "markdown", "markdown": markdown, "saved_report_id": saved_id}
