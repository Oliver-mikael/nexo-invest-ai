"""Preferencias de la cuenta y consumo de IA."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import AuditEvent, User, UserSettings
from app.schemas import SettingsUpdate
from app.services.jobs import usage_snapshot

router = APIRouter(prefix="/settings", tags=["configuración"])


def _settings_row(db: Session, user: User) -> UserSettings:
    row = db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    ).scalar_one_or_none()
    if row is None:
        row = UserSettings(user_id=user.id)
        db.add(row)
        db.flush()
    return row


@router.get("", summary="Preferencias y consumo")
def get_settings(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    row = _settings_row(db, user)
    app_settings = request.app.state.settings
    return {
        "ai_profile": row.ai_profile,
        "monthly_budget_usd": row.monthly_budget_usd,
        "default_forecast_years": row.default_forecast_years,
        "preferred_provider": row.preferred_provider,
        "benchmark": row.benchmark,
        "usage": usage_snapshot(db, user.id),
        "default_job_budget_usd": app_settings.default_job_budget_usd,
        "max_job_budget_usd": app_settings.max_job_budget_usd,
        "ai_available": request.app.state.orchestrator.available,
        "providers": [p.public_view() for p in app_settings.providers],
    }


@router.patch("", summary="Actualizar preferencias")
def update_settings(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    row = _settings_row(db, user)
    changes: Dict[str, Any] = {}
    for field in (
        "ai_profile",
        "monthly_budget_usd",
        "default_forecast_years",
        "preferred_provider",
        "benchmark",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(row, field, value)
            changes[field] = value
    if changes:
        db.add(
            AuditEvent(
                user_id=user.id,
                action="settings.updated",
                subject=str(user.id),
                meta=changes,
            )
        )
    return {"ok": True, "updated": changes}
