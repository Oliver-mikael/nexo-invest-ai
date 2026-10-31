"""Investigaciones con IA: creación, seguimiento, pasos y cancelación."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import client_key, get_current_user, rate_limit
from app.errors import ApiError
from app.models import AuditEvent, ResearchJob, ResearchStep, User, utcnow
from app.schemas import ResearchCreateRequest
from app.security import hourly_limiter
from app.services.engine import EngineUnavailable
from app.services.jobs import (
    JobError,
    job_status_payload,
    record_usage,
    usage_snapshot,
)

router = APIRouter(prefix="/research", tags=["investigación"])


def _job_or_404(db: Session, user: User, job_id: int) -> ResearchJob:
    job = db.execute(
        select(ResearchJob).where(
            ResearchJob.id == job_id, ResearchJob.user_id == user.id
        )
    ).scalar_one_or_none()
    if job is None:
        raise ApiError(404, "not_found", "La investigación no existe.")
    return job


@router.get("/plan", summary="Plan de ejecución del orquestador")
def research_plan(
    request: Request,
    profile: str = Query(default="standard"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    orchestrator = request.app.state.orchestrator
    settings = request.app.state.settings
    plan = orchestrator.plan(profile)
    return {
        "ai_available": orchestrator.available,
        "providers": [
            provider.public_view() for provider in settings.providers
        ],
        "plan": plan,
        "usage": usage_snapshot(db, user.id),
        "default_budget_usd": settings.default_job_budget_usd,
        "max_budget_usd": settings.max_job_budget_usd,
    }


@router.post(
    "",
    status_code=202,
    summary="Iniciar una investigación",
    dependencies=[Depends(rate_limit("research-create", 30))],
)
def create_research(
    payload: ResearchCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    settings = request.app.state.settings
    orchestrator = request.app.state.orchestrator
    runner = request.app.state.jobs

    allowed, retry_after = hourly_limiter(settings.research_jobs_per_hour).check(
        f"jobs:{user.id}"
    )
    if not allowed:
        raise ApiError(
            429,
            "job_quota_exceeded",
            "Has alcanzado el límite de investigaciones por hora.",
            {"retry_after_seconds": round(retry_after, 1)},
        )

    active = db.execute(
        select(func.count())
        .select_from(ResearchJob)
        .where(
            ResearchJob.user_id == user.id,
            ResearchJob.status.in_(["queued", "running"]),
        )
    ).scalar_one()
    if active >= settings.max_concurrent_jobs_per_user:
        raise ApiError(
            429,
            "too_many_jobs",
            "Ya tienes investigaciones en curso. Espera a que terminen.",
            {"active": int(active), "limit": settings.max_concurrent_jobs_per_user},
        )

    profile = payload.profile
    if profile != "basic" and not orchestrator.available:
        profile = "basic"

    budget = payload.budget_usd or settings.default_job_budget_usd
    budget = min(budget, settings.max_job_budget_usd)
    usage = usage_snapshot(db, user.id)
    if profile != "basic" and usage["remaining_usd"] < min(budget, 0.01):
        raise ApiError(
            402,
            "budget_exhausted",
            "Presupuesto mensual de IA agotado. Puedes seguir en modo básico sin IA.",
            {"usage": usage},
        )

    ticker = payload.ticker.upper()
    try:
        engine_payload = request.app.state.engine.payload(ticker)
    except EngineUnavailable as exc:
        raise ApiError(503, "engine_unavailable", str(exc)) from exc

    company_id: Optional[int] = None
    from app.models import Company

    company = db.execute(
        select(Company).where(Company.ticker == ticker)
    ).scalar_one_or_none()
    if company is not None:
        company_id = company.id

    job = ResearchJob(
        user_id=user.id,
        company_id=company_id,
        ticker=ticker,
        status="queued",
        stage="en cola",
        profile=profile,
        budget_usd=round(budget, 4),
        payload={
            "company": engine_payload["identity"].get("name"),
            "forecast_years": payload.forecast_years,
            "requested_profile": payload.profile,
        },
    )
    db.add(job)
    db.flush()
    db.add(
        AuditEvent(
            user_id=user.id,
            action="research.created",
            subject=f"{ticker}#{job.id}",
            meta={"profile": profile, "budget_usd": job.budget_usd},
            ip=client_key(request),
        )
    )
    record_usage(db, user.id, cost_usd=0.0, tokens_in=0, tokens_out=0)
    db.commit()

    try:
        runner.submit(job.id)
    except JobError as exc:
        raise ApiError(503, "queue_unavailable", str(exc)) from exc

    return {
        "id": job.id,
        "ticker": ticker,
        "status": job.status,
        "profile": job.profile,
        "budget_usd": job.budget_usd,
        "note": (
            "Perfil básico: sin IA, el informe se construye con el motor y la procedencia."
            if profile == "basic" and payload.profile != "basic"
            else ""
        ),
    }


@router.get("", summary="Listar investigaciones")
def list_research(
    status: Optional[str] = Query(default=None, max_length=20),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    statement = select(ResearchJob).where(ResearchJob.user_id == user.id)
    if status:
        statement = statement.where(ResearchJob.status == status)
    rows = (
        db.execute(statement.order_by(ResearchJob.created_at.desc()).limit(limit))
        .scalars()
        .all()
    )
    return {
        "items": [job_status_payload(row) for row in rows],
        "total": len(rows),
    }


@router.get("/{job_id}", summary="Estado detallado de una investigación")
def get_research(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    job = _job_or_404(db, user, job_id)
    steps = (
        db.execute(
            select(ResearchStep)
            .where(ResearchStep.job_id == job.id)
            .order_by(ResearchStep.id)
        )
        .scalars()
        .all()
    )
    return job_status_payload(job, list(steps))


@router.post("/{job_id}/cancel", summary="Cancelar una investigación")
def cancel_research(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    job = _job_or_404(db, user, job_id)
    if job.status in {"completed", "failed", "cancelled"}:
        return {"id": job.id, "status": job.status, "changed": False}
    job.cancel_requested = True
    if job.status == "queued":
        job.status = "cancelled"
        job.stage = "cancelado antes de ejecutar"
        job.finished_at = utcnow()
    else:
        job.stage = "cancelación solicitada"
    db.add(
        AuditEvent(
            user_id=user.id,
            action="research.cancel",
            subject=f"{job.ticker}#{job.id}",
            meta={},
        )
    )
    return {"id": job.id, "status": job.status, "changed": True}


@router.get("/{job_id}/steps", summary="Pasos ejecutados por los roles de IA")
def research_steps(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    job = _job_or_404(db, user, job_id)
    steps: List[ResearchStep] = list(
        db.execute(
            select(ResearchStep)
            .where(ResearchStep.job_id == job.id)
            .order_by(ResearchStep.id)
        )
        .scalars()
        .all()
    )
    return {"job_id": job.id, "steps": [step_payload(step) for step in steps]}


def step_payload(step: ResearchStep) -> Dict[str, Any]:
    return {
        "role": step.role,
        "status": step.status,
        "provider": step.provider,
        "model": step.model,
        "tokens_in": step.tokens_in,
        "tokens_out": step.tokens_out,
        "cost_usd": step.cost_usd,
        "error": step.error,
        "output": step.output,
    }
