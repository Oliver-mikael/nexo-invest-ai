"""Ciclo de vida de la sesión: emisión, revocación y concurrencia.

Estas pruebas fijan las invariantes que provocaban la intermitencia observada en
las pruebas de navegador:

- el token sirve en la petición inmediatamente posterior a emitirlo;
- cuando `POST /auth/logout` responde 200, la revocación ya está confirmada;
- cerrar sesión en un dispositivo no invalida los demás.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.platform.conftest import auth_headers, register


def test_token_is_usable_immediately_after_issue(client: TestClient):
    """Registro y acceso: el token vale sin esperar a ningún cierre de sesión de BD."""
    for index in range(5):
        created = register(client, email=f"inmediato-{index}@nexo.invalid")
        headers = auth_headers(created["access_token"])
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

        login = client.post(
            "/api/v1/auth/login",
            json={"email": f"inmediato-{index}@nexo.invalid", "password": "clave-segura-123"},
        )
        assert login.status_code == 200, login.text
        login_headers = auth_headers(login.json()["access_token"])
        assert client.get("/api/v1/auth/me", headers=login_headers).status_code == 200


def test_logout_revokes_before_responding(client: TestClient):
    created = register(client, email="revocacion@nexo.invalid")
    headers = auth_headers(created["access_token"])

    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200

    # Inmediatamente después del 200 el token ya no existe en la base de datos.
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert client.get("/api/v1/portfolios", headers=headers).status_code == 401


def test_logout_is_idempotent_and_does_not_leak(client: TestClient):
    created = register(client, email="idempotente@nexo.invalid")
    headers = auth_headers(created["access_token"])

    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    # El segundo intento no puede autenticarse: la sesión ya no existe.
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 401
    assert client.post("/api/v1/auth/logout").status_code == 401


def test_logout_only_closes_the_current_device(client: TestClient):
    register(client, email="dos-dispositivos@nexo.invalid")
    first = client.post(
        "/api/v1/auth/login",
        json={"email": "dos-dispositivos@nexo.invalid", "password": "clave-segura-123"},
    ).json()["access_token"]
    second = client.post(
        "/api/v1/auth/login",
        json={"email": "dos-dispositivos@nexo.invalid", "password": "clave-segura-123"},
    ).json()["access_token"]

    assert client.post("/api/v1/auth/logout", headers=auth_headers(first)).status_code == 200

    assert client.get("/api/v1/auth/me", headers=auth_headers(first)).status_code == 401
    assert client.get("/api/v1/auth/me", headers=auth_headers(second)).status_code == 200

    # Quedan la sesión del registro y la del segundo acceso; la del primero no.
    sessions = client.get("/api/v1/auth/sessions", headers=auth_headers(second)).json()
    assert sessions["total"] == 2


def test_revoked_token_cannot_be_reused_for_writes(client: TestClient):
    created = register(client, email="escritura@nexo.invalid")
    headers = auth_headers(created["access_token"])

    assert (
        client.post(
            "/api/v1/portfolios",
            headers=headers,
            json={"name": "Antes", "starting_cash": 10000, "benchmark": "SPY"},
        ).status_code
        == 201
    )

    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200

    rejected = client.post(
        "/api/v1/portfolios",
        headers=headers,
        json={"name": "Después", "starting_cash": 10000, "benchmark": "SPY"},
    )
    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "unauthorized"
