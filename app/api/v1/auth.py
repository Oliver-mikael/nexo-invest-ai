"""Registro, acceso, cierre de sesión y perfil."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import bearer_scheme, get_current_user, rate_limit
from app.errors import ApiError
from app.models import AuditEvent, SessionToken, User, UserSettings, utcnow
from app.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.security import (
    PasswordError,
    hash_password,
    hash_token,
    new_session_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["autenticación"])

# Hash de relleno: mantiene un coste similar cuando el correo no existe, para no
# revelar por tiempo de respuesta qué cuentas están registradas.
_DUMMY_HASH = hash_password("nexo-dummy-password-value")


def _issue_token(
    db: Session, user: User, *, user_agent: str, ttl_hours: int
) -> TokenResponse:
    token = new_session_token()
    expires = utcnow() + timedelta(hours=ttl_hours)
    db.add(
        SessionToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=expires,
            user_agent=user_agent[:255],
        )
    )
    db.flush()
    return TokenResponse(
        access_token=token,
        expires_at=expires,
        user=UserOut.model_validate(user),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=201,
    dependencies=[Depends(rate_limit("auth-register", 10))],
    summary="Crear una cuenta",
)
def register(
    payload: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
    settings = request.app.state.settings
    if not settings.allow_registration:
        raise ApiError(403, "registration_disabled", "El registro está desactivado.")
    existing = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if existing is not None:
        raise ApiError(409, "email_taken", "Ya existe una cuenta con ese correo.")
    try:
        password_hash = hash_password(payload.password)
    except PasswordError as exc:
        raise ApiError(422, "weak_password", str(exc)) from exc
    user = User(
        email=payload.email,
        password_hash=password_hash,
        display_name=payload.display_name.strip() or payload.email.split("@")[0],
    )
    db.add(user)
    db.flush()
    db.add(
        UserSettings(
            user_id=user.id,
            monthly_budget_usd=settings.monthly_budget_usd,
            ai_profile=settings.ai_default_profile,
        )
    )
    db.add(
        AuditEvent(
            user_id=user.id,
            action="auth.register",
            subject=user.email,
            meta={},
            ip=request.client.host if request.client else "",
        )
    )
    return _issue_token(
        db,
        user,
        user_agent=request.headers.get("user-agent", ""),
        ttl_hours=settings.session_ttl_hours,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("auth-login", 12))],
    summary="Iniciar sesión",
)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
    settings = request.app.state.settings
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    stored = user.password_hash if user is not None else _DUMMY_HASH
    valid = verify_password(payload.password, stored)
    if user is None or not valid:
        db.add(
            AuditEvent(
                user_id=None,
                action="auth.login_failed",
                subject=payload.email[:160],
                meta={},
                ip=request.client.host if request.client else "",
            )
        )
        db.commit()
        raise ApiError(401, "invalid_credentials", "Correo o contraseña incorrectos.")
    if not user.is_active:
        raise ApiError(403, "forbidden", "La cuenta no está activa.")
    db.add(
        AuditEvent(
            user_id=user.id,
            action="auth.login",
            subject=user.email,
            meta={},
            ip=request.client.host if request.client else "",
        )
    )
    return _issue_token(
        db,
        user,
        user_agent=request.headers.get("user-agent", ""),
        ttl_hours=settings.session_ttl_hours,
    )


@router.post("/logout", summary="Cerrar la sesión actual")
def logout(
    credentials: Optional[object] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    raw = getattr(credentials, "credentials", None)
    if raw:
        row = db.execute(
            select(SessionToken).where(SessionToken.token_hash == hash_token(raw))
        ).scalar_one_or_none()
        if row is not None:
            db.delete(row)
    return {"ok": True, "user_id": user.id}


@router.get("/me", response_model=UserOut, summary="Perfil de la cuenta")
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.get("/sessions", summary="Sesiones abiertas de la cuenta")
def sessions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    rows = (
        db.execute(
            select(SessionToken)
            .where(SessionToken.user_id == user.id)
            .order_by(SessionToken.created_at.desc())
        )
        .scalars()
        .all()
    )
    now = datetime.now(timezone.utc)
    items = []
    for row in rows:
        expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
        items.append(
            {
                "created_at": row.created_at.isoformat(),
                "expires_at": expires.isoformat(),
                "active": expires > now,
                "user_agent": row.user_agent,
            }
        )
    return {"items": items, "total": len(items)}
