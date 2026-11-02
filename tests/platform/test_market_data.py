"""Fase 5: datos de mercado — adaptadores, persistencia y API (sin red).

Las respuestas se simulan con `httpx.MockTransport` replicando el formato real
verificado en vivo el 2026-10-31:

- Frankfurter v2: lista de `{date, base, quote, rate}`.
- StockAnalysis: `{status: 200, data: [{t,o,h,l,c,v,a}]}`.
- ExchangeRate-API: `{result: success, base_code, time_last_update_utc, rates}`.

La suite nunca abre conexiones de red: cualquier llamada real sería un fallo.
"""

from __future__ import annotations

import contextlib
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterator, List

import httpx
import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import DataCache, FxRate, FundamentalFact, Instrument, ProviderRun, Quote
from app.services.data.base import ProviderDataError, ProviderNotConfigured
from app.services.data.providers.sec_fundamentals import SecFundamentalsProvider
from app.services.data.sync import DataSyncService
from tests.platform.conftest import auth_headers, register

# -- respuestas simuladas (formato real) ---------------------------------------

FRANK_ROWS = [
    {"date": "2026-10-30", "base": "USD", "quote": "BOB", "rate": 12.05},
    {"date": "2026-10-30", "base": "USD", "quote": "EUR", "rate": 0.89},
]

ERAPI_PAYLOAD = {
    "result": "success",
    "base_code": "USD",
    "time_last_update_utc": "Fri, 30 Oct 2026 00:00:00 +0000",
    "rates": {"BOB": 12.60, "EUR": 0.89},
}

STOCKANALYSIS_PAYLOAD = {
    "status": 200,
    "data": [
        {"t": "2026-10-30", "o": 346.72, "h": 349.19, "l": 334.35, "c": 344.63,
         "v": 68841571, "a": 340.10},
        {"t": "2026-10-29", "o": 348.0, "h": 351.43, "l": 347.3, "c": 348.91,
         "v": 42582126, "a": 344.50},
    ],
}

SEC_COMPANYFACTS = {
    "facts": {
        "us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {"USD": [{
                    "start": "2025-10-01", "end": "2026-09-30",
                    "val": 400000000000, "filed": "2026-11-01", "form": "10-K",
                }]}
            },
            "NetIncomeLoss": {
                "units": {"USD": [{
                    "start": "2025-10-01", "end": "2026-09-30",
                    "val": 100000000000, "filed": "2026-11-01", "form": "10-K",
                }]}
            },
            "EarningsPerShareDiluted": {
                "units": {"USD/shares": [{
                    "start": "2025-10-01", "end": "2026-09-30",
                    "val": 6.11, "filed": "2026-11-01", "form": "10-K",
                }]}
            },
        },
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {"shares": [{
                    "end": "2026-09-30", "val": 15200000000,
                    "filed": "2026-11-01", "form": "10-Q",
                }]}
            },
        },
    }
}


@contextlib.contextmanager
def mocked_service(settings, handler: Callable[[httpx.Request], httpx.Response]) -> Iterator[DataSyncService]:
    """Servicio con transporte simulado y sleep inyectado (sin espera real)."""
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    service = DataSyncService(settings, client=http_client, sleep=lambda _s: None)
    try:
        yield service
    finally:
        http_client.close()


def _instrument(client, headers, *, symbol="AAPL", market="XNAS", country="US",
                currency="USD", cik=None) -> str:
    body: Dict[str, Any] = {
        "symbol": symbol,
        "name": f"{symbol} Test",
        "market_code": market,
        "currency": currency,
        "instrument_type": "stock",
        "country_code": country,
    }
    if cik is not None:
        body["cik"] = cik
    response = client.post("/api/v1/instruments", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()["uid"]


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condición no alcanzada a tiempo")


# -- divisas -------------------------------------------------------------------


def test_fx_sync_stores_rates_with_full_provenance(client, settings):
    """Sincronización real de divisas: persiste con fuente, calidad y fecha."""
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=FRANK_ROWS)

    with mocked_service(settings, handler) as service:
        result = service.sync_fx("USD", ["BOB", "EUR"])

    assert result["status"] == "success"
    assert result["stored"] == 2
    assert len(calls) == 1
    assert calls[0].url.host == "api.frankfurter.dev"

    with session_scope() as session:
        rows = list(session.execute(select(FxRate)).scalars().all())
        assert len(rows) == 2
        bob = next(r for r in rows if r.quote_currency == "BOB")
        assert bob.user_id is None  # global, no privado
        assert bob.source == "frankfurter"
        assert bob.quality == "close"  # diario, jamás realtime
        assert bob.kind == "reference"
        assert bob.as_of == date(2026, 10, 30)  # fecha del dato, no de consulta
        assert Decimal(bob.rate) == Decimal("12.05")

        run = session.execute(select(ProviderRun)).scalar_one()
        assert run.status == "success"
        assert run.category == "fx"
        assert run.request_count == 1
        assert run.details["items_stored"] == 2
        assert run.details["data_as_of"] == "2026-10-30"


def test_fx_response_never_overwrites_without_force(client, settings):
    """Una respuesta distinta no pisa un dato válido: se marca anomalía."""
    state = {"rate": 12.05}

    def handler(request: httpx.Request) -> httpx.Response:
        rows = [dict(row) for row in FRANK_ROWS]
        rows[0]["rate"] = state["rate"]
        return httpx.Response(200, json=rows)

    with mocked_service(settings, handler) as service:
        first = service.sync_fx("USD", ["BOB", "EUR"])
        assert first["status"] == "success"

        state["rate"] = 12.50
        # Caduca la caché: la reconsulta ocurre y el valor llega distinto
        with session_scope() as session:
            for row in session.execute(select(DataCache)).scalars().all():
                row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        second = service.sync_fx("USD", ["BOB", "EUR"])

        assert second["status"] == "partial"  # hay anomalías y nada guardado
        assert any(
            a["kind"] == "valor_existente_distinto_sin_force"
            for a in second["anomalies"]
        )
        with session_scope() as session:
            bob = session.execute(
                select(FxRate).where(FxRate.quote_currency == "BOB")
            ).scalar_one()
            assert Decimal(bob.rate) == Decimal("12.05")  # conservado

        forced = service.sync_fx("USD", ["BOB", "EUR"], force=True)
        # `partial` porque la sustitución queda registrada como anomalía
        assert forced["status"] == "partial"
        assert forced["updated"] == 1
        with session_scope() as session:
            bob = session.execute(
                select(FxRate).where(FxRate.quote_currency == "BOB")
            ).scalar_one()
            assert Decimal(bob.rate) == Decimal("12.50")
            run = session.execute(
                select(ProviderRun).order_by(ProviderRun.id.desc()).limit(1)
            ).scalar_one()
            assert any(
                a["kind"] == "valor_historico_reemplazado"
                for a in run.details["anomalies"]
            )


def test_fx_cache_prevents_duplicate_requests(client, settings):
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=FRANK_ROWS)

    with mocked_service(settings, handler) as service:
        first = service.sync_fx("USD", ["BOB", "EUR"])
        second = service.sync_fx("USD", ["BOB", "EUR"])

    assert first["status"] == "success"
    assert second["status"] == "cached"
    assert len(calls) == 1  # caché vigente: cero petición extra
    with session_scope() as session:
        runs = list(session.execute(select(ProviderRun)).scalars().all())
        assert [run.status for run in runs] == ["success", "cached"]


def test_fx_divergence_between_providers_is_recorded(client, settings):
    """La divergencia >3% entre fuentes se registra; ambas tasas se conservan."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "frankfurter" in request.url.host:
            return httpx.Response(200, json=FRANK_ROWS)
        return httpx.Response(200, json=ERAPI_PAYLOAD)

    with mocked_service(settings, handler) as service:
        service.sync_fx("USD", ["BOB", "EUR"])
        second = service.sync_fx("USD", ["BOB", "EUR"], provider_name="erapi")

    assert second["status"] in {"success", "partial"}
    with session_scope() as session:
        rows = list(session.execute(
            select(FxRate).where(FxRate.quote_currency == "BOB")
        ).scalars().all())
        assert sorted(r.source for r in rows) == ["erapi", "frankfurter"]
        assert Decimal(rows[0].rate) != Decimal(rows[1].rate)

        run = session.execute(
            select(ProviderRun).order_by(ProviderRun.id.desc()).limit(1)
        ).scalar_one()
        assert any(
            a["kind"] == "divergencia_entre_proveedores"
            for a in run.details["anomalies"]
        )


def test_fx_rate_limit_marks_run_failed_without_data(client, settings):
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, text="slow down")

    with mocked_service(settings, handler) as service:
        result = service.sync_fx("USD", ["BOB"])

    assert result["status"] == "failed"
    assert "429" in result["error"]
    assert len(calls) == settings.data_http_retries + 1  # reintentos acotados
    with session_scope() as session:
        assert session.execute(select(FxRate)).scalars().all() == []
        run = session.execute(select(ProviderRun)).scalar_one()
        assert run.status == "failed"
        assert "429" in run.error


def test_fx_historical_range_is_stored(client, settings):
    rows = [
        {"date": f"2026-10-{day:02d}", "base": "USD", "quote": "BOB", "rate": 12.0 + day / 100}
        for day in range(20, 25)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("from") == "2026-10-20"
        assert request.url.params.get("to") == "2026-10-24"
        return httpx.Response(200, json=rows)

    with mocked_service(settings, handler) as service:
        result = service.sync_fx(
            "USD", ["BOB"], start=date(2026, 10, 20), end=date(2026, 10, 24)
        )
        # ER-API no admite rangos: error explícito, no se inventa historial
        with pytest.raises(ProviderDataError):
            service.sync_fx(
                "USD", ["BOB"], start=date(2026, 10, 20), provider_name="erapi"
            )

    assert result["status"] == "success"
    assert result["stored"] == 5
    with session_scope() as session:
        dates = sorted(
            r.as_of for r in session.execute(select(FxRate)).scalars().all()
        )
        assert dates == [date(2026, 10, d) for d in range(20, 25)]


# -- precios históricos -------------------------------------------------------


def test_price_sync_stores_daily_closes_with_adjusted_separate(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "stockanalysis.com"
        assert "exchange" not in request.url.params  # EE. UU. sin parámetro
        return httpx.Response(200, json=STOCKANALYSIS_PAYLOAD)

    with mocked_service(settings, handler) as service:
        result = service.sync_prices(uid)

    assert result["status"] == "success"
    assert result["stored"] == 2
    assert result["latest_as_of"] == "2026-10-30"
    assert result["stale"] is False

    with session_scope() as session:
        instrument = session.execute(
            select(Instrument).where(Instrument.uid == uid)
        ).scalar_one()
        quotes = list(session.execute(
            select(Quote).where(Quote.instrument_id == instrument.id)
        ).scalars().all())
        assert len(quotes) == 4  # 2 sesiones × (cierre + ajustado)
        assert all(q.user_id is None and q.quality == "close" for q in quotes)
        close = next(q for q in quotes if not q.adjusted and str(q.as_of) == "2026-10-30")
        adjusted = next(q for q in quotes if q.adjusted and str(q.as_of) == "2026-10-30")
        assert Decimal(close.price) == Decimal("344.63")
        assert Decimal(adjusted.price) == Decimal("340.10")
        assert close.source == "stockanalysis"
        assert adjusted.source == "stockanalysis:adj"

        run = session.execute(select(ProviderRun)).scalar_one()
        assert run.status == "success"
        assert run.details["latest_as_of"] == "2026-10-30"


def test_price_sync_flags_stale_history(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers)
    payload = {
        "status": 200,
        "data": [{"t": "2026-09-01", "o": 100, "h": 101, "l": 99, "c": 100.5,
                  "v": 1000, "a": 100.5}],
    }

    with mocked_service(settings, lambda _r: httpx.Response(200, json=payload)) as service:
        result = service.sync_prices(uid)

    assert result["status"] == "success"
    assert result["stale"] is True  # más de data_stale_after_days de antigüedad

    # El estado de la API lo refleja para la interfaz
    token = register(client, email="stale@nexo.invalid")["access_token"]
    status = client.get("/api/v1/data/status", headers=auth_headers(token)).json()
    assert status["prices"] and status["prices"][0]["stale"] is True


def test_price_sync_failure_keeps_previous_quotes(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers)

    with mocked_service(
        settings, lambda _r: httpx.Response(200, json=STOCKANALYSIS_PAYLOAD)
    ) as service:
        first = service.sync_prices(uid)
        assert first["status"] == "success"

    # Segunda pasada forzada: el proveedor falla y no se toca lo ya guardado
    with mocked_service(
        settings, lambda _r: httpx.Response(500, text="caído")
    ) as service:
        second = service.sync_prices(uid, force=True)

    assert second["status"] == "failed"
    with session_scope() as session:
        instrument = session.execute(
            select(Instrument).where(Instrument.uid == uid)
        ).scalar_one()
        quotes = list(session.execute(
            select(Quote).where(Quote.instrument_id == instrument.id)
        ).scalars().all())
        assert len(quotes) == 4
        run = session.execute(
            select(ProviderRun).order_by(ProviderRun.id.desc()).limit(1)
        ).scalar_one()
        assert run.status == "failed"
        assert "500" in run.error


def test_price_sync_unsupported_market_fails_explicitly(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    # Mercado XMEX (México): fuera de la cobertura verificada US/DE/ES/GB
    uid = _instrument(
        client, headers, symbol="WALMEX", market="XMEX", country="MX",
        currency="MXN",
    )

    with mocked_service(
        settings, lambda _r: httpx.Response(200, json=STOCKANALYSIS_PAYLOAD)
    ) as service:
        result = service.sync_prices(uid)

    assert result["status"] == "failed"
    assert "no está soportado" in result["error"]
    with session_scope() as session:
        instrument = session.execute(
            select(Instrument).where(Instrument.uid == uid)
        ).scalar_one()
        quotes = session.execute(
            select(Quote).where(Quote.instrument_id == instrument.id)
        ).scalars().all()
        assert quotes == []  # ni se inventa ni se sustituye por otro mercado


# -- fundamentales -------------------------------------------------------------


class _StubSecClient:
    """Sustituto de `SecEdgarClient` con el companyfacts ya descargado."""

    def __init__(self, payload: Dict[str, Any]) -> None:
        self.payload = payload
        self.fetches: List[int] = []

    def require_contact(self, _purpose: str) -> None:
        return None

    def company_facts(self, cik: int):
        self.fetches.append(cik)
        record = SimpleNamespace(retrieved_at=datetime.now(timezone.utc))
        return self.payload, record


def test_fundamentals_store_only_reported_metrics(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers, symbol="AAPL", cik=320193)

    provider = SecFundamentalsProvider(contact="test@nexo.invalid")
    provider._client = _StubSecClient(SEC_COMPANYFACTS)

    with mocked_service(settings, lambda _r: httpx.Response(500)) as service:
        result = service.sync_fundamentals(uid, provider=provider)

    assert result["status"] == "success"
    assert result["stored"] == 1  # un periodo anual; no hay trimestre en el fixture
    with session_scope() as session:
        instrument = session.execute(
            select(Instrument).where(Instrument.uid == uid)
        ).scalar_one()
        fact = session.execute(
            select(FundamentalFact).where(FundamentalFact.instrument_id == instrument.id)
        ).scalar_one()
        assert fact.period_type == "annual"
        assert fact.fiscal_end == date(2026, 9, 30)
        assert fact.source == "sec"
        assert fact.quality == "reported"
        assert Decimal(fact.revenue) == Decimal("400000000000")
        assert Decimal(fact.eps_diluted) == Decimal("6.11")
        assert Decimal(fact.shares_outstanding) == Decimal("15200000000")
        # EBITDA y FCF no existen como concepto reportado: no se calculan
        assert fact.ebitda is None
        assert fact.free_cash_flow is None


def test_fundamentals_require_cik_and_do_not_invent_source(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers, symbol="SAP", market="XETR", country="DE",
                      currency="EUR")

    with mocked_service(settings, lambda _r: httpx.Response(500)) as service:
        with pytest.raises(ProviderNotConfigured):
            service.sync_fundamentals(uid)


# -- API -----------------------------------------------------------------------


def test_data_endpoints_require_authentication(client):
    for path in ("/api/v1/data/status", "/api/v1/data/runs", "/api/v1/data/news",
                 "/api/v1/data/fx-rates", "/api/v1/data/providers"):
        assert client.get(path).status_code == 401, path


def test_data_status_exposes_providers_runs_and_scheduler(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)

    status = client.get("/api/v1/data/status", headers=headers)
    assert status.status_code == 200
    payload = status.json()
    names = {p["name"] for p in payload["providers"]}
    assert {"frankfurter", "erapi", "stockanalysis", "sec"} <= names
    news = next(p for p in payload["providers"] if p["category"] == "news")
    assert news["configured"] is False  # sin proveedor: se informa, no se inventa
    assert payload["scheduler"]["enabled"] is False  # apagado por defecto
    assert "USD/BOB" in payload["scheduler"]["pairs"]

    providers = client.get("/api/v1/data/providers", headers=headers).json()
    assert any(p["category"] == "fx" and p["selected"] for p in providers["items"])


def test_sync_fx_via_api_synchronous(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=FRANK_ROWS)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client.app_state.data = DataSyncService(
        settings, client=http_client, sleep=lambda _s: None
    )
    try:
        response = client.post(
            "/api/v1/data/sync/fx",
            headers=headers,
            json={"base": "USD", "quotes": ["BOB", "EUR"], "background": False},
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["background"] is False
        assert body["status"] == "success"
        assert body["stored"] == 2
    finally:
        http_client.close()

    runs = client.get("/api/v1/data/runs", headers=headers).json()
    assert runs["total"] >= 1
    assert runs["items"][0]["status"] == "success"


def test_sync_fx_validates_quotes(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)

    same = client.post(
        "/api/v1/data/sync/fx", headers=headers,
        json={"base": "USD", "quotes": ["USD"], "background": False},
    )
    assert same.status_code == 400
    assert same.json()["error"]["code"] == "data_error"

    bad = client.post(
        "/api/v1/data/sync/fx", headers=headers,
        json={"base": "USD", "quotes": ["BOBB"], "background": False},
    )
    assert bad.status_code == 422


def test_sync_fx_background_is_deduplicated(client, settings):
    """Dos peticiones idénticas en vuelo comparten run: sin doble petición."""
    token = register(client)["access_token"]
    headers = auth_headers(token)

    def handler(request: httpx.Request) -> httpx.Response:
        time.sleep(0.25)  # mantiene el run activo mientras llega la 2.ª llamada
        return httpx.Response(200, json=FRANK_ROWS)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    service = DataSyncService(settings, client=http_client, sleep=lambda _s: None)
    client.app_state.data = service
    client.app_state.data_jobs.service = service
    try:
        first = client.post(
            "/api/v1/data/sync/fx", headers=headers,
            json={"base": "USD", "quotes": ["BOB"], "background": True},
        )
        assert first.status_code == 202
        run_id = first.json()["run_id"]
        assert first.json()["status"] == "queued"

        second = client.post(
            "/api/v1/data/sync/fx", headers=headers,
            json={"base": "USD", "quotes": ["BOB"], "background": True},
        )
        assert second.json()["run_id"] == run_id  # anti-duplicados

        detail: Dict[str, Any] = {}
        _wait_until(lambda: (detail.update(
            client.get(f"/api/v1/data/runs/{run_id}", headers=headers).json()
        ) or detail["status"] not in {"queued", "running"}))
        assert detail["status"] == "success"
    finally:
        http_client.close()


def test_sync_prices_endpoint_checks_instrument(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    response = client.post(
        "/api/v1/data/sync/prices", headers=headers,
        json={"instrument_uid": "00000000-0000-0000-0000-000000000000",
              "background": False},
    )
    assert response.status_code == 404


def test_auto_sync_toggle_feeds_scheduler(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers, symbol="AAPL", cik=320193)

    toggled = client.post(
        f"/api/v1/data/instruments/{uid}/auto-sync", headers=headers,
        json={"enabled": True},
    )
    assert toggled.status_code == 200, toggled.text
    assert toggled.json()["auto_sync"] is True

    from app.services.data.runner import DataSyncRunner

    runner = DataSyncRunner(settings)
    requests = runner.scheduled_requests()
    kinds = {(r["type"], r.get("instrument_uid")) for r in requests}
    assert ("prices", uid) in kinds
    assert ("fundamentals", uid) in kinds  # tiene CIK


def test_fundamentals_endpoint_lists_reported_periods(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers, symbol="AAPL", cik=320193)

    provider = SecFundamentalsProvider(contact="test@nexo.invalid")
    provider._client = _StubSecClient(SEC_COMPANYFACTS)
    http_client = httpx.Client(
        transport=httpx.MockTransport(lambda _r: httpx.Response(500))
    )
    service = DataSyncService(settings, client=http_client, sleep=lambda _s: None)
    service._fundamentals = provider
    client.app_state.data = service
    try:
        response = client.post(
            "/api/v1/data/sync/fundamentals", headers=headers,
            json={"instrument_uid": uid, "background": False},
        )
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "success"
    finally:
        http_client.close()

    listed = client.get(f"/api/v1/data/fundamentals/{uid}", headers=headers).json()
    assert listed["total"] == 1
    item = listed["items"][0]
    assert item["period_type"] == "annual"
    # Nunca se presentan EBITDA/FCF calculados como si fueran reportados
    assert "ebitda" not in item and "free_cash_flow" not in item
    assert "EBITDA" in listed["note"]


def test_news_endpoint_reports_unavailable_honestly(client):
    token = register(client)["access_token"]
    payload = client.get("/api/v1/data/news", headers=auth_headers(token)).json()
    assert payload == {
        "items": [],
        "available": False,
        "reason": payload["reason"],
    }
    assert payload["reason"]  # hay explicación, no contenido inventado


def test_private_fx_rates_stay_private_between_users(client, settings):
    token_a = register(client, email="privA@nexo.invalid")["access_token"]
    headers_a = auth_headers(token_a)
    token_b = register(client, email="privB@nexo.invalid")["access_token"]
    headers_b = auth_headers(token_b)

    manual = client.post(
        "/api/v1/fx-rates", headers=headers_a,
        json={"base_currency": "USD", "quote_currency": "BOB", "rate": "6.90",
              "as_of": "2024-06-28", "source": "manual-broker"},
    )
    assert manual.status_code == 201, manual.text

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=FRANK_ROWS)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client.app_state.data = DataSyncService(
        settings, client=http_client, sleep=lambda _s: None
    )
    try:
        client.post(
            "/api/v1/data/sync/fx", headers=headers_a,
            json={"base": "USD", "quotes": ["BOB"], "background": False},
        )
    finally:
        http_client.close()

    seen_a = client.get(
        "/api/v1/data/fx-rates", headers=headers_a,
        params={"base": "USD", "quote": "BOB"},
    ).json()["items"]
    assert any(row["private"] for row in seen_a)          # la suya
    assert any(not row["private"] for row in seen_a)      # la global

    seen_b = client.get(
        "/api/v1/data/fx-rates", headers=headers_b,
        params={"base": "USD", "quote": "BOB"},
    ).json()["items"]
    assert all(not row["private"] for row in seen_b)      # nunca la de otro
    assert all(row["rate"] != "6.90" for row in seen_b)

    # El panel de estado solo mira datos globales (nunca tasas privadas)
    status_b = client.get("/api/v1/data/status", headers=headers_b).json()
    pair = next(i for i in status_b["fx"] if i["pair"] == "USD/BOB")
    assert pair["available"] is True
    assert pair["sources"] == ["frankfurter"]
    assert all(v["rate"] != "6.90" for v in pair["values"])
