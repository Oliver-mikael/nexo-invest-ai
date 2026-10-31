"""Dependencias compartidas: sesión, usuario autenticado y límite de peticiones."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import SessionToken, User
from app.security import hash_token, limiter_for

bearer_scheme = HTTPBearer(auto_error=False)


def client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "desconocido"


def _active_token(
    credentials: Optional[HTTPAuthorizationCredentials],
    db: Session,
) -> SessionToken:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "unauthorized", "Se requiere una sesión válida.")
    token_hash = hash_token(credentials.credentials)
    row = db.execute(
        select(SessionToken).where(SessionToken.token_hash == token_hash)
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(401, "unauthorized", "La sesión no existe o fue revocada.")
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        raise ApiError(401, "session_expired", "La sesión ha caducado. Vuelve a entrar.")
    return row


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = _active_token(credentials, db)
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise ApiError(403, "forbidden", "La cuenta no está activa.")
    request.state.user_id = user.id
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise ApiError(403, "forbidden", "Esta operación requiere permisos de administración.")
    return user


def rate_limit(scope: str, limit: Optional[int] = None) -> Callable[[Request], None]:
    """Dependencia de límite por IP y ruta lógica."""

    def _dependency(request: Request) -> None:
        settings = request.app.state.settings
        max_requests = limit or settings.rate_limit_per_minute
        allowed, retry_after = limiter_for(max_requests).check(f"{scope}:{client_key(request)}")
        if not allowed:
            raise ApiError(
                429,
                "rate_limited",
                "Demasiadas peticiones. Inténtalo de nuevo en unos segundos.",
                {"retry_after_seconds": round(retry_after, 1)},
            )

    return _dependency
