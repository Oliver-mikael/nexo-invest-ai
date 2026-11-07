"""Importación de movimientos con vista previa y confirmación explícita."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, rate_limit
from app.errors import ApiError
from app.models import AuditEvent, ImportBatch, RealAccount, User
from app.schemas import ImportConfirm
from app.services.imports import (
    confirm_batch,
    content_hash,
    parse_tabular,
    prepare_rows,
    resolve_mapping,
)

router = APIRouter(prefix="/real/accounts/{account_id}/imports", tags=["importación"])

MAX_IMPORT_BYTES = 5 * 1024 * 1024


def _account_or_404(db: Session, user: User, account_id: int) -> RealAccount:
    account = db.execute(
        select(RealAccount).where(
            RealAccount.id == account_id, RealAccount.user_id == user.id
        )
    ).scalar_one_or_none()
    if account is None:
        raise ApiError(404, "not_found", "La cuenta real no existe.")
    return account


def _batch_or_404(
    db: Session, account: RealAccount, batch_id: int
) -> ImportBatch:
    batch = db.execute(
        select(ImportBatch).where(
            ImportBatch.id == batch_id, ImportBatch.account_id == account.id
        )
    ).scalar_one_or_none()
    if batch is None:
        raise ApiError(404, "not_found", "La previsualización no existe.")
    return batch


def _batch_payload(batch: ImportBatch, *, include_rows: bool, limit: int = 200) -> Dict[str, Any]:
    data = {
        "id": batch.id,
        "account_id": batch.account_id,
        "filename": batch.filename,
        "content_sha256": batch.content_sha256,
        "status": batch.status,
        "mapping": batch.mapping,
        "total_rows": batch.total_rows,
        "valid_rows": batch.valid_rows,
        "duplicate_rows": batch.duplicate_rows,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "confirmed_at": batch.confirmed_at.isoformat() if batch.confirmed_at else None,
    }
    if include_rows:
        data["rows"] = (batch.rows or [])[:limit]
        data["rows_returned"] = len(data["rows"])
    return data


@router.post(
    "/preview",
    status_code=201,
    summary="Subir CSV/XLSX y previsualizar movimientos sin registrarlos",
    dependencies=[Depends(rate_limit("import-preview", 30))],
)
async def preview_import(
    account_id: int,
    file: UploadFile = File(...),
    mapping: str = Form(default=""),
    date_order: str = Form(default="dmy"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    if date_order not in {"dmy", "mdy"}:
        raise ApiError(422, "invalid_date_order", "El orden de fecha debe ser dmy o mdy.")
    content = await file.read()
    if len(content) > MAX_IMPORT_BYTES:
        raise ApiError(413, "file_too_large", "El archivo supera el límite de 5 MB.")
    if not content:
        raise ApiError(422, "empty_file", "El archivo está vacío.")
    headers, records = parse_tabular(file.filename or "", content)
    if len(records) > 2000:
        raise ApiError(
            422,
            "too_many_rows",
            "El archivo supera las 2.000 filas. Divídelo en partes más pequeñas.",
        )
    provided: Optional[Dict[str, str]] = None
    if mapping.strip():
        try:
            parsed = json.loads(mapping)
        except json.JSONDecodeError as exc:
            raise ApiError(422, "invalid_mapping", "El mapeo no es JSON válido.") from exc
        if not isinstance(parsed, dict):
            raise ApiError(422, "invalid_mapping", "El mapeo debe ser un objeto JSON.")
        provided = {str(key): str(value) for key, value in parsed.items()}
    resolved = resolve_mapping(headers, provided)
    prepared = prepare_rows(
        db, account, records, resolved, date_order=date_order
    )
    errors = sum(1 for row in prepared if row["errors"])
    duplicates = sum(1 for row in prepared if row["duplicate"])
    batch = ImportBatch(
        user_id=user.id,
        account_id=account.id,
        filename=(file.filename or "")[:255],
        content_sha256=content_hash(content),
        status="preview",
        mapping={**resolved, "date_order": date_order},
        rows=prepared,
        total_rows=len(prepared),
        valid_rows=len(prepared) - errors - duplicates,
        duplicate_rows=duplicates,
    )
    db.add(batch)
    db.flush()
    db.add(
        AuditEvent(
            user_id=user.id,
            action="import.previewed",
            subject=f"{account.id}:{batch.id}",
            meta={
                "filename": batch.filename,
                "rows": batch.total_rows,
                "errors": errors,
                "duplicates": duplicates,
            },
        )
    )
    payload = _batch_payload(batch, include_rows=True)
    payload.update(
        {
            "headers": headers,
            "mapping": resolved,
            "error_rows": errors,
            "ready_to_confirm": errors == 0,
            "note": (
                "Vista previa: no se ha registrado ningún movimiento. Revisa las filas "
                "y confirma para guardarlas."
            ),
        }
    )
    return payload


@router.get("", summary="Listar previsualizaciones de la cuenta")
def list_batches(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    rows = (
        db.execute(
            select(ImportBatch)
            .where(ImportBatch.account_id == account.id)
            .order_by(ImportBatch.created_at.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    return {"items": [_batch_payload(row, include_rows=False) for row in rows]}


@router.get("/{batch_id}", summary="Detalle de una previsualización")
def get_batch(
    account_id: int,
    batch_id: int,
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    batch = _batch_or_404(db, account, batch_id)
    return _batch_payload(batch, include_rows=True, limit=limit)


@router.post(
    "/{batch_id}/confirm",
    summary="Confirmar la importación y registrar los movimientos válidos",
)
def confirm_import(
    account_id: int,
    batch_id: int,
    payload: ImportConfirm,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    batch = _batch_or_404(db, account, batch_id)
    if batch.status != "preview":
        raise ApiError(
            409,
            "batch_already_confirmed",
            "Esta previsualización ya se confirmó o descartó.",
        )
    result = confirm_batch(
        db,
        account,
        batch,
        rows=payload.rows,
        allow_partial=payload.allow_partial,
    )
    db.add(
        AuditEvent(
            user_id=user.id,
            action="import.confirmed",
            subject=f"{account.id}:{batch.id}",
            meta={
                "created": result["created"],
                "skipped_duplicates": result["skipped_duplicates"],
                "errors": len(result["errors"]),
            },
        )
    )
    return result


@router.delete("/{batch_id}", summary="Descartar una previsualización")
def discard_batch(
    account_id: int,
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    batch = _batch_or_404(db, account, batch_id)
    if batch.status == "confirmed":
        raise ApiError(
            409,
            "batch_already_confirmed",
            "No se puede descartar una importación ya confirmada.",
        )
    batch.status = "discarded"
    return {"ok": True, "status": batch.status}
