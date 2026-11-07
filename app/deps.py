"""Dependencias compartidas: sesión, usuario autenticado y límite de peticiones."""

from __future__ import annotations

import ipaddress
from datetime import datetime, timezone
from functools import lru_cache
from typing import Callable, Optional, Sequence, Tuple, Union

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import SessionToken, User
from app.security import hash_token, limiter_for

bearer_scheme = HTTPBearer(auto_error=False)

IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]
IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]

# Una cadena de proxies más larga que esto no es creíble: se descarta entera.
_MAX_FORWARDED_HOPS = 10


@lru_cache(maxsize=8)
def _trusted_networks(values: Tuple[str, ...]) -> Tuple[IPNetwork, ...]:
    """Redes declaradas como proxies de confianza.

    Una entrada mal escrita se ignora: nunca autoriza nada (fallo cerrado) y no
    impide arrancar el servidor por un error de configuración.
    """
    networks: list[IPNetwork] = []
    for raw in values:
        try:
            networks.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _parse_ip(raw: Optional[str]) -> Optional[IPAddress]:
    """Convierte texto en dirección; admite `ip:puerto` y `[ipv6]:puerto`."""
    if not raw:
        return None
    token = raw.strip().strip('"')
    if not token:
        return None
    if "%" in token:  # zona de interfaz (fe80::1%eth0): no forma parte de la IP
        token = token.split("%", 1)[0]
    if token.startswith("[") and "]" in token:
        token = token[1 : token.index("]")]
    elif token.count(":") == 1:
        host, _, port = token.partition(":")
        if port.isdigit():
            token = host
    try:
        address = ipaddress.ip_address(token)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def _is_trusted(address: IPAddress, networks: Sequence[IPNetwork]) -> bool:
    for network in networks:
        try:
            if address in network:
                return True
        except TypeError:  # familia distinta (IPv4 frente a red IPv6)
            continue
    return False


def client_key(request: Request) -> str:
    """Identidad de red del cliente para límites de peticiones y auditoría.

    Reglas deliberadas:

    1. Sin proxies configurados en `NEXO_TRUSTED_PROXIES`, manda la IP de la
       conexión TCP y `X-Forwarded-For` se ignora por completo: un cliente
       directo no puede elegir su propia identidad ni esquivar un límite.
    2. La cabecera solo se interpreta si la conexión llega desde un proxy
       declarado. Se recorre de derecha a izquierda descartando los saltos de
       confianza, que es el orden en el que los proxies añaden direcciones.
    3. Si algún salto no es una IP válida, la cabecera se descarta entera y se
       usa la IP de la conexión: nunca se propaga texto arbitrario como clave.
    """
    peer = _parse_ip(request.client.host) if request.client else None
    if peer is None:
        return "desconocido"
    settings = getattr(request.app.state, "settings", None)
    networks = _trusted_networks(tuple(getattr(settings, "trusted_proxies", ()) or ()))
    if not networks or not _is_trusted(peer, networks):
        return str(peer)

    header = request.headers.get("x-forwarded-for")
    if not header:
        return str(peer)
    hops = [hop for hop in (chunk.strip() for chunk in header.split(",")) if hop]
    if not hops or len(hops) > _MAX_FORWARDED_HOPS:
        return str(peer)
    chain: list[IPAddress] = []
    for hop in hops:
        address = _parse_ip(hop)
        if address is None:
            return str(peer)
        chain.append(address)
    for address in reversed(chain):
        if not _is_trusted(address, networks):
            return str(address)
    return str(chain[0])


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
