"""Documentos privados y OCR local con confirmación humana.

Antes de registrar un movimiento desde una fotografía, el usuario debe revisar
los campos propuestos. El documento se guarda fuera del directorio estático y
solo su propietario puede consultarlo, descargarlo o eliminarlo.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_db
from app.deps import get_current_user, rate_limit
from app.errors import ApiError
from app.models import AuditEvent, Document, RealAccount, RealMovement, User, utcnow
from app.schemas import DocumentConfirm
from app.services.ocr import OcrUnavailable, extract
from app.services.real_movements import create_movement

router = APIRouter(prefix="/real/documents", tags=["documentos"])

ALLOWED = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}


def _matches_signature(content: bytes, content_type: str) -> bool:
    """Comprueba la firma real del archivo, no solo el tipo declarado por el cliente."""

    if content_type == "application/pdf":
        return content.startswith(b"%PDF")
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    return False


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _document_or_404(db: Session, user: User, document_id: int) -> Document:
    row = db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "El documento no existe.")
    return row


def _account_or_404(db: Session, user: User, account_id: int) -> RealAccount:
    account = db.execute(
        select(RealAccount).where(
            RealAccount.id == account_id, RealAccount.user_id == user.id
        )
    ).scalar_one_or_none()
    if account is None:
        raise ApiError(404, "not_found", "La cuenta real no existe.")
    return account


def _path(settings: Settings, storage_key: str) -> Path:
    root = Path(settings.documents_dir).resolve()
    candidate = (root / storage_key).resolve()
    if root not in candidate.parents:
        raise ApiError(400, "invalid_path", "Ruta de documento no válida.")
    return candidate


def _payload(row: Document) -> Dict[str, Any]:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "filename": row.filename,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
        "status": row.status,
        "extraction": row.extraction or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.post(
    "",
    status_code=201,
    summary="Subir un documento privado",
    dependencies=[Depends(rate_limit("document-upload", 30))],
)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    account_id: Optional[int] = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    settings = _settings(request)
    if account_id is not None:
        _account_or_404(db, user, account_id)
    content_type = (file.content_type or "").lower().split(";")[0]
    if content_type not in ALLOWED:
        raise ApiError(
            415,
            "unsupported_document",
            "Solo se admiten imágenes JPEG/PNG/WebP o PDF.",
        )
    content = await file.read()
    if not content:
        raise ApiError(422, "empty_file", "El documento está vacío.")
    if len(content) > settings.max_upload_bytes:
        raise ApiError(
            413,
            "file_too_large",
            f"El documento supera el límite de {settings.max_upload_bytes // (1024 * 1024)} MB.",
        )
    if not _matches_signature(content, content_type):
        raise ApiError(
            415,
            "content_type_mismatch",
            "El contenido del archivo no coincide con el tipo declarado.",
        )
    suffix = ALLOWED[content_type]
    original = Path(file.filename or f"documento{suffix}")
    storage_key = f"{user.id}/{uuid.uuid4().hex}{suffix}"
    target = _path(settings, storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass
    target.write_bytes(content)
    row = Document(
        user_id=user.id,
        account_id=account_id,
        filename=original.name[:255],
        content_type=content_type,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        storage_key=storage_key,
        status="uploaded",
        extraction={},
    )
    db.add(row)
    db.flush()
    db.add(
        AuditEvent(
            user_id=user.id,
            action="document.uploaded",
            subject=str(row.id),
            meta={"content_type": content_type, "size": len(content), "sha256": row.sha256},
        )
    )
    return _payload(row)


@router.get("", summary="Listar documentos del usuario")
def list_documents(
    account_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    query = select(Document).where(Document.user_id == user.id)
    if account_id is not None:
        _account_or_404(db, user, account_id)
        query = query.where(Document.account_id == account_id)
    rows = (
        db.execute(query.order_by(Document.created_at.desc()).limit(100))
        .scalars()
        .all()
    )
    return {"items": [_payload(row) for row in rows], "total": len(rows)}


@router.get("/{document_id}", summary="Metadatos y extracción de un documento")
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return _payload(_document_or_404(db, user, document_id))


@router.get("/{document_id}/file", summary="Descargar el documento original")
def download_document(
    request: Request,
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _document_or_404(db, user, document_id)
    path = _path(_settings(request), row.storage_key)
    if not path.is_file():
        raise ApiError(410, "file_missing", "El archivo ya no está disponible.")
    return FileResponse(path, media_type=row.content_type, filename=row.filename)


@router.post(
    "/{document_id}/extract",
    summary="Extraer campos con OCR local (no registra movimientos)",
    dependencies=[Depends(rate_limit("document-ocr", 20))],
)
def extract_document(
    request: Request,
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    row = _document_or_404(db, user, document_id)
    path = _path(_settings(request), row.storage_key)
    if not path.is_file():
        raise ApiError(410, "file_missing", "El archivo ya no está disponible.")
    try:
        result = extract(path, row.content_type)
    except OcrUnavailable as exc:
        raise ApiError(503, "ocr_unavailable", str(exc)) from exc
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            422, "extraction_failed", "No se pudo extraer el contenido del documento."
        ) from exc
    row.extraction = result.as_dict()
    row.status = "extracted"
    row.updated_at = utcnow()
    db.add(
        AuditEvent(
            user_id=user.id,
            action="document.extracted",
            subject=str(row.id),
            meta={"engine": result.engine, "fields": sorted(result.fields)},
        )
    )
    return {
        "document_id": row.id,
        "status": row.status,
        "extraction": row.extraction,
    }


@router.post(
    "/{document_id}/confirm",
    status_code=201,
    summary="Confirmar la revisión humana y registrar el movimiento",
)
def confirm_document(
    document_id: int,
    payload: DocumentConfirm,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    row = _document_or_404(db, user, document_id)
    account = _account_or_404(db, user, payload.account_id)
    if row.account_id is not None and row.account_id != account.id:
        raise ApiError(
            422,
            "document_account_mismatch",
            "El documento está vinculado a otra cuenta.",
        )
    if row.status == "confirmed":
        raise ApiError(
            409, "document_already_confirmed", "Este documento ya generó un movimiento."
        )
    movement = create_movement(
        db,
        account,
        payload.movement,
        source="ocr",
        document_id=row.id,
    )
    row.account_id = account.id
    row.status = "confirmed"
    row.extraction = {
        **(row.extraction or {}),
        "confirmed_movement_id": movement.id,
        "confirmed_at": utcnow().isoformat(),
    }
    db.add(
        AuditEvent(
            user_id=user.id,
            action="document.confirmed",
            subject=f"{row.id}:{movement.id}",
            meta={"account_id": account.id, "type": movement.movement_type},
        )
    )
    from app.services.real_movements import movement_payload

    return {
        "document_id": row.id,
        "status": row.status,
        "movement": movement_payload(db, movement),
    }


@router.delete("/{document_id}", summary="Eliminar un documento no vinculado")
def delete_document(
    request: Request,
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    row = _document_or_404(db, user, document_id)
    linked = db.execute(
        select(func.count(RealMovement.id)).where(RealMovement.document_id == row.id)
    ).scalar_one()
    if linked:
        raise ApiError(
            409,
            "document_linked",
            "El documento respalda un movimiento registrado y no se puede eliminar.",
        )
    path = _path(_settings(request), row.storage_key)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    db.delete(row)
    db.add(
        AuditEvent(
            user_id=user.id,
            action="document.deleted",
            subject=str(document_id),
            meta={},
        )
    )
    return {"ok": True, "deleted": document_id}
