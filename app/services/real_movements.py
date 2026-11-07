"""Alta y validación de movimientos reales.

Toda operación pasa por el mismo camino, venga de un formulario, un CSV o una
fotografía: se normaliza, se reproduce el libro completo con el candidato y solo
se guarda si el resultado es contablemente válido. La confirmación humana es
obligatoria en importación y OCR: esas rutas no guardan movimientos por sí solas.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Instrument, Market, RealAccount, RealMovement, utcnow
from app.schemas import RealMovementCreate
from app.services.accounting import (
    InstrumentInfo,
    LedgerError,
    LedgerMovement,
    dec,
    replay,
)
from app.services.real_portfolio import instrument_map, ledger_movements

CASH_TYPES = {"deposit", "withdrawal", "dividend", "fee", "tax", "adjustment"}
PURE_CASH_TYPES = {"deposit", "withdrawal", "fee", "tax", "adjustment"}
INSTRUMENT_TYPES = {"buy", "sell", "dividend", "split", "transfer_in", "transfer_out"}


def instrument_or_404(session: Session, uid: str) -> Instrument:
    instrument = session.execute(
        select(Instrument).where(Instrument.uid == uid)
    ).scalar_one_or_none()
    if instrument is None:
        raise ApiError(404, "instrument_not_found", "El instrumento no existe.")
    return instrument


def instrument_payload(session: Session, instrument: Instrument) -> Dict[str, Any]:
    market = session.get(Market, instrument.market_id)
    return {
        "uid": instrument.uid,
        "symbol": instrument.symbol,
        "name": instrument.name,
        "market": market.code if market else "",
        "market_name": market.name if market else "",
        "country_code": instrument.country_code,
        "currency": instrument.currency,
        "instrument_type": instrument.instrument_type,
        "isin": instrument.isin,
        "cik": instrument.cik,
        "status": instrument.status,
    }


def canonical_dedupe_key(
    *,
    movement_type: str,
    movement_date: date,
    instrument_uid: Optional[str],
    quantity: Decimal,
    price: Decimal,
    amount: Decimal,
    fee: Decimal,
    tax: Decimal,
    currency: str,
    external_id: Optional[str] = None,
) -> str:
    """Clave estable para no registrar dos veces el mismo hecho.

    Un `external_id` del bróker manda; si no existe, se usa una huella de los
    campos económicos. La comisión y el impuesto forman parte de la huella para
    no fusionar dos operaciones distintas del mismo día.
    """

    if external_id:
        raw = f"external:{external_id.strip()}"
    else:
        raw = "|".join(
            [
                movement_type,
                movement_date.isoformat(),
                instrument_uid or "",
                str(quantity.normalize()),
                str(price.normalize()),
                str(amount.normalize()),
                str(fee.normalize()),
                str(tax.normalize()),
                currency.upper(),
            ]
        )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize(
    payload: RealMovementCreate,
    account: RealAccount,
    instrument: Optional[Instrument],
) -> Dict[str, Any]:
    kind = payload.movement_type
    base = account.base_currency.upper()
    currency = (payload.currency or (instrument.currency if instrument else base)).upper()
    quantity = dec(payload.quantity)
    price = dec(payload.price)
    amount = dec(payload.amount)
    fee = dec(payload.fee)
    tax = dec(payload.tax)

    if kind in INSTRUMENT_TYPES and instrument is None:
        raise ApiError(
            422,
            "instrument_required",
            f"El movimiento «{kind}» requiere instrumento.",
        )
    if kind in PURE_CASH_TYPES and instrument is not None:
        raise ApiError(
            422,
            "instrument_not_allowed",
            f"El movimiento «{kind}» no admite instrumento.",
        )
    if instrument is not None and currency != instrument.currency.upper():
        raise ApiError(
            422,
            "currency_mismatch",
            "La moneda del movimiento debe coincidir con la del instrumento.",
        )
    if kind != "split" and quantity < 0:
        raise ApiError(422, "invalid_quantity", "La cantidad no puede ser negativa.")
    if kind in {"buy", "sell"} and (quantity <= 0 or price < 0):
        raise ApiError(422, "invalid_quantity", "Compra o venta requieren cantidad positiva.")
    if kind in {"deposit", "withdrawal", "dividend", "fee", "tax"} and amount <= 0:
        raise ApiError(422, "invalid_amount", f"«{kind}» requiere importe positivo.")
    if kind in {"deposit", "withdrawal", "split", "transfer_in", "transfer_out"} and (
        fee or tax
    ):
        raise ApiError(
            422,
            "costs_not_allowed",
            "Este tipo de movimiento no admite comisión ni impuesto; regístralos como movimientos separados.",
        )
    if kind == "split" and quantity == 0:
        raise ApiError(422, "invalid_split", "El split requiere una variación distinta de cero.")
    if kind == "adjustment" and amount == 0 and fee == 0 and tax == 0:
        raise ApiError(422, "invalid_adjustment", "El ajuste requiere un importe distinto de cero.")
    if kind in {"transfer_in", "transfer_out"}:
        if instrument is None and amount <= 0:
            raise ApiError(422, "invalid_transfer", "El traspaso de efectivo requiere importe.")
        if instrument is not None:
            if quantity <= 0:
                raise ApiError(
                    422, "invalid_transfer", "El traspaso de valores requiere cantidad positiva."
                )
            if payload.transfer_cost_basis is None:
                raise ApiError(
                    422,
                    "transfer_basis_required",
                    "El traspaso de valores requiere el coste de adquisición en moneda base.",
                )
    if currency == base:
        fx_rate = Decimal("1")
        fx_date = payload.movement_date
        fx_source = "identity"
    else:
        if payload.fx_rate is None or dec(payload.fx_rate) <= 0:
            raise ApiError(
                422,
                "fx_rate_required",
                "Una operación en moneda distinta de la base requiere tipo de cambio histórico.",
            )
        if not payload.fx_source.strip():
            raise ApiError(
                422,
                "fx_source_required",
                "Indica la fuente del tipo de cambio aplicado.",
            )
        fx_rate = dec(payload.fx_rate)
        fx_date = payload.fx_date or payload.movement_date
        fx_source = payload.fx_source.strip()

    transfer_group = payload.transfer_group
    if kind in {"transfer_in", "transfer_out"} and not transfer_group:
        transfer_group = str(uuid.uuid4())

    dedupe = canonical_dedupe_key(
        movement_type=kind,
        movement_date=payload.movement_date,
        instrument_uid=instrument.uid if instrument else None,
        quantity=quantity,
        price=price,
        amount=amount,
        fee=fee,
        tax=tax,
        currency=currency,
        external_id=payload.external_id,
    )
    return {
        "movement_type": kind,
        "movement_date": payload.movement_date,
        "instrument": instrument,
        "quantity": quantity,
        "price": price,
        "amount": amount,
        "fee": fee,
        "tax": tax,
        "currency": currency,
        "fx_rate": fx_rate,
        "fx_date": fx_date,
        "fx_source": fx_source,
        "transfer_group": transfer_group,
        "transfer_cost_basis": (
            None
            if payload.transfer_cost_basis is None
            else dec(payload.transfer_cost_basis)
        ),
        "notes": payload.notes.strip(),
        "dedupe_key": dedupe,
        "external_id": payload.external_id,
    }


def _info_for(session: Session, instrument: Instrument) -> InstrumentInfo:
    data = instrument_map(session, [instrument.id])
    return data[instrument.id]


def validate_candidate(
    session: Session,
    account: RealAccount,
    values: Dict[str, Any],
    *,
    exclude_movement_id: Optional[int] = None,
) -> None:
    instrument: Optional[Instrument] = values["instrument"]
    existing_rows = (
        session.execute(
            select(RealMovement)
            .where(RealMovement.account_id == account.id)
            .order_by(RealMovement.movement_date, RealMovement.id)
        )
        .scalars()
        .all()
    )
    existing = [
        row for row in existing_rows if row.id != exclude_movement_id
    ]
    ids = {row.instrument_id for row in existing if row.instrument_id}
    if instrument is not None:
        ids.add(instrument.id)
    instruments = instrument_map(session, ids)
    ledger = [
        LedgerMovement(
            id=row.id,
            kind=row.movement_type,
            date=row.movement_date,
            instrument_id=row.instrument_id,
            currency=row.currency.upper(),
            quantity=dec(row.quantity),
            price=dec(row.price),
            amount=dec(row.amount),
            fee=dec(row.fee),
            tax=dec(row.tax),
            fx_rate=dec(row.fx_rate),
            transfer_group=row.transfer_group,
            transfer_cost_basis=(
                None if row.transfer_cost_basis is None else dec(row.transfer_cost_basis)
            ),
            note=row.notes or "",
        )
        for row in existing
    ]
    ledger.append(
        LedgerMovement(
            id=2_000_000_000,
            kind=values["movement_type"],
            date=values["movement_date"],
            instrument_id=instrument.id if instrument else None,
            currency=values["currency"],
            quantity=values["quantity"],
            price=values["price"],
            amount=values["amount"],
            fee=values["fee"],
            tax=values["tax"],
            fx_rate=values["fx_rate"],
            transfer_group=values["transfer_group"],
            transfer_cost_basis=values["transfer_cost_basis"],
            note=values["notes"],
        )
    )
    try:
        replay(
            base_currency=account.base_currency,
            cost_method=account.cost_method,
            instruments=instruments,
            movements=ledger,
            allow_negative_cash=account.allow_negative_cash,
            allow_short=account.allow_short,
        )
    except LedgerError as exc:
        raise ApiError(422, "invalid_movement", str(exc)) from exc


def create_movement(
    session: Session,
    account: RealAccount,
    payload: RealMovementCreate,
    *,
    source: str = "manual",
    document_id: Optional[int] = None,
    import_batch_id: Optional[int] = None,
) -> RealMovement:
    instrument = (
        instrument_or_404(session, payload.instrument_uid)
        if payload.instrument_uid
        else None
    )
    values = _normalize(payload, account, instrument)
    duplicate = session.execute(
        select(RealMovement).where(
            RealMovement.account_id == account.id,
            RealMovement.dedupe_key == values["dedupe_key"],
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise ApiError(
            409,
            "duplicate_movement",
            "Ese movimiento ya está registrado en la cuenta.",
            {"movement_id": duplicate.id},
        )
    validate_candidate(session, account, values)
    row = RealMovement(
        account_id=account.id,
        instrument_id=instrument.id if instrument else None,
        movement_type=values["movement_type"],
        movement_date=values["movement_date"],
        settlement_date=None,
        quantity=values["quantity"],
        price=values["price"],
        amount=values["amount"],
        fee=values["fee"],
        tax=values["tax"],
        currency=values["currency"],
        fx_rate=values["fx_rate"],
        fx_date=values["fx_date"],
        fx_source=values["fx_source"],
        source=source,
        validation_status="confirmed",
        dedupe_key=values["dedupe_key"],
        transfer_group=values["transfer_group"],
        transfer_cost_basis=values["transfer_cost_basis"],
        document_id=document_id,
        import_batch_id=import_batch_id,
        notes=values["notes"],
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        raise ApiError(
            409,
            "duplicate_movement",
            "Ese movimiento ya está registrado en la cuenta.",
        ) from exc
    return row


def update_movement(
    session: Session,
    account: RealAccount,
    row: RealMovement,
    payload: RealMovementCreate,
) -> RealMovement:
    instrument = (
        instrument_or_404(session, payload.instrument_uid)
        if payload.instrument_uid
        else None
    )
    values = _normalize(payload, account, instrument)
    duplicate = session.execute(
        select(RealMovement).where(
            RealMovement.account_id == account.id,
            RealMovement.dedupe_key == values["dedupe_key"],
            RealMovement.id != row.id,
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise ApiError(409, "duplicate_movement", "Otro movimiento ya usa esos datos.")
    validate_candidate(session, account, values, exclude_movement_id=row.id)
    row.instrument_id = instrument.id if instrument else None
    row.movement_type = values["movement_type"]
    row.movement_date = values["movement_date"]
    row.quantity = values["quantity"]
    row.price = values["price"]
    row.amount = values["amount"]
    row.fee = values["fee"]
    row.tax = values["tax"]
    row.currency = values["currency"]
    row.fx_rate = values["fx_rate"]
    row.fx_date = values["fx_date"]
    row.fx_source = values["fx_source"]
    row.transfer_group = values["transfer_group"]
    row.transfer_cost_basis = values["transfer_cost_basis"]
    row.notes = values["notes"]
    row.dedupe_key = values["dedupe_key"]
    row.updated_at = utcnow()
    return row


def movement_payload(session: Session, row: RealMovement) -> Dict[str, Any]:
    instrument = session.get(Instrument, row.instrument_id) if row.instrument_id else None
    return {
        "id": row.id,
        "movement_type": row.movement_type,
        "movement_date": row.movement_date.isoformat(),
        "settlement_date": row.settlement_date.isoformat() if row.settlement_date else None,
        "instrument_uid": instrument.uid if instrument else None,
        "symbol": instrument.symbol if instrument else None,
        "currency": row.currency,
        "quantity": str(row.quantity),
        "price": str(row.price),
        "amount": str(row.amount),
        "fee": str(row.fee),
        "tax": str(row.tax),
        "fx_rate": str(row.fx_rate),
        "fx_date": row.fx_date.isoformat() if row.fx_date else None,
        "fx_source": row.fx_source,
        "source": row.source,
        "validation_status": row.validation_status,
        "transfer_group": row.transfer_group,
        "transfer_cost_basis": (
            None if row.transfer_cost_basis is None else str(row.transfer_cost_basis)
        ),
        "document_id": row.document_id,
        "import_batch_id": row.import_batch_id,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def ledger_for(session: Session, account: RealAccount) -> Tuple[List[LedgerMovement], Dict[int, InstrumentInfo]]:
    movements = ledger_movements(session, account.id)
    instruments = instrument_map(
        session, {m.instrument_id for m in movements if m.instrument_id}
    )
    return movements, instruments
