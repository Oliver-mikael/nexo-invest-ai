"""Cola de trabajos de investigación con estado persistente.

Propiedades que exige el producto:

- El estado vive en la base de datos, no en memoria: un reinicio no pierde trabajos.
- Los trabajos interrumpidos se recuperan al arrancar (o se marcan fallidos tras
  agotar los intentos).
- Cancelación cooperativa entre pasos.
- Presupuesto por trabajo y límite mensual por usuario.
- Reintentos acotados con espera, no bucles infinitos.

El ejecutor es un `ThreadPoolExecutor` en el mismo proceso. Para varias instancias
hace falta un broker (Redis/RQ o similar); queda documentado como límite actual.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.base import BudgetExceeded
from app.ai.orchestrator import AIOrchestrator, RoleResult
from app.config import Settings, load_settings
from app.db import get_session_factory, session_scope
from app.models import (
    AuditEvent,
    Company,
    Report,
    ResearchJob,
    ResearchStep,
    UsageCounter,
    UserSettings,
    utcnow,
)
from app.services.engine import EngineService, EngineUnavailable
from app.services.research import assemble


class JobError(RuntimeError):
    pass


def monthly_period(moment: Optional[datetime] = None) -> str:
    moment = moment or datetime.now(timezone.utc)
    return moment.strftime("%Y-%m")


def usage_snapshot(session: Session, user_id: int) -> Dict[str, Any]:
    period = monthly_period()
    counter = session.execute(
        select(UsageCounter).where(
            UsageCounter.user_id == user_id, UsageCounter.period == period
        )
    ).scalar_one_or_none()
    settings = session.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    ).scalar_one_or_none()
    limit = settings.monthly_budget_usd if settings else 10.0
    used = counter.cost_usd if counter else 0.0
    return {
        "period": period,
        "used_usd": round(used, 6),
        "limit_usd": round(limit, 2),
        "remaining_usd": round(max(0.0, limit - used), 6),
        "jobs": counter.jobs if counter else 0,
        "tokens_in": counter.tokens_in if counter else 0,
        "tokens_out": counter.tokens_out if counter else 0,
    }


def record_usage(
    session: Session,
    user_id: int,
    *,
    cost_usd: float,
    tokens_in: int,
    tokens_out: int,
    jobs: int = 0,
) -> UsageCounter:
    period = monthly_period()
    counter = session.execute(
        select(UsageCounter).where(
            UsageCounter.user_id == user_id, UsageCounter.period == period
        )
    ).scalar_one_or_none()
    if counter is None:
        counter = UsageCounter(user_id=user_id, period=period)
        session.add(counter)
        session.flush()
    counter.cost_usd = round(counter.cost_usd + cost_usd, 6)
    counter.tokens_in += tokens_in
    counter.tokens_out += tokens_out
    counter.jobs += jobs
    return counter


def previous_reports(session: Session, user_id: int, ticker: str, limit: int = 3) -> List[Dict[str, Any]]:
    rows = (
        session.execute(
            select(Report)
            .where(Report.user_id == user_id, Report.ticker == ticker.upper())
            .order_by(Report.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    items: List[Dict[str, Any]] = []
    for row in rows:
        payload = row.payload or {}
        items.append(
            {
                "id": row.id,
                "created_at": row.created_at.isoformat(),
                "base_per_share": payload.get("base_per_share"),
                "currency": payload.get("currency"),
                "thesis": _thesis_of(payload),
            }
        )
    return items


def _thesis_of(payload: Dict[str, Any]) -> str:
    for section in payload.get("sections", []):
        if section.get("id") in {"thesis", "conclusion"}:
            paragraphs = section.get("paragraphs") or []
            if paragraphs:
                return str(paragraphs[0])[:400]
    return ""


class JobRunner:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        engine: Optional[EngineService] = None,
        orchestrator: Optional[AIOrchestrator] = None,
        *,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.engine = engine or EngineService(self.settings)
        self.orchestrator = orchestrator or AIOrchestrator(self.settings)
        self._session_factory = session_factory or get_session_factory()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._futures: Dict[int, Future] = {}
        self._lock = threading.Lock()

    # -- ciclo de vida ----------------------------------------------------------

    def start(self) -> None:
        if self._executor is not None:
            return
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, self.settings.worker_threads),
            thread_name_prefix="nexo-job",
        )
        for job_id in self.recover_interrupted():
            self.submit(job_id)

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=False)
            self._executor = None

    @property
    def running(self) -> bool:
        with self._lock:
            return any(not f.done() for f in self._futures.values())

    def submit(self, job_id: int) -> None:
        if self._executor is None:
            raise JobError("El ejecutor de trabajos no está iniciado")
        with self._lock:
            existing = self._futures.get(job_id)
            if existing is not None and not existing.done():
                return
            self._futures[job_id] = self._executor.submit(self._process, job_id)

    # -- recuperación -----------------------------------------------------------

    def recover_interrupted(self) -> List[int]:
        requeue: List[int] = []
        with session_scope() as session:
            rows = (
                session.execute(
                    select(ResearchJob).where(ResearchJob.status.in_(["running", "queued"]))
                )
                .scalars()
                .all()
            )
            for job in rows:
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.stage = "cancelado antes de ejecutar"
                    job.finished_at = utcnow()
                    continue
                if job.status == "running":
                    if job.attempts >= self.settings.job_max_attempts:
                        job.status = "failed"
                        job.stage = "interrumpido"
                        job.error = "El proceso se interrumpió y se agotaron los reintentos."
                        job.finished_at = utcnow()
                        continue
                    job.status = "queued"
                    job.stage = "recuperado tras reinicio"
                requeue.append(job.id)
        return requeue

    # -- ejecución --------------------------------------------------------------

    def _process(self, job_id: int) -> None:
        try:
            with session_scope() as session:
                job = session.get(ResearchJob, job_id)
                if job is None or job.status not in {"queued", "running"}:
                    return
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.finished_at = utcnow()
                    return
                job.status = "running"
                job.attempts += 1
                job.started_at = utcnow()
                job.stage = "datos"
                job.error = ""
                user_id = job.user_id
                ticker = job.ticker
                profile = job.profile
                budget = job.budget_usd

            self._run_research(job_id, user_id, ticker, profile, budget)
        except BudgetExceeded as exc:
            self._fail(job_id, f"presupuesto agotado: {exc}", retry=False)
        except EngineUnavailable as exc:
            self._fail(job_id, f"datos no disponibles: {exc}", retry=False)
        except Exception as exc:  # nunca deja el trabajo colgado en "running"
            self._fail(job_id, f"{type(exc).__name__}: {exc}", retry=True)

    def _run_research(
        self, job_id: int, user_id: int, ticker: str, profile: str, budget: float
    ) -> None:
        started = datetime.now(timezone.utc)
        bundle = self.engine.analysis(ticker)
        self._stage(job_id, "valoración")

        with session_scope() as session:
            company = session.execute(
                select(Company).where(Company.ticker == ticker.upper())
            ).scalar_one_or_none()
            previous = previous_reports(session, user_id, ticker)
            company_id = company.id if company else None
            prefs = session.execute(
                select(UserSettings).where(UserSettings.user_id == user_id)
            ).scalar_one_or_none()
            preferred_provider = prefs.preferred_provider if prefs else ""

        chosen_profile = profile if self.orchestrator.available else "basic"
        orchestration = None
        if chosen_profile != "basic":
            self._stage(job_id, "agentes")

            def on_step(role: RoleResult) -> None:
                with session_scope() as session:
                    step = ResearchStep(
                        job_id=job_id,
                        role=role.role,
                        provider=role.provider,
                        model=role.model,
                        status=role.status,
                        tokens_in=role.usage.tokens_in,
                        tokens_out=role.usage.tokens_out,
                        cost_usd=role.usage.cost_usd,
                        output=role.output,
                        error=role.error,
                        started_at=started,
                        finished_at=utcnow(),
                    )
                    session.add(step)
                    job = session.get(ResearchJob, job_id)
                    if job is not None:
                        job.tokens_in += role.usage.tokens_in
                        job.tokens_out += role.usage.tokens_out
                        job.cost_usd = round(job.cost_usd + role.usage.cost_usd, 6)

            orchestration = self.orchestrator.run(
                profile=chosen_profile,
                identity=bundle.payload["identity"],
                ledger=bundle.payload.get("ledger", []),
                valuation=bundle.payload["valuation"],
                provenance=bundle.payload["provenance"],
                previous=previous,
                budget_usd=budget,
                preferred_provider=preferred_provider,
                on_step=on_step,
                should_cancel=lambda: self._should_stop(job_id, started),
            )

        self._stage(job_id, "auditoría")
        document = assemble(
            bundle=bundle,
            orchestration=orchestration,
            previous=previous,
        )

        cancelled = self._cancelled(job_id)
        with session_scope() as session:
            job = session.get(ResearchJob, job_id)
            if job is None:
                return
            report = Report(
                user_id=job.user_id,
                company_id=company_id,
                job_id=job.id,
                kind="research",
                ticker=ticker.upper(),
                title=f"Investigación {ticker.upper()}",
                markdown=document["markdown"],
                payload=document,
            )
            session.add(report)
            session.flush()
            job.report_id = report.id
            job.stage = "informe"
            job.payload = {
                "audit": document["audit"],
                "profile": document["profile"],
                "base_per_share": document["base_per_share"],
            }
            if cancelled:
                job.status = "cancelled"
                job.stage = "cancelado (informe parcial guardado)"
            else:
                job.status = "completed"
                job.stage = "completado"
            job.finished_at = utcnow()
            if job.cost_usd or job.tokens_in or job.tokens_out:
                record_usage(
                    session,
                    job.user_id,
                    cost_usd=job.cost_usd,
                    tokens_in=job.tokens_in,
                    tokens_out=job.tokens_out,
                    jobs=1,
                )
            session.add(
                AuditEvent(
                    user_id=job.user_id,
                    action="research.completed" if not cancelled else "research.cancelled",
                    subject=f"{ticker.upper()}#{job.id}",
                    meta={
                        "profile": document["profile"],
                        "cost_usd": job.cost_usd,
                        "report_id": report.id,
                    },
                )
            )

    def _should_stop(self, job_id: int, started: datetime) -> bool:
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        if elapsed > self.settings.job_timeout_seconds:
            self._fail(job_id, "tiempo máximo de ejecución superado", retry=False)
            return True
        return self._cancelled(job_id)

    def _cancelled(self, job_id: int) -> bool:
        with session_scope() as session:
            job = session.get(ResearchJob, job_id)
            return bool(job and job.cancel_requested)

    def _stage(self, job_id: int, stage: str) -> None:
        with session_scope() as session:
            job = session.get(ResearchJob, job_id)
            if job is not None:
                job.stage = stage

    def _fail(self, job_id: int, error: str, *, retry: bool) -> None:
        with session_scope() as session:
            job = session.get(ResearchJob, job_id)
            if job is None:
                return
            job.error = error[:1200]
            exhausted = job.attempts >= self.settings.job_max_attempts
            if retry and not exhausted and not job.cancel_requested:
                job.status = "queued"
                job.stage = "reintentando"
                retry_id = job.id
            else:
                job.status = "cancelled" if job.cancel_requested else "failed"
                job.stage = "fallido"
                job.finished_at = utcnow()
                session.add(
                    AuditEvent(
                        user_id=job.user_id,
                        action="research.failed",
                        subject=f"{job.ticker}#{job.id}",
                        meta={"error": job.error},
                    )
                )
                retry_id = None
        if retry_id is not None:
            with self._lock:
                self._futures.pop(retry_id, None)
            self.submit(retry_id)

    # -- utilidades -------------------------------------------------------------

    def wait(self, timeout: float = 10.0) -> None:
        with self._lock:
            futures = list(self._futures.values())
        for future in futures:
            future.result(timeout=timeout)


def job_status_payload(job: ResearchJob, steps: Optional[List[ResearchStep]] = None) -> Dict[str, Any]:
    return {
        "id": job.id,
        "ticker": job.ticker,
        "status": job.status,
        "stage": job.stage,
        "profile": job.profile,
        "budget_usd": job.budget_usd,
        "cost_usd": job.cost_usd,
        "tokens_in": job.tokens_in,
        "tokens_out": job.tokens_out,
        "attempts": job.attempts,
        "cancel_requested": job.cancel_requested,
        "error": job.error,
        "report_id": job.report_id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "steps": [
            {
                "role": step.role,
                "status": step.status,
                "provider": step.provider,
                "model": step.model,
                "tokens_in": step.tokens_in,
                "tokens_out": step.tokens_out,
                "cost_usd": step.cost_usd,
                "error": step.error,
            }
            for step in (steps or [])
        ],
    }


def stale_job_cutoff(seconds: int = 3600) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)
