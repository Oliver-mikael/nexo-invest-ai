"""Fase 8: backtests deterministas sin red (costes, divisas, walk-forward, aislamiento).

Toda la verificación usa series sembradas en la base: comprueba que las
señales no miran al futuro, que los costes restan, que las divisas se
convierten con tasas históricas y que cada usuario solo ve sus backtests.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict

from sqlalchemy import select

from app.db import session_scope
from app.models import FxRate, Instrument, Quote
from tests.platform.conftest import auth_headers, register

TODAY = date.today()


def _instrument(client, headers, *, symbol: str = "AAPL", currency: str = "USD",
                market: str = "XNAS") -> str:
    response = client.post(
        "/api/v1/instruments",
        headers=headers,
        json={
            "symbol": symbol,
            "name": f"{symbol} Test",
            "market_code": market,
            "currency": currency,
            "instrument_type": "stock",
            "country_code": "GB" if currency != "USD" else "US",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["uid"]


def _instrument_id(uid: str) -> int:
    with session_scope() as session:
        row = session.execute(select(Instrument).where(Instrument.uid == uid)).scalar_one()
        return row.id


def _seed_quotes(uid: str, *, days: int = 120, first: Decimal = Decimal("100"),
                 step: Decimal = Decimal("1"), currency: str = "USD") -> None:
    """Serie diaria ascendente: determinista y con cruce SMA claro."""
    instrument_id = _instrument_id(uid)
    with session_scope() as session:
        for offset in range(days):
            session.add(
                Quote(
                    instrument_id=instrument_id,
                    price=first + step * Decimal(offset),
                    currency=currency,
                    as_of=TODAY - timedelta(days=days - offset),
                    source="stockanalysis",
                    quality="close",
                )
            )


def _seed_fx(base: str, quote: str, *, rate: str = "0.80", days: int = 150) -> None:
    with session_scope() as session:
        for offset in range(days, 0, -7):
            session.add(
                FxRate(
                    base_currency=base,
                    quote_currency=quote,
                    rate=Decimal(rate),
                    as_of=TODAY - timedelta(days=offset),
                    source="ecb",
                    quality="close",
                )
            )


def _seed_fx_changing(base: str, quote: str) -> None:
    """Tasa vieja 0.80 y reciente 1.60: la elegida por fecha debe cambiar."""
    with session_scope() as session:
        session.add(FxRate(
            base_currency=base, quote_currency=quote, rate=Decimal("0.80"),
            as_of=TODAY - timedelta(days=120), source="ecb", quality="close"))
        session.add(FxRate(
            base_currency=base, quote_currency=quote, rate=Decimal("1.60"),
            as_of=TODAY - timedelta(days=7), source="ecb", quality="close"))


def _body(uid: str, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"instrument_uid": uid, "strategy": "buy_hold"}
    body.update(overrides)
    return body


# -- motor determinista ---------------------------------------------------------


def test_buy_hold_matches_series_and_costs_reduce_return(client):
    headers = auth_headers(register(client)["access_token"])
    uid = _instrument(client, headers)
    _seed_quotes(uid, days=120, first=Decimal("100"), step=Decimal("1"))

    free = client.post("/api/v1/backtests", headers=headers,
                       json=_body(uid, commission_bps=0, slippage_bps=0))
    assert free.status_code == 200, free.text
    paid = client.post("/api/v1/backtests", headers=headers,
                       json=_body(uid, commission_bps=25, slippage_bps=10))
    assert paid.status_code == 200, paid.text

    free_metrics = free.json()["metrics"]
    paid_metrics = paid.json()["metrics"]
    # Compra al cierre del día 2 (sin look-ahead) y mantiene hasta el final.
    assert Decimal(free_metrics["final_equity"]) > Decimal("10000")
    assert Decimal(paid_metrics["final_equity"]) < Decimal(free_metrics["final_equity"])
    assert paid_metrics["max_drawdown"] <= 0
    assert free.json()["curve"][0]["date"] < free.json()["curve"][-1]["date"]
    # Misma petición, mismos números (determinismo).
    again = client.post("/api/v1/backtests", headers=headers,
                        json=_body(uid, commission_bps=0, slippage_bps=0))
    assert again.json()["metrics"] == free_metrics


def test_no_lookahead_first_trade_is_after_first_close(client):
    headers = auth_headers(register(client)["access_token"])
    uid = _instrument(client, headers)
    _seed_quotes(uid, days=120, first=Decimal("200"), step=Decimal("-1"))  # bajista → venta

    result = client.post("/api/v1/backtests", headers=headers, json=_body(uid)).json()
    first_close = (TODAY - timedelta(days=120)).isoformat()
    for trade in result["last_trades"]:
        assert trade["day"] > first_close  # nunca en el cierre de la señal


def test_sma_cross_trades_and_metrics(client):
    headers = auth_headers(register(client)["access_token"])
    uid = _instrument(client, headers)
    _seed_quotes(uid, days=120, first=Decimal("100"), step=Decimal("1"))

    response = client.post(
        "/api/v1/backtests", headers=headers,
        json=_body(uid, strategy="sma_cross", params={"fast": 5, "slow": 20}),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["trades"] >= 1
    metrics = payload["metrics"]
    for key in ("total_return", "cagr", "ann_volatility", "sharpe", "sortino", "max_drawdown"):
        assert key in metrics, key
    assert payload["walk_forward"]["applied"] is False

    invalid = client.post(
        "/api/v1/backtests", headers=headers,
        json=_body(uid, strategy="sma_cross", params={"fast": 50, "slow": 20}),
    )
    assert invalid.status_code == 400

    unknown = client.post("/api/v1/backtests", headers=headers,
                          json=_body(uid, strategy="grid_trading"))
    assert unknown.status_code == 400


def test_walk_forward_splits_train_and_eval(client):
    headers = auth_headers(register(client)["access_token"])
    uid = _instrument(client, headers)
    _seed_quotes(uid, days=150, first=Decimal("50"), step=Decimal("1"))

    response = client.post(
        "/api/v1/backtests", headers=headers,
        json=_body(uid, strategy="sma_cross", params={"fast": 5, "slow": 20},
                   walk_forward=True),
    )
    assert response.status_code == 200, response.text
    walk = response.json()["walk_forward"]
    assert walk["applied"] is True
    assert walk["train_points"] > 0 and walk["eval_points"] > 0
    assert walk["train_points"] + walk["eval_points"] == response.json()["points"]
    assert walk["chosen"] in [{"fast": fast, "slow": slow} for fast in (5, 10, 15)
                              for slow in (20, 30, 40) if fast < slow]
    # La evaluación arranca después del bloque de entrenamiento.
    assert walk["split_date"] >= (TODAY - timedelta(days=150)).isoformat()
    assert "no participaron en la selección" in walk["note"]


# -- divisas y benchmark ---------------------------------------------------------


def test_fx_conversion_uses_historical_rates(client):
    headers = auth_headers(register(client)["access_token"])
    gbp_uid = _instrument(client, headers, symbol="VOD", currency="GBP", market="XLON")
    _seed_quotes(gbp_uid, days=60, first=Decimal("100"), step=Decimal("1"), currency="GBP")

    missing = client.post("/api/v1/backtests", headers=headers,
                          json=_body(gbp_uid, base_currency="USD"))
    assert missing.status_code == 400
    assert "Sin tasas históricas" in missing.json()["error"]["message"]

    # Tasa histórica: 1 USD = 0.80 GBP → 1 GBP = 1.25 USD al inicio del
    # periodo; 1.60 GBP por USD (factor 0.625) al final. La compra se ejecuta
    # con la tasa vieja y el cierre final con la reciente.
    _seed_fx_changing("USD", "GBP")
    converted = client.post("/api/v1/backtests", headers=headers,
                            json=_body(gbp_uid, base_currency="USD"))
    assert converted.status_code == 200, converted.text
    assert not any("Sin tasas" in warning
                   for warning in converted.json()["warnings"])

    local = client.post("/api/v1/backtests", headers=headers,
                        json=_body(gbp_uid, base_currency="GBP"))
    assert local.status_code == 200  # sin conversión: moneda propia

    # Factor efectivo: 0.625 / 1.25 = 0.5 → la tasa se aplica por fecha.
    ratio = (Decimal(converted.json()["metrics"]["final_equity"])
             / Decimal(local.json()["metrics"]["final_equity"]))
    assert abs(ratio - Decimal("0.5")) < Decimal("0.01")


def test_benchmark_block_when_data_exists(client):
    headers = auth_headers(register(client)["access_token"])
    uid = _instrument(client, headers, symbol="AAPL")
    bench_uid = _instrument(client, headers, symbol="SPY")
    _seed_quotes(uid, days=60, first=Decimal("100"), step=Decimal("1"))
    _seed_quotes(bench_uid, days=60, first=Decimal("300"), step=Decimal("2"))

    with_bench = client.post("/api/v1/backtests", headers=headers,
                             json=_body(uid, benchmark_uid=bench_uid)).json()
    assert with_bench["benchmark_result"]["available"] is True
    assert with_bench["benchmark_result"]["symbol"] == "SPY"
    assert "total_return" in with_bench["benchmark_result"]["metrics"]

    empty_bench = _instrument(client, headers, symbol="EMPTY")
    omitted = client.post("/api/v1/backtests", headers=headers,
                          json=_body(uid, benchmark_uid=empty_bench)).json()
    assert omitted["benchmark_result"]["available"] is False
    assert any("sin datos" in warning for warning in omitted["warnings"])


def test_insufficient_data_and_invalid_period(client):
    headers = auth_headers(register(client)["access_token"])
    uid = _instrument(client, headers, symbol="THIN")
    _seed_quotes(uid, days=10)

    poor = client.post("/api/v1/backtests", headers=headers, json=_body(uid))
    assert poor.status_code == 400
    assert "Sin datos suficientes" in poor.json()["error"]["message"]

    rich = _instrument(client, headers, symbol="RICH")
    _seed_quotes(rich, days=60)
    bad_period = client.post("/api/v1/backtests", headers=headers,
                             json=_body(rich, start=TODAY.isoformat(),
                                        end=(TODAY - timedelta(days=30)).isoformat()))
    assert bad_period.status_code == 400


# -- persistencia y aislamiento ---------------------------------------------------


def test_backtest_persists_and_is_isolated(client):
    owner = auth_headers(register(client)["access_token"])
    other = auth_headers(register(client, email="otro@nexo.invalid")["access_token"])
    uid = _instrument(client, owner, symbol="AAPL")
    _seed_quotes(uid, days=60, first=Decimal("100"), step=Decimal("1"))

    assert client.get("/api/v1/backtests").status_code == 401
    created = client.post("/api/v1/backtests", headers=owner, json=_body(uid))
    assert created.status_code == 200
    run_id = created.json()["id"]

    listed = client.get("/api/v1/backtests", headers=owner).json()
    assert [item["id"] for item in listed["items"]] == [run_id]
    assert listed["items"][0]["instrument"]["symbol"] == "AAPL"

    detail = client.get(f"/api/v1/backtests/{run_id}", headers=owner).json()
    assert detail["curve"] and detail["metrics"]

    assert client.get(f"/api/v1/backtests/{run_id}", headers=other).status_code == 404
    assert client.get("/api/v1/backtests", headers=other).json()["items"] == []

    # La advertencia de que el histórico no garantiza nada viaja siempre.
    assert any("no garantiza" in note for note in created.json()["notes"])
