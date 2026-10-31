"""Estado del sistema y panel de inicio."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, rate_limit
from app.models import Company, Portfolio, Report, ResearchJob, User
from app.schemas import HealthResponse
from app.services.jobs import usage_snapshot

router = APIRouter(tags=["sistema"])


@router.get("/health", response_model=HealthResponse, summary="Salud del servicio")
def health(request: Request, db: Session = Depends(get_db)) -> HealthResponse:
    database = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        database = "error"
    settings = request.app.state.settings
    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        version=settings.app_version,
        environment=settings.environment,
        database=database,
        ai_enabled=bool(request.app.state.orchestrator.available),
        engine="nexo_invest",
        time=datetime.now(timezone.utc),
    )


@router.get("/dashboard", summary="Resumen del panel de inicio")
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    jobs = (
        db.execute(
            select(ResearchJob)
            .where(ResearchJob.user_id == user.id)
            .order_by(ResearchJob.created_at.desc())
            .limit(6)
        )
        .scalars()
        .all()
    )
    reports = (
        db.execute(
            select(Report)
            .where(Report.user_id == user.id)
            .order_by(Report.created_at.desc())
            .limit(6)
        )
        .scalars()
        .all()
    )
    companies = (
        db.execute(select(Company).order_by(Company.updated_at.desc()).limit(8))
        .scalars()
        .all()
    )
    portfolios = (
        db.execute(select(Portfolio).where(Portfolio.user_id == user.id)).scalars().all()
    )
    active_jobs = db.execute(
        select(func.count())
        .select_from(ResearchJob)
        .where(ResearchJob.user_id == user.id, ResearchJob.status.in_(["queued", "running"]))
    ).scalar_one()
    failed_jobs = db.execute(
        select(func.count())
        .select_from(ResearchJob)
        .where(ResearchJob.user_id == user.id, ResearchJob.status == "failed")
    ).scalar_one()
    settings = request.app.state.settings
    usage = usage_snapshot(db, user.id)
    alerts = []
    if failed_jobs:
        alerts.append(
            {
                "level": "warning",
                "message": f"{failed_jobs} investigación(es) fallida(s) en el historial.",
            }
        )
    if usage["remaining_usd"] <= 0:
        alerts.append(
            {
                "level": "warning",
                "message": "Presupuesto mensual de IA agotado: solo modo básico disponible.",
            }
        )
    if not request.app.state.orchestrator.available:
        alerts.append(
            {
                "level": "info",
                "message": "Sin proveedores de IA configurados: las investigaciones se generan "
                "con el motor y la procedencia, sin análisis cualitativo.",
            }
        )
    if not settings.sec_contact:
        alerts.append(
            {
                "level": "error",
                "message": "Falta NEXO_SEC_CONTACT: el motor no puede descargar datos de la SEC.",
            }
        )
    return {
        "system": {
            "version": settings.app_version,
            "environment": settings.environment,
            "ai_available": request.app.state.orchestrator.available,
            "engine_ready": bool(settings.sec_contact),
            "providers": [p.public_view() for p in settings.providers],
            "jobs_running": int(active_jobs),
        },
        "usage": usage,
        "jobs": [
            {
                "id": job.id,
                "ticker": job.ticker,
                "status": job.status,
                "stage": job.stage,
                "profile": job.profile,
                "created_at": job.created_at.isoformat(),
                "report_id": job.report_id,
            }
            for job in jobs
        ],
        "reports": [
            {
                "id": report.id,
                "ticker": report.ticker,
                "title": report.title,
                "kind": report.kind,
                "created_at": report.created_at.isoformat(),
            }
            for report in reports
        ],
        "companies": [
            {"ticker": company.ticker, "name": company.name, "cik": company.cik}
            for company in companies
        ],
        "portfolios": [
            {"id": p.id, "name": p.name, "cash": p.cash, "currency": p.currency}
            for p in portfolios
        ],
        "alerts": alerts,
    }


@router.get(
    "/system/logs",
    summary="Eventos de auditoría de la cuenta",
    dependencies=[Depends(rate_limit("system-logs", 30))],
)
def audit_log(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = 50,
) -> Dict[str, Any]:
    from app.models import AuditEvent

    rows = (
        db.execute(
            select(AuditEvent)
            .where(AuditEvent.user_id == user.id)
            .order_by(AuditEvent.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "action": row.action,
                "subject": row.subject,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
        "total": len(rows),
    }
