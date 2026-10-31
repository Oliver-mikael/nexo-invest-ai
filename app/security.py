"""Primitivas de seguridad: contraseñas, sesiones y límite de peticiones.

Decisiones:

- Contraseñas con PBKDF2-HMAC-SHA256 y sal aleatoria de 16 bytes, guardadas como
  `pbkdf2_sha256$iteraciones$sal$hash`. Nunca se guarda la contraseña en claro.
- Sesiones con token opaco aleatorio (256 bits). En la base de datos solo se guarda
  su SHA-256, de modo que un volcado de la tabla no permite reutilizar sesiones.
- Comparaciones en tiempo constante (`hmac.compare_digest`).
- El límite de peticiones es en memoria y por proceso: sirve para un despliegue de
  una instancia; con varias instancias debe moverse a Redis (documentado en
  `docs/PLATFORM.md`).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

PBKDF2_ITERATIONS = 260_000
PBKDF2_PREFIX = "pbkdf2_sha256"
MIN_PASSWORD_LENGTH = 10


class PasswordError(ValueError):
    """La contraseña no cumple la política mínima."""


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordError(
            f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres"
        )
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "$".join(
        [PBKDF2_PREFIX, str(PBKDF2_ITERATIONS), salt.hex(), digest.hex()]
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        prefix, iterations_raw, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if prefix != PBKDF2_PREFIX:
        return False
    try:
        iterations = int(iterations_raw)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RateLimiter:
    """Ventana deslizante por clave (usuario, IP o usuario:acción)."""

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = max(1, limit)
        self.window = window_seconds
        self._events: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, *, cost: int = 1) -> Tuple[bool, float]:
        """Devuelve (permitido, segundos_de_espera)."""
        now = time.monotonic()
        with self._lock:
            bucket = self._events.setdefault(key, deque())
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) + cost > self.limit:
                retry_after = self.window - (now - bucket[0]) if bucket else self.window
                return False, max(0.0, retry_after)
            for _ in range(cost):
                bucket.append(now)
            return True, 0.0

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


_limiter: Optional[RateLimiter] = None
_hourly: Optional[RateLimiter] = None


def limiter_for(limit: int) -> RateLimiter:
    global _limiter
    if _limiter is None or _limiter.limit != max(1, limit):
        _limiter = RateLimiter(limit)
    return _limiter


def hourly_limiter(limit: int) -> RateLimiter:
    """Ventana de una hora, para cupos de trabajos (no de peticiones sueltas)."""
    global _hourly
    if _hourly is None or _hourly.limit != max(1, limit) or _hourly.window != 3600.0:
        _hourly = RateLimiter(limit, window_seconds=3600.0)
    return _hourly


def reset_rate_limiter() -> None:
    global _limiter, _hourly
    _limiter = None
    _hourly = None
