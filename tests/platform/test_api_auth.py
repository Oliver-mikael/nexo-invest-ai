"""Registro, acceso, cierre de sesión y aislamiento entre cuentas."""

from __future__ import annotations

from tests.platform.conftest import auth_headers, register


def test_health_and_openapi(client):
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["engine"] == "nexo_invest"

    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/companies/{ticker}/valuation" in paths
    assert "/api/v1/research" in paths


def test_register_login_logout(client):
    data = register(client)
    token = data["access_token"]
    assert data["user"]["email"] == "analista@nexo.invalid"
    assert data["expires_at"]

    me = client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert me.status_code == 200
    assert me.json()["email"] == "analista@nexo.invalid"

    duplicate = client.post(
        "/api/v1/auth/register",
        json={"email": "analista@nexo.invalid", "password": "otra-clave-larga"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "email_taken"

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "analista@nexo.invalid", "password": "clave-segura-123"},
    )
    assert login.status_code == 200
    second_token = login.json()["access_token"]
    assert second_token != token

    sessions = client.get("/api/v1/auth/sessions", headers=auth_headers(second_token))
    assert sessions.json()["total"] == 2

    logout = client.post("/api/v1/auth/logout", headers=auth_headers(second_token))
    assert logout.status_code == 200
    assert client.get("/api/v1/auth/me", headers=auth_headers(second_token)).status_code == 401
    # La primera sesión sigue activa: cerrar una no revoca las demás.
    assert client.get("/api/v1/auth/me", headers=auth_headers(token)).status_code == 200


def test_weak_password_and_bad_credentials(client):
    weak = client.post(
        "/api/v1/auth/register",
        json={"email": "corta@nexo.invalid", "password": "123"},
    )
    assert weak.status_code == 422

    register(client, email="otro@nexo.invalid")
    wrong = client.post(
        "/api/v1/auth/login",
        json={"email": "otro@nexo.invalid", "password": "clave-incorrecta"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "invalid_credentials"


def test_requires_token(client):
    assert client.get("/api/v1/companies").status_code == 401
    assert client.get("/api/v1/dashboard").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer inventado"}).status_code == 401


def test_dashboard_shape(client):
    token = register(client)["access_token"]
    response = client.get("/api/v1/dashboard", headers=auth_headers(token))
    assert response.status_code == 200
    body = response.json()
    assert "system" in body and "usage" in body and "alerts" in body
    assert body["usage"]["limit_usd"] == 10.0
    assert body["system"]["ai_available"] is True
