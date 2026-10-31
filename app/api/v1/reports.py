"""Historial de informes y exportaciones."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.errors import ApiError
from app.models import Report, User
from app.services.export import markdown_to_html, report_csv

router = APIRouter(prefix="/reports", tags=["informes"])


def _report_or_404(db: Session, user: User, report_id: int) -> Report:
    report = db.execute(
        select(Report).where(Report.id == report_id, Report.user_id == user.id)
    ).scalar_one_or_none()
    if report is None:
        raise ApiError(404, "not_found", "El informe no existe.")
    return report


@router.get("", summary="Listar informes")
def list_reports(
    kind: Optional[str] = Query(default=None, max_length=20),
    ticker: Optional[str] = Query(default=None, max_length=12),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    statement = select(Report).where(Report.user_id == user.id)
    if kind:
        statement = statement.where(Report.kind == kind)
    if ticker:
        statement = statement.where(Report.ticker == ticker.upper())
    total = db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
    rows = (
        db.execute(
            statement.order_by(Report.created_at.desc()).limit(limit).offset(offset)
        )
        .scalars()
        .all()
    )
    items = [
        {
            "id": row.id,
            "ticker": row.ticker,
            "title": row.title,
            "kind": row.kind,
            "created_at": row.created_at.isoformat(),
            "profile": (row.payload or {}).get("profile"),
            "base_per_share": (row.payload or {}).get("base_per_share"),
        }
        for row in rows
    ]
    return {
        "items": items,
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < int(total),
    }


@router.get("/{report_id}", summary="Contenido de un informe")
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    report = _report_or_404(db, user, report_id)
    payload = report.payload or {}
    return {
        "id": report.id,
        "ticker": report.ticker,
        "title": report.title,
        "kind": report.kind,
        "created_at": report.created_at.isoformat(),
        "markdown": report.markdown,
        "sections": payload.get("sections", []),
        "audit": payload.get("audit", {}),
        "roles": payload.get("roles", []),
        "provenance": payload.get("provenance", {}),
        "metrics": payload.get("metrics", []),
        "scenarios": payload.get("scenarios", []),
        "base_per_share": payload.get("base_per_share"),
        "currency": payload.get("currency"),
    }


@router.get("/{report_id}/export", summary="Exportar el informe")
def export_report(
    report_id: int,
    format: str = Query(default="md", pattern="^(md|csv|html)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    report = _report_or_404(db, user, report_id)
    filename = f"nexo-{report.ticker.lower()}-{report.id}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if format == "md":
        return Response(
            content=report.markdown,
            media_type="text/markdown; charset=utf-8",
            headers=headers,
        )
    if format == "csv":
        return Response(
            content=report_csv(report.payload or {}),
            media_type="text/csv; charset=utf-8",
            headers=headers,
        )
    return Response(
        content=markdown_to_html(report.markdown, title=report.title),
        media_type="text/html; charset=utf-8",
        headers=headers,
    )


@router.delete("/{report_id}", summary="Eliminar un informe propio")
def delete_report(
    report_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    report = _report_or_404(db, user, report_id)
    db.delete(report)
    return {"ok": True, "deleted": report_id}
