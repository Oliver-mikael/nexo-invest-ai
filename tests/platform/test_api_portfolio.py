"""Cartera simulada: operaciones, coste medio y rendimiento."""

from __future__ import annotations

from tests.platform.conftest import auth_headers, register


def _portfolio(client, headers) -> int:
    response = client.post(
        "/api/v1/portfolios",
        headers=headers,
        json={"name": "Prueba", "starting_cash": 100000, "benchmark": "SPY"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_buy_sell_and_performance(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    portfolio_id = _portfolio(client, headers)

    buy = client.post(
        f"/api/v1/portfolios/{portfolio_id}/trades",
        headers=headers,
        json={"symbol": "AAPL", "side": "buy", "quantity": 10, "price": 200, "fee": 1},
    )
    assert buy.status_code == 201, buy.text
    assert buy.json()["portfolio"]["cash"] == 97999.0

    detail = client.get(f"/api/v1/portfolios/{portfolio_id}", headers=headers).json()
    assert detail["cash"] == 97999.0
    assert detail["positions"][0]["symbol"] == "AAPL"
    assert detail["positions"][0]["price"] == 230.0
    assert detail["market_value"] == 2300.0
    assert detail["total_value"] == 100299.0
    assert round(detail["total_return"], 6) == round(0.00299, 6)
    assert detail["positions"][0]["unrealized"] == 299.0

    sell = client.post(
        f"/api/v1/portfolios/{portfolio_id}/trades",
        headers=headers,
        json={"symbol": "AAPL", "side": "sell", "quantity": 5, "price": 240, "fee": 1},
    )
    assert sell.status_code == 201
    assert sell.json()["portfolio"]["cash"] == 99198.0

    detail = client.get(f"/api/v1/portfolios/{portfolio_id}", headers=headers).json()
    # (240 - 200,1) * 5 - 1 = 198,5
    assert detail["realized_pnl"] == 198.5
    assert detail["positions"][0]["quantity"] == 5


def test_rejects_oversell_and_overspend(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    portfolio_id = _portfolio(client, headers)

    oversell = client.post(
        f"/api/v1/portfolios/{portfolio_id}/trades",
        headers=headers,
        json={"symbol": "AAPL", "side": "sell", "quantity": 1, "price": 200},
    )
    assert oversell.status_code == 422
    assert oversell.json()["error"]["code"] == "invalid_trade"

    overspend = client.post(
        f"/api/v1/portfolios/{portfolio_id}/trades",
        headers=headers,
        json={"symbol": "AAPL", "side": "buy", "quantity": 1000, "price": 200},
    )
    assert overspend.status_code == 422

    negative = client.post(
        f"/api/v1/portfolios/{portfolio_id}/trades",
        headers=headers,
        json={"symbol": "AAPL", "side": "buy", "quantity": -1, "price": 200},
    )
    assert negative.status_code == 422


def test_portfolio_isolation_and_list(client):
    owner = register(client, email="cartera1@nexo.invalid")["access_token"]
    other = register(client, email="cartera2@nexo.invalid")["access_token"]
    portfolio_id = _portfolio(client, auth_headers(owner))

    listed = client.get("/api/v1/portfolios", headers=auth_headers(owner)).json()
    assert listed["total"] == 1
    assert listed["items"][0]["positions"] == 0

    assert (
        client.get(f"/api/v1/portfolios/{portfolio_id}", headers=auth_headers(other)).status_code
        == 404
    )

    deleted = client.delete(f"/api/v1/portfolios/{portfolio_id}", headers=auth_headers(owner))
    assert deleted.status_code == 200
    assert client.get("/api/v1/portfolios", headers=auth_headers(owner)).json()["total"] == 0


def test_trades_history(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    portfolio_id = _portfolio(client, headers)
    client.post(
        f"/api/v1/portfolios/{portfolio_id}/trades",
        headers=headers,
        json={"symbol": "MSFT", "side": "buy", "quantity": 3, "price": 300, "thesis": "Calidad"},
    )
    trades = client.get(f"/api/v1/portfolios/{portfolio_id}/trades", headers=headers).json()
    assert trades["total"] == 1
    assert trades["items"][0]["symbol"] == "MSFT"
    assert trades["items"][0]["side"] == "buy"
