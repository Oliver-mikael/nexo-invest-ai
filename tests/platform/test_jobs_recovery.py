"""Recuperación de trabajos tras un reinicio y contabilidad de consumo."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.ai.orchestrator import AIOrchestrator
from app.db import configure, init_db, session_scope
from app.models import ResearchJob, User
from app.services.engine import EngineService
from app.services.jobs import JobRunner, monthly_period, record_usage, usage_snapshot
from app.security import hash_password
from tests.platform.conftest import apple_result


def _prepare(settings):
    configure(settings)
    init_db()
    with session_scope() as session:
        user = User(
            email="jobs@nexo.invalid",
            password_hash=hash_password("clave-segura-123"),
            display_name="Jobs",
        )
        session.add(user)
        session.flush()
        return user.id


def test_running_job_is_requeued_after_restart(settings):
    user_id = _prepare(settings)
    with session_scope() as session:
        job = ResearchJob(user_id=user_id, ticker="AAPL", status="running", attempts=0)
        session.add(job)
        session.flush()
        job_id = job.id

    runner = JobRunner(
        settings,
        EngineService(settings, loader=lambda ticker: apple_result()),
        AIOrchestrator(settings, {}),
    )
    requeued = runner.recover_interrupted()
    assert job_id in requeued
    with session_scope() as session:
        job = session.get(ResearchJob, job_id)
        assert job.status == "queued"
        assert job.stage == "recuperado tras reinicio"


def test_exhausted_job_is_marked_failed(settings):
    user_id = _prepare(settings)
    with session_scope() as session:
        job = ResearchJob(
            user_id=user_id, ticker="AAPL", status="running", attempts=settings.job_max_attempts
        )
        session.add(job)
        session.flush()
        job_id = job.id

    runner = JobRunner(
        settings,
        EngineService(settings, loader=lambda ticker: apple_result()),
        AIOrchestrator(settings, {}),
    )
    runner.recover_interrupted()
    with session_scope() as session:
        job = session.get(ResearchJob, job_id)
        assert job.status == "failed"
        assert "reintentos" in job.error


def test_cancelled_before_start_is_not_requeued(settings):
    user_id = _prepare(settings)
    with session_scope() as session:
        job = ResearchJob(
            user_id=user_id, ticker="AAPL", status="queued", attempts=0, cancel_requested=True
        )
        session.add(job)
        session.flush()
        job_id = job.id

    runner = JobRunner(
        settings,
        EngineService(settings, loader=lambda ticker: apple_result()),
        AIOrchestrator(settings, {}),
    )
    assert job_id not in runner.recover_interrupted()
    with session_scope() as session:
        assert session.get(ResearchJob, job_id).status == "cancelled"


def test_usage_counters_accumulate(settings):
    user_id = _prepare(settings)
    with session_scope() as session:
        record_usage(session, user_id, cost_usd=0.25, tokens_in=100, tokens_out=50, jobs=1)
        record_usage(session, user_id, cost_usd=0.10, tokens_in=10, tokens_out=5, jobs=1)
    with session_scope() as session:
        usage = usage_snapshot(session, user_id)
    assert usage["period"] == monthly_period()
    assert usage["used_usd"] == pytest.approx(0.35, rel=1e-6)
    assert usage["jobs"] == 2
    assert usage["tokens_in"] == 110
    assert usage["remaining_usd"] == pytest.approx(9.65, rel=1e-6)


def test_usage_rows_are_per_period(settings):
    user_id = _prepare(settings)
    with session_scope() as session:
        record_usage(session, user_id, cost_usd=1.0, tokens_in=1, tokens_out=1, jobs=1)
        from app.models import UsageCounter

        counters = session.execute(select(UsageCounter)).scalars().all()
    assert len(counters) == 1
    assert counters[0].period == monthly_period()

