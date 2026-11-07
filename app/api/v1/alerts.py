"""API de alertas declarativas (Fase 6).

Rutas (todas con sesión de usuario):

- `GET /alerts` — reglas del usuario + estado del planificador.
- `POST /alerts` — crear regla (validación de semántica en el motor).
- `PATCH /alerts/{id}` / `DELETE /alerts/{id}`.
- `GET /alerts/events` — historial y alertas sin leer.
- `POST /alerts/evaluate` — revisar ahora (también lo hace el planificador sin
  tráfico externo y los sync de datos al terminar).
- `POST /alerts/events/read-all` y `POST /alerts/events/{id}/read`.

El aislamiento es absoluto: solo se ven reglas y eventos del usuario de la
sesión; un id ajeno responde 404.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.errors import ApiError
from app.models import AlertEvent, AlertRule, Instrument, User, utcnow
from app.schemas import AlertRuleCreate, AlertRuleUpdate
from app.services.alerts import AlertRuleError, AlertEngine, rule_catalog
from app.services.scheduler import SchedulerService

router = APIRouter(prefix="/alerts", tags=["alertas"])


def _engine(request: Request) -> AlertEngine:
    state = getattr(request.app.state, "alerts", None)
    if state is None:
        state = AlertEngine(request.app.state.settings)
        request.app.state.alerts = state
    return state


def _instrument(db: Session, user: User, uid: Optional[str]) -> Optional[Instrument]:
    if not uid:
        return None
    row = db.execute(
        select(Instrument).where(Instrument.uid == uid)
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "El instrumento indicado no existe.")
    return row


def _user_rule(db: Session, user: User, rule_id: int) -> AlertRule:
    row = db.execute(
        select(AlertRule).where(AlertRule.id == rule_id, AlertRule.user_id == user.id)
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "La regla no existe.")
    return row


def _instrument_map(
    db: Session, ids: List[Optional[int]]
) -> Dict[Optional[int], Optional[Instrument]]:
    unique = {value for value in ids if value is not None}
    if not unique:
        return {}
    rows = (
        db.execute(select(Instrument).where(Instrument.id.in_(unique))).scalars().all()
    )
    return {row.id: row for row in rows}


@router.get("", summary="Reglas del usuario y estado del planificador")
def list_rules(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    rules = (
        db.execute(select(AlertRule).where(AlertRule.user_id == user.id).order_by(AlertRule.id))
        .scalars()
        .all()
    )
    instruments = _instrument_map(db, [rule.instrument_id for rule in rules])
    scheduler = SchedulerService(request.app.state.settings)
    unread_count = (
        db.execute(
            select(func.count())
            .select_from(AlertEvent)
            .where(AlertEvent.user_id == user.id, AlertEvent.read_at.is_(None))
        ).scalar_one()
    )
    return {
        "rules": [
            _engine(request).rule_view(rule, instruments.get(rule.instrument_id))
            for rule in rules
        ],
        "catalog": rule_catalog(),
        "scheduler": {
            "state": scheduler.state(db),
            "interval_minutes": scheduler.interval_minutes,
        },
        "unread": unread_count,
    }


@router.post("", summary="Crear regla de alerta")
def create_rule(
    payload: AlertRuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    instrument = _instrument(db, user, payload.instrument_uid)
    engine = AlertEngine(db)
    try:
        config = engine.validate(
            kind=payload.kind,
            instrument=instrument,
            threshold=payload.threshold,
            window_days=payload.window_days,
        )
    except AlertRuleError as exc:
        raise ApiError(400, "validation_error", str(exc)) from exc
    rule = AlertRule(
        user_id=user.id,
        instrument_id=instrument.id if instrument is not None else None,
        kind=payload.kind,
        threshold=payload.threshold,
        config=config,
        active=payload.active,
    )
    db.add(rule)
    db.flush()
    return engine.rule_view(rule, instrument)


@router.patch("/{rule_id}", summary="Modificar o activar/desactivar una regla")
def update_rule(
    rule_id: int,
    payload: AlertRuleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    rule = _user_rule(db, user, rule_id)
    instrument = (
        db.get(Instrument, rule.instrument_id) if rule.instrument_id is not None else None
    )
    engine = _engine(request)
    threshold = payload.threshold if payload.threshold is not None else (
        None if rule.threshold is None else rule.threshold
    )
    window_days = payload.window_days
    if window_days is None:
        window_days = int((rule.config or {}).get("window_days") or 0) or None
    try:
        config = engine.validate(
            kind=rule.kind,
            instrument=instrument,
            threshold=threshold,
            window_days=window_days,
        )
    except AlertRuleError as exc:
        raise ApiError(400, "validation_error", str(exc)) from exc
    if payload.threshold is not None:
        rule.threshold = payload.threshold
    if payload.active is not None:
        rule.active = payload.active
    rule.config = config
    db.flush()
    return engine.rule_view(rule, instrument)


@router.delete("/{rule_id}", summary="Eliminar una regla")
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    rule = _user_rule(db, user, rule_id)
    db.delete(rule)
    db.flush()
    return {"deleted": rule_id}


@router.get("/events", summary="Historial de alertas")
def list_events(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    query = select(AlertEvent).where(AlertEvent.user_id == user.id)
    if unread_only:
        query = query.where(AlertEvent.read_at.is_(None))
    events = (
        db.execute(query.order_by(AlertEvent.created_at.desc(), AlertEvent.id.desc()).limit(limit))
        .scalars()
        .all()
    )
    instruments = _instrument_map(db, [event.instrument_id for event in events])
    totals = db.execute(
        select(func.count())
        .select_from(AlertEvent)
        .where(AlertEvent.user_id == user.id, AlertEvent.read_at.is_(None))
    ).scalar_one()
    return {
        "unread": totals,
        "events": [
            {
                "id": event.id,
                "kind": event.kind,
                "severity": event.severity,
                "title": event.title,
                "detail": dict(event.detail or {}),
                "instrument_uid": (
                    instruments[event.instrument_id].uid if event.instrument_id in instruments else None
                ),
                "created_at": event.created_at.isoformat(),
                "read_at": event.read_at.isoformat() if event.read_at else None,
            }
            for event in events
        ],
    }


@router.post("/evaluate", summary="Revisar condiciones ahora")
def evaluate_now(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    scheduler = SchedulerService(request.app.state.settings)
    events = scheduler.check_in_session(db)
    return {"new_events": len(events)}


@router.post("/events/read-all", summary="Marcar todas las alertas como leídas")
def read_all_events(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    events = (
        db.execute(
            select(AlertEvent).where(
                AlertEvent.user_id == user.id, AlertEvent.read_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    moment = utcnow()
    for event in events:
        event.read_at = event.read_at or moment
    db.flush()
    return {"marked": len(events)}


@router.post("/events/{event_id}/read", summary="Marcar una alerta como leída")
def read_event(
    event_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    event = db.execute(
        select(AlertEvent).where(AlertEvent.id == event_id, AlertEvent.user_id == user.id)
    ).scalar_one_or_none()
    if event is None:
        raise ApiError(404, "not_found", "La alerta no existe.")
    event.read_at = event.read_at or utcnow()
    db.flush()
    return {"id": event.id}
