"""Identidad de red del cliente: proxies de confianza y X-Forwarded-For.

El objetivo es que un cliente directo no pueda elegir la identidad con la que se
le aplican los límites de intentos. Sin `NEXO_TRUSTED_PROXIES`, la cabecera se
ignora; con proxies declarados, solo se cree el salto que ellos añaden.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Optional, Tuple

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import Settings
from app.deps import client_key
from app.main import create_app
from app.security import reset_rate_limiter


def make_request(
    peer: Optional[str],
    headers: Iterable[Tuple[str, str]] = (),
    trusted: Iterable[str] = (),
) -> Request:
    settings = dataclasses.replace(Settings(), trusted_proxies=list(trusted))
    scope: Dict[str, Any] = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers],
        "client": (peer, 4321) if peer else None,
        "server": ("testserver", 80),
        "app": SimpleNamespace(state=SimpleNamespace(settings=settings)),
    }
    return Request(scope)


# -- cliente directo ----------------------------------------------------------


def test_direct_client_ignores_forwarded_header():
    """Sin proxies declarados, la cabecera no cambia la identidad."""
    request = make_request("198.51.100.7", [("X-Forwarded-For", "203.0.113.9")])
    assert client_key(request) == "198.51.100.7"


def test_missing_header_uses_connection_ip():
    assert client_key(make_request("198.51.100.7")) == "198.51.100.7"


def test_invalid_connection_address_is_reported_as_unknown():
    """Un transporte sin IP utilizable (o un UNIX socket) no inventa identidad."""
    assert client_key(make_request(None)) == "desconocido"
    assert client_key(make_request("testclient")) == "desconocido"


def test_ipv4_mapped_peer_is_normalized():
    request = make_request("::ffff:198.51.100.7")
    assert client_key(request) == "198.51.100.7"


# -- proxies de confianza -----------------------------------------------------


def test_trusted_proxy_forwards_real_client():
    request = make_request(
        "10.0.0.5",
        [("X-Forwarded-For", "203.0.113.9")],
        trusted=["10.0.0.0/8"],
    )
    assert client_key(request) == "203.0.113.9"


def test_untrusted_peer_cannot_forward():
    """Un cliente que no es proxy declarado no puede imponer su propia IP."""
    request = make_request(
        "198.51.100.7",
        [("X-Forwarded-For", "203.0.113.9")],
        trusted=["10.0.0.0/8"],
    )
    assert client_key(request) == "198.51.100.7"


def test_chain_is_walked_from_the_right_skipping_trusted_hops():
    request = make_request(
        "10.0.0.5",
        [("X-Forwarded-For", "203.0.113.9, 10.1.2.3, 10.0.0.5")],
        trusted=["10.0.0.0/8"],
    )
    assert client_key(request) == "203.0.113.9"


def test_leftmost_forged_entry_is_not_used_when_chain_has_untrusted_hop():
    """El cliente puede añadir entradas a la izquierda: no se le cree."""
    request = make_request(
        "10.0.0.5",
        [("X-Forwarded-For", "1.1.1.1, 203.0.113.9")],
        trusted=["10.0.0.0/8"],
    )
    assert client_key(request) == "203.0.113.9"


def test_chain_of_only_trusted_hops_falls_back_to_leftmost():
    request = make_request(
        "10.0.0.5",
        [("X-Forwarded-For", "10.5.5.5, 10.1.2.3")],
        trusted=["10.0.0.0/8"],
    )
    assert client_key(request) == "10.5.5.5"


# -- entradas anómalas --------------------------------------------------------


@pytest.mark.parametrize(
    "header",
    [
        "no-es-una-ip",
        "203.0.113.9, basura",
        "999.1.1.1",
        "",
        " , , ",
        "203.0.113.9, " + "10.1.1.1, " * 12,
    ],
)
def test_malformed_header_falls_back_to_connection_ip(header: str):
    request = make_request("10.0.0.5", [("X-Forwarded-For", header)], trusted=["10.0.0.0/8"])
    assert client_key(request) == "10.0.0.5"


def test_ports_are_stripped_from_hops():
    request = make_request(
        "10.0.0.5",
        [("X-Forwarded-For", "203.0.113.9:5555, [2001:db8::1]:443")],
        trusted=["10.0.0.0/8"],
    )
    assert client_key(request) == "2001:db8::1"


def test_ipv6_proxy_is_matched_by_network():
    request = make_request(
        "2001:db8:1::5",
        [("X-Forwarded-For", "2606:4700::1111")],
        trusted=["2001:db8:1::/48"],
    )
    assert client_key(request) == "2606:4700::1111"


def test_invalid_trusted_proxy_entry_grants_no_trust():
    request = make_request(
        "10.0.0.5",
        [("X-Forwarded-For", "203.0.113.9")],
        trusted=["10.0.0.0/no-es-red"],
    )
    assert client_key(request) == "10.0.0.5"


# -- extremo a extremo: límite de intentos -----------------------------------


@pytest.fixture()
def direct_client(settings: Settings, engine, orchestrator, prices):
    """Cliente HTTP directo con IP de conexión real y sin proxies declarados."""
    reset_rate_limiter()
    guarded = dataclasses.replace(settings, trusted_proxies=[])
    app = create_app(
        guarded,
        engine=engine,
        orchestrator=orchestrator,
        price_provider=prices,
        start_workers=True,
    )
    with TestClient(app, client=("198.51.100.7", 50123)) as test_client:
        yield test_client


@pytest.fixture()
def proxied_client(settings: Settings, engine, orchestrator, prices):
    """Cliente que llega desde un proxy declarado en `trusted_proxies`."""
    reset_rate_limiter()
    guarded = dataclasses.replace(settings, trusted_proxies=["10.0.0.0/8"])
    app = create_app(
        guarded,
        engine=engine,
        orchestrator=orchestrator,
        price_provider=prices,
        start_workers=True,
    )
    with TestClient(app, client=("10.0.0.5", 50123)) as test_client:
        yield test_client


def _register(client: TestClient, email: str, forwarded: Optional[str] = None):
    headers = {"X-Forwarded-For": forwarded} if forwarded else {}
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "clave-segura-123", "display_name": "Prueba"},
        headers=headers,
    )


def test_spoofed_header_cannot_evade_registration_limit(direct_client: TestClient):
    """Diez registros con IP falsa distinta agotan el límite de la IP real."""
    for index in range(10):
        response = _register(direct_client, f"evasion-{index}@nexo.invalid", f"203.0.113.{index}")
        assert response.status_code == 201, response.text

    blocked = _register(direct_client, "evasion-final@nexo.invalid", "203.0.113.200")
    assert blocked.status_code == 429, blocked.text
    assert blocked.json()["error"]["code"] == "rate_limited"


def test_trusted_proxy_separates_real_clients(proxied_client: TestClient):
    """Detrás de un proxy declarado, cada IP reenviada tiene su propio cupo."""
    for index in range(10):
        response = _register(proxied_client, f"proxy-a-{index}@nexo.invalid", "203.0.113.10")
        assert response.status_code == 201, response.text

    assert _register(proxied_client, "proxy-a-final@nexo.invalid", "203.0.113.10").status_code == 429
    assert _register(proxied_client, "proxy-b-0@nexo.invalid", "203.0.113.11").status_code == 201


def test_untrusted_forwarded_header_from_proxy_is_still_walked(proxied_client: TestClient):
    """El proxy añade la IP real al final: una entrada falsa a la izquierda no evade."""
    for index in range(9):
        assert _register(proxied_client, f"chain-{index}@nexo.invalid", "203.0.113.20").status_code == 201

    # Noveno intento agotado; el décimo con otra IP falsa a la izquierda sigue
    # contando para la IP real que añadió el proxy.
    assert _register(proxied_client, "chain-9@nexo.invalid", "203.0.113.20").status_code == 201
    spoofed = _register(proxied_client, "chain-10@nexo.invalid", "1.1.1.1, 203.0.113.20")
    assert spoofed.status_code == 429
