"""API de investigación: watchlist, tesis versionadas y oportunidades (Fase 7).

Rutas (sesión obligatoria, aislamiento absoluto por usuario):

- `GET/POST/DELETE /watchlist[/{instrument_uid}]`.
- `GET/POST /opportunities` — estudios cuantitativos sobre los datos
  persistidos; sin datos suficientes el instrumento no aparece con puntuación.
- `GET/POST /theses`, `GET/PATCH/DELETE /theses/{id}`,
  `POST /theses/{id}/versions|events|evaluate`, `PATCH /theses/{id}/status`.

El motor registra indicios; los cambios de estado de una tesis son
siempre de usuario (ver DECISIONS, fase 7).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.errors import ApiError
from app.models import (
    Instrument,
    InvestmentThesis,
    User,
    WatchlistItem,
)
from app.schemas import (
    ThesisCreate,
    ThesisEventCreate,
    ThesisPatch,
    ThesisStatusUpdate,
    ThesisVersionCreate,
    WatchlistCreate,
)
from app.services.opportunities import OpportunityEngine, OpportunityError
from app.services.theses import ThesisError, ThesisService

router = APIRouter(prefix="/theses", tags=["tesis"])
board_router = APIRouter(prefix="", tags=["investigación"])


def _service() -> ThesisService:
    return ThesisService()


def _instrument(session: Session, uid: str) -> Instrument:
    row = session.execute(select(Instrument).where(Instrument.uid == uid)).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "El instrumento no existe.")
    return row


def _user_thesis(session: Session, user: User, thesis_id: int) -> InvestmentThesis:
    row = session.execute(
        select(InvestmentThesis).where(
            InvestmentThesis.id == thesis_id, InvestmentThesis.user_id == user.id
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "La tesis no existe.")
    return row


def _instrument_map(session: Session, ids) -> Dict[Optional[int], Instrument]:
    unique = {value for value in ids if value is not None}
    if not unique:
        return {}
    rows = session.execute(select(Instrument).where(Instrument.id.in_(unique))).scalars().all()
    return {row.id: row for row in rows}


# -- watchlist -----------------------------------------------------------------


@board_router.get("/watchlist", summary="Instrumentos seguidos")
def list_watchlist(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    rows = (
        session.execute(
            select(WatchlistItem)
            .where(WatchlistItem.user_id == user.id)
            .order_by(WatchlistItem.created_at.desc(), WatchlistItem.id.desc())
        )
        .scalars()
        .all()
    )
    instruments = _instrument_map(session, [row.instrument_id for row in rows])
    return {
        "items": [
            {
                "instrument_uid": instruments[row.instrument_id].uid,
                "symbol": instruments[row.instrument_id].symbol,
                "name": instruments[row.instrument_id].name,
                "currency": instruments[row.instrument_id].currency,
                "note": row.note,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
            if row.instrument_id in instruments
        ]
    }


@board_router.post("/watchlist", summary="Seguir un instrumento")
def add_watchlist(
    payload: WatchlistCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    instrument = _instrument(session, payload.instrument_uid)
    existing = session.execute(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id,
            WatchlistItem.instrument_id == instrument.id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"instrument_uid": instrument.uid, "note": existing.note, "already": True}
    row = WatchlistItem(user_id=user.id, instrument_id=instrument.id, note=payload.note or "")
    session.add(row)
    session.flush()
    return {"instrument_uid": instrument.uid, "note": row.note, "already": False}


@board_router.delete("/watchlist/{instrument_uid}", summary="Dejar de seguir")
def remove_watchlist(
    instrument_uid: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    instrument = _instrument(session, instrument_uid)
    row = session.execute(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id,
            WatchlistItem.instrument_id == instrument.id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "El instrumento no está en tu watchlist.")
    session.delete(row)
    session.flush()
    return {"removed": instrument_uid}


# -- oportunidades --------------------------------------------------------------


@board_router.get("/opportunities", summary="Estudios cuantitativos por horizonte")
def list_opportunities(
    horizon: Optional[str] = None,
    limit: int = 50,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        result = OpportunityEngine().scan(session)
    except OpportunityError as exc:
        raise ApiError(400, "validation_error", str(exc)) from exc
    items = result["items"]
    if horizon:
        items = [item for item in items if item.get("horizon") == horizon]
    return {**result, "items": items[:limit]}


# -- tesis ----------------------------------------------------------------------


@router.get("", summary="Tesis del usuario")
def list_theses(
    status: Optional[str] = None,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    query = select(InvestmentThesis).where(InvestmentThesis.user_id == user.id)
    if status in ("open", "under_review", "validated", "invalidated", "closed"):
        query = query.where(InvestmentThesis.status == status)
    rows = session.execute(query.order_by(InvestmentThesis.updated_at.desc())).scalars().all()
    instruments = _instrument_map(session, [row.instrument_id for row in rows])
    service = _service()
    return {
        "theses": [
            service.thesis_view(session, row, instruments.get(row.instrument_id))
            for row in rows
        ]
    }


@router.post("", summary="Abrir tesis")
def create_thesis(
    payload: ThesisCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    instrument = _instrument(session, payload.instrument_uid)
    service = _service()
    try:
        thesis = service.create(
            session,
            user.id,
            instrument,
            horizon=payload.horizon,
            title=payload.title,
            hypothesis=payload.hypothesis,
            invalidation_conditions=[item.model_dump() for item in payload.invalidation_conditions],
            uncertainty_level=payload.uncertainty_level,
            missing_info=payload.missing_info,
            entry_target=payload.entry_target,
            exit_target=payload.exit_target,
        )
    except ThesisError as exc:
        raise ApiError(400, "validation_error", str(exc)) from exc
    return service.thesis_view(session, thesis, instrument)


@router.get("/{thesis_id}", summary="Detalle de tesis")
def get_thesis(
    thesis_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    thesis = _user_thesis(session, user, thesis_id)
    instrument = session.get(Instrument, thesis.instrument_id)
    return _service().thesis_view(session, thesis, instrument, with_detail=True)


@router.patch("/{thesis_id}", summary="Metadatos de la tesis")
def patch_thesis(
    thesis_id: int,
    payload: ThesisPatch,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    thesis = _user_thesis(session, user, thesis_id)
    if payload.title is not None:
        thesis.title = payload.title
    if payload.missing_info is not None:
        thesis.missing_info = [item[:200] for item in payload.missing_info][:20]
    if payload.entry_target is not None:
        thesis.entry_target = payload.entry_target
    if payload.exit_target is not None:
        thesis.exit_target = payload.exit_target
    return _service().thesis_view(session, thesis, session.get(Instrument, thesis.instrument_id))


@router.post("/{thesis_id}/versions", summary="Añadir versión a la tesis")
def add_thesis_version(
    thesis_id: int,
    payload: ThesisVersionCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    thesis = _user_thesis(session, user, thesis_id)
    service = _service()
    try:
        version = service.add_version(
            session,
            thesis,
            hypothesis=payload.hypothesis,
            invalidation_conditions=(
                [item.model_dump() for item in payload.invalidation_conditions]
                if payload.invalidation_conditions is not None
                else None
            ),
            uncertainty_level=payload.uncertainty_level,
            note=payload.note,
        )
    except ThesisError as exc:
        raise ApiError(400, "validation_error", str(exc)) from exc
    return service.version_view(version)


@router.post("/{thesis_id}/events", summary="Registrar suceso manual")
def add_thesis_event(
    thesis_id: int,
    payload: ThesisEventCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    thesis = _user_thesis(session, user, thesis_id)
    service = _service()
    try:
        event = service.add_event(session, thesis, kind=payload.kind, payload=payload.payload)
    except ThesisError as exc:
        raise ApiError(400, "validation_error", str(exc)) from exc
    return service.event_view(event)


@router.patch("/{thesis_id}/status", summary="Cambiar estado de la tesis")
def set_thesis_status(
    thesis_id: int,
    payload: ThesisStatusUpdate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    thesis = _user_thesis(session, user, thesis_id)
    service = _service()
    try:
        event = service.set_status(session, thesis, payload.status, note=payload.note)
    except ThesisError as exc:
        raise ApiError(400, "validation_error", str(exc)) from exc
    return {
        "status": thesis.status,
        "event": service.event_view(event) if event.kind != "noop" else None,
    }


@router.delete("/{thesis_id}", summary="Eliminar tesis")
def delete_thesis(
    thesis_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    thesis = _user_thesis(session, user, thesis_id)
    session.delete(thesis)
    session.flush()
    return {"deleted": thesis_id}


@router.post("/evaluate", summary="Revisar tesis abiertas")
def evaluate_theses(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return {"new_events": _service().evaluate_user(session, user.id)}
