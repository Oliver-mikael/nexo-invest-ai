"""Cartera real multimercado: cuentas, movimientos y métricas."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, rate_limit
from app.errors import ApiError
from app.models import AuditEvent, Instrument, RealAccount, RealMovement, User
from app.schemas import RealAccountCreate, RealAccountUpdate, RealMovementCreate
from app.services.accounting import LedgerError, replay
from app.services.real_movements import (
    create_movement,
    ledger_for,
    movement_payload,
    update_movement,
)
from app.services.real_portfolio import account_summary, overview

router = APIRouter(prefix="/real", tags=["cartera real"])


def _account_or_404(db: Session, user: User, account_id: int) -> RealAccount:
    account = db.execute(
        select(RealAccount).where(
            RealAccount.id == account_id, RealAccount.user_id == user.id
        )
    ).scalar_one_or_none()
    if account is None:
        raise ApiError(404, "not_found", "La cuenta real no existe.")
    return account


def _movement_or_404(
    db: Session, account: RealAccount, movement_id: int
) -> RealMovement:
    row = db.execute(
        select(RealMovement).where(
            RealMovement.id == movement_id, RealMovement.account_id == account.id
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "El movimiento no existe en esta cuenta.")
    return row


def account_payload(account: RealAccount, *, positions: int = 0) -> Dict[str, Any]:
    return {
        "id": account.id,
        "name": account.name,
        "broker_name": account.broker_name,
        "broker_country": account.broker_country,
        "account_type": account.account_type,
        "base_currency": account.base_currency,
        "cost_method": account.cost_method,
        "commission_scheme": account.commission_scheme or {},
        "allow_negative_cash": account.allow_negative_cash,
        "allow_short": account.allow_short,
        "status": account.status,
        "positions": positions,
        "created_at": account.created_at.isoformat() if account.created_at else None,
    }


@router.get("/accounts", summary="Listar cuentas reales")
def list_accounts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    accounts = (
        db.execute(
            select(RealAccount)
            .where(RealAccount.user_id == user.id)
            .order_by(RealAccount.created_at, RealAccount.id)
        )
        .scalars()
        .all()
    )
    items = []
    for account in accounts:
        count = db.execute(
            select(func.count(RealMovement.id)).where(
                RealMovement.account_id == account.id
            )
        ).scalar_one()
        items.append(account_payload(account, positions=int(count)))
    return {"items": items, "total": len(items)}


@router.post("/accounts", status_code=201, summary="Crear una cuenta real")
def create_account(
    payload: RealAccountCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    account = RealAccount(
        user_id=user.id,
        name=payload.name.strip(),
        broker_name=payload.broker_name.strip(),
        broker_country=payload.broker_country,
        account_type=payload.account_type,
        base_currency=payload.base_currency,
        cost_method=payload.cost_method,
        commission_scheme=payload.commission_scheme,
        allow_negative_cash=payload.allow_negative_cash,
        allow_short=payload.allow_short,
        status="active",
    )
    db.add(account)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ApiError(
            409, "account_exists", "Ya tienes una cuenta real con ese nombre."
        ) from exc
    db.add(
        AuditEvent(
            user_id=user.id,
            action="real_account.created",
            subject=str(account.id),
            meta={"base_currency": account.base_currency, "broker": account.broker_name},
        )
    )
    return account_payload(account)


@router.get("/accounts/{account_id}", summary="Detalle de una cuenta real")
def get_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    return account_payload(account)


@router.patch("/accounts/{account_id}", summary="Actualizar una cuenta real")
def update_account(
    account_id: int,
    payload: RealAccountUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    data = payload.model_dump(exclude_unset=True)
    if "base_currency" in data and data["base_currency"] != account.base_currency:
        has_movements = db.execute(
            select(func.count(RealMovement.id)).where(
                RealMovement.account_id == account.id
            )
        ).scalar_one()
        if has_movements:
            raise ApiError(
                422,
                "base_currency_locked",
                "No se puede cambiar la moneda base de una cuenta con movimientos: "
                "los tipos de cambio históricos quedarían inconsistentes.",
            )
    if "cost_method" in data and data["cost_method"] != account.cost_method:
        db.add(
            AuditEvent(
                user_id=user.id,
                action="real_account.cost_method_changed",
                subject=str(account.id),
                meta={"from": account.cost_method, "to": data["cost_method"]},
            )
        )
    for field, value in data.items():
        if field == "name" and isinstance(value, str):
            value = value.strip()
        setattr(account, field, value)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ApiError(409, "account_exists", "Ya existe otra cuenta con ese nombre.") from exc
    return account_payload(account)


@router.delete("/accounts/{account_id}", summary="Eliminar una cuenta real y sus movimientos")
def delete_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    db.delete(account)
    db.add(
        AuditEvent(
            user_id=user.id,
            action="real_account.deleted",
            subject=str(account_id),
            meta={"name": account.name, "currency": account.base_currency},
        )
    )
    return {"ok": True, "deleted": account_id}


@router.get("/accounts/{account_id}/summary", summary="Valoración y rentabilidad de la cuenta")
def get_summary(
    account_id: int,
    as_of: Optional[date] = Query(default=None),
    twr: bool = Query(default=True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    return account_summary(db, account, as_of=as_of, include_twr=twr)


@router.get("/accounts/{account_id}/movements", summary="Movimientos de la cuenta")
def list_movements(
    account_id: int,
    movement_type: Optional[str] = Query(default=None, max_length=24),
    instrument_uid: Optional[str] = Query(default=None, max_length=36),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    query = select(RealMovement).where(RealMovement.account_id == account.id)
    if movement_type:
        query = query.where(RealMovement.movement_type == movement_type)
    if instrument_uid:
        instrument = db.execute(
            select(Instrument).where(Instrument.uid == instrument_uid)
        ).scalar_one_or_none()
        if instrument is None:
            raise ApiError(404, "instrument_not_found", "El instrumento no existe.")
        query = query.where(RealMovement.instrument_id == instrument.id)
    if from_date:
        query = query.where(RealMovement.movement_date >= from_date)
    if to_date:
        query = query.where(RealMovement.movement_date <= to_date)
    total = db.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar_one()
    rows = (
        db.execute(
            query.order_by(RealMovement.movement_date.desc(), RealMovement.id.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return {
        "items": [movement_payload(db, row) for row in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.post(
    "/accounts/{account_id}/movements",
    status_code=201,
    summary="Registrar un movimiento real (manual)",
    dependencies=[Depends(rate_limit("real-movement", 120))],
)
def create_real_movement(
    account_id: int,
    payload: RealMovementCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    row = create_movement(db, account, payload, source="manual")
    db.add(
        AuditEvent(
            user_id=user.id,
            action="real_movement.created",
            subject=f"{account.id}:{row.id}",
            meta={
                "type": row.movement_type,
                "instrument_id": row.instrument_id,
                "date": row.movement_date.isoformat(),
            },
        )
    )
    return {"movement": movement_payload(db, row)}


@router.get(
    "/accounts/{account_id}/movements/{movement_id}",
    summary="Detalle de un movimiento",
)
def get_movement(
    account_id: int,
    movement_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    return movement_payload(db, _movement_or_404(db, account, movement_id))


@router.patch(
    "/accounts/{account_id}/movements/{movement_id}",
    summary="Corregir un movimiento con nueva validación del libro",
)
def edit_movement(
    account_id: int,
    movement_id: int,
    payload: RealMovementCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    row = _movement_or_404(db, account, movement_id)
    update_movement(db, account, row, payload)
    db.add(
        AuditEvent(
            user_id=user.id,
            action="real_movement.updated",
            subject=f"{account.id}:{movement_id}",
            meta={"type": row.movement_type},
        )
    )
    return {"movement": movement_payload(db, row)}


@router.delete(
    "/accounts/{account_id}/movements/{movement_id}",
    summary="Eliminar un movimiento si el libro sigue siendo válido",
)
def delete_movement(
    account_id: int,
    movement_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    row = _movement_or_404(db, account, movement_id)
    deleted_type = row.movement_type
    deleted_date = row.movement_date
    db.delete(row)
    db.flush()
    movements, instruments = ledger_for(db, account)
    try:
        replay(
            base_currency=account.base_currency,
            cost_method=account.cost_method,
            instruments=instruments,
            movements=movements,
            allow_negative_cash=account.allow_negative_cash,
            allow_short=account.allow_short,
        )
    except LedgerError as exc:
        raise ApiError(
            422,
            "movement_required_by_later_operations",
            f"No se puede eliminar: {exc}",
        ) from exc
    db.add(
        AuditEvent(
            user_id=user.id,
            action="real_movement.deleted",
            subject=f"{account.id}:{movement_id}",
            meta={"type": deleted_type, "date": deleted_date.isoformat()},
        )
    )
    return {"ok": True, "deleted": movement_id}


@router.get("/overview", summary="Consolidado por moneda base y distribución")
def real_overview(
    as_of: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return overview(db, user.id, as_of=as_of)


@router.get("/performance", summary="Rentabilidad de todas las cuentas")
def real_performance(
    as_of: Optional[date] = Query(default=None),
    twr: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    accounts = (
        db.execute(
            select(RealAccount)
            .where(RealAccount.user_id == user.id, RealAccount.status != "archived")
            .order_by(RealAccount.id)
        )
        .scalars()
        .all()
    )
    return {
        "as_of": (as_of or date.today()).isoformat(),
        "items": [
            {
                "account_id": account.id,
                "name": account.name,
                "base_currency": account.base_currency,
                **{
                    key: value
                    for key, value in account_summary(
                        db, account, as_of=as_of, include_twr=twr
                    ).items()
                    if key
                    in {
                        "total_value_base",
                        "net_contributions_base",
                        "net_gain_base",
                        "net_return_pct",
                        "xirr_pct",
                        "xirr_available",
                        "twr_pct",
                        "twr_available",
                        "twr_reason",
                        "realized_base",
                        "unrealized_base",
                        "dividends_base",
                        "complete",
                    }
                },
            }
            for account in accounts
        ],
    }
