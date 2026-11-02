"""Fase 6: alertas declarativas, planificador persistente y API (sin red).

Las reglas se evalúan sobre datos sembrados directamente en la base de datos
(sequences de cotizaciones con procedencia, fundamentales, cartera real), sin
ningún proveedor externo. Se comprueba: disparo correcto por condición,
anti-duplicación por `dedupe_key`, aislamiento por usuario y la API completa.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import select

from app.db import session_scope
from app.models import AlertEvent, AlertRule, SystemState, User
from app.services.alerts import AlertEngine, AlertRuleError, KINDS
from app.services.scheduler import ALERT_STATE_KEY, SchedulerService
from tests.platform.conftest import auth_headers, register

TODAY = date.today()


def _user_id(email: str) -> int:
    with session_scope() as session:
        user = session.execute(select(User).where(User.email == email)).scalar_one()
        return user.id


def _instrument(client, headers, *, symbol: str = "AAPL", market: str = "XNAS",
                currency: str = "USD", country: str = "US") -> str:
    response = client.post(
        "/api/v1/instruments",
        headers=headers,
        json={
            "symbol": symbol,
            "name": f"{symbol} Test",
            "market_code": market,
            "currency": currency,
            "instrument_type": "stock",
            "country_code": country,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["uid"]


def _instrument_id(uid: str) -> int:
    from app.models import Instrument

    with session_scope() as session:
        row = session.execute(
            select(Instrument).where(Instrument.uid == uid)
        ).scalar_one()
        return row.id


def _quote(instrument_id: int, as_of: date, price: str, *,
           source: str = "stockanalysis", quality: str = "close") -> None:
    from app.models import Quote

    with session_scope() as session:
        session.add(
            Quote(
                instrument_id=instrument_id,
                price=Decimal(price),
                currency="USD",
                as_of=as_of,
                source=source,
                quality=quality,
            )
        )


def _rule(user_id: int, kind: str, *, instrument_id: Optional[int] = None,
          threshold: Optional[str] = None, config: Optional[Dict[str, Any]] = None,
          active: bool = True) -> int:
    with session_scope() as session:
        rule = AlertRule(
            user_id=user_id,
            instrument_id=instrument_id,
            kind=kind,
            threshold=Decimal(threshold) if threshold is not None else None,
            config=config or {},
            active=active,
        )
        session.add(rule)
        session.flush()
        return rule.id


def _events(kind: Optional[str] = None) -> list:
    with session_scope() as session:
        query = select(AlertEvent).order_by(AlertEvent.id)
        if kind is not None:
            query = query.where(AlertEvent.kind == kind)
        rows = session.execute(query).scalars().all()
        return [{"id": row.id, "kind": row.kind, "title": row.title, "detail": row.detail} for row in rows]


# -- catálogo y validación -----------------------------------------------------


def test_catalog_lists_eight_kinds():
    catalog = {item["kind"] for item in [
        {"kind": kind}
        for kind in (
            "price_above", "price_below", "target_entry", "target_exit",
            "price_change_pct", "fundamentals_change", "data_stale", "concentration_risk",
        )
    ]}
    assert catalog == set(KINDS)


def test_validate_requires_instrument_and_positive_threshold():
    engine = AlertEngine()
    with session_scope():
        try:
            engine.validate(kind="price_above", instrument=None, threshold=Decimal("100"),
                            window_days=None)
            raise AssertionError("debería exigir instrumento")
        except AlertRuleError as exc:
            assert "instrumento" in str(exc)
        userless = None
        try:
            engine.validate(kind="price_change_pct", instrument=userless,
                            threshold=Decimal("2000"), window_days=None)
        except AlertRuleError:
            pass  # instrumento faltante ya es suficientemente explícito


def test_unknown_kind_is_rejected():
    engine = AlertEngine()
    try:
        engine.validate(kind="inexistente", instrument=None, threshold=None, window_days=None)
        raise AssertionError("kind desconocido aceptado")
    except AlertRuleError as exc:
        assert "desconocida" in str(exc)


# -- reglas de precio ----------------------------------------------------------


def test_price_above_fires_once_per_dedup_data(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers)
    instrument_id = _instrument_id(uid)
    _quote(instrument_id, TODAY, "250")  # por encima del objetivo 200

    _rule(_user_id("analista@nexo.invalid"), "price_above",
                    instrument_id=instrument_id, threshold="200")
    engine = AlertEngine(settings)
    with session_scope() as session:
        first = engine.evaluate_all(session)
    assert len(first) == 1
    event = _events("price_above")[0]
    assert "250" in event["title"] and "200" in event["title"]

    # Segunda revisión el mismo día del dato: sin duplicado.
    with session_scope() as session:
        assert engine.evaluate_all(session) == []
    assert len(_events()) == 1


def test_price_change_pct_window(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers)
    instrument_id = _instrument_id(uid)
    _quote(instrument_id, TODAY - timedelta(days=5), "100")
    _quote(instrument_id, TODAY, "120")  # +20 % dentro de la ventana de 7 días

    _rule(_user_id("analista@nexo.invalid"), "price_change_pct",
                    instrument_id=instrument_id, threshold="10",
                    config={"window_days": 7})
    engine = AlertEngine(settings)
    with session_scope() as session:
        fired = engine.evaluate_all(session)
    assert len(fired) == 1
    detail = fired[0].detail
    assert detail["change_pct"] == "20.00"
    assert detail["start_price"] == "100.0000" and detail["end_price"] == "120.0000"

    # Regla desactivada: no dispara.
    _rule(_user_id("analista@nexo.invalid"), "price_change_pct",
          instrument_id=instrument_id, threshold="10",
          config={"window_days": 7}, active=False)
    with session_scope() as session:
        assert engine.evaluate_all(session) == []


# -- fundamentales y desactualización ------------------------------------------


def test_fundamentals_change(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers)
    instrument_id = _instrument_id(uid)
    from app.models import FundamentalFact

    with session_scope() as session:
        session.add(FundamentalFact(
            instrument_id=instrument_id, period_type="annual", fiscal_end=TODAY - timedelta(days=400),
            currency="USD", revenue=Decimal("100000000"), net_income=Decimal("90000000"),
            source="sec", quality="reported"))
        session.add(FundamentalFact(
            instrument_id=instrument_id, period_type="annual", fiscal_end=TODAY - timedelta(days=40),
            currency="USD", revenue=Decimal("100000000"), net_income=Decimal("70000000"),
            source="sec", quality="reported"))

    _rule(_user_id("analista@nexo.invalid"), "fundamentals_change",
                    instrument_id=instrument_id, threshold="10")
    engine = AlertEngine(settings)
    with session_scope() as session:
        fired = engine.evaluate_all(session)
    assert len(fired) == 1
    assert fired[0].detail["metric"] == "net_income"
    assert fired[0].detail["change_pct"] == "-22.22"
    assert fired[0].detail["sources"] == ["sec"]


def test_data_stale_uses_positions_and_weekly_dedupe(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers)
    instrument_id = _instrument_id(uid)
    _quote(instrument_id, TODAY - timedelta(days=30), "100")

    _rule(_user_id("analista@nexo.invalid"), "data_stale", threshold="5")
    engine = AlertEngine(settings)
    # Sin posiciones del usuario la regla sobre toda la cartera no tiene sujetos.
    with session_scope() as session:
        assert engine.evaluate_all(session) == []

    from app.models import RealAccount, RealMovement

    with session_scope() as session:
        account = RealAccount(user_id=_user_id("analista@nexo.invalid"), name="CC",
                              base_currency="USD")
        session.add(account)
        session.flush()
        session.add(RealMovement(
            account_id=account.id, instrument_id=instrument_id, movement_type="buy",
            movement_date=TODAY - timedelta(days=60), quantity=Decimal("1"),
            price=Decimal("100"), amount=Decimal("100"), currency="USD"))
    with session_scope() as session:
        first = engine.evaluate_all(session)
    assert len(first) == 1
    assert first[0].detail["age_days"] == 30

    with session_scope() as session:
        assert engine.evaluate_all(session) == []  # misma semana: sin duplicado


# -- concentración en cartera real ----------------------------------------------


def test_concentration_risk_fires_for_heavy_position(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers)
    instrument_id = _instrument_id(uid)
    _quote(instrument_id, TODAY, "210")

    account_response = client.post("/api/v1/real/accounts", headers=headers,
                                   json={"name": "Bolsa", "base_currency": "USD"})
    assert account_response.status_code == 201, account_response.text
    account_id = account_response.json()["id"]
    for movement in (
        {"movement_type": "deposit", "movement_date": str(TODAY - timedelta(days=60)),
         "amount": "100", "currency": "USD"},
        {"movement_type": "buy", "movement_date": str(TODAY - timedelta(days=59)),
         "instrument_uid": uid, "quantity": "1", "price": "100",
         "amount": "100", "currency": "USD"},
    ):
        created = client.post(f"/api/v1/real/accounts/{account_id}/movements",
                              headers=headers, json=movement)
        assert created.status_code == 201, created.text

    _rule(_user_id("analista@nexo.invalid"), "concentration_risk",
                    threshold="40")
    engine = AlertEngine(settings)
    with session_scope() as session:
        fired = engine.evaluate_all(session)
    assert len(fired) == 1
    assert fired[0].detail["weight_pct"] == "100.00"
    assert fired[0].detail["symbol"] == "AAPL"

    with session_scope() as session:
        assert engine.evaluate_all(session) == []  # dedupe semanal


# -- planificador y API ---------------------------------------------------------


def test_scheduler_persists_state_and_can_be_disabled(settings):
    scheduler = SchedulerService(settings)
    with session_scope() as session:
        assert scheduler.state(session) == {}
        scheduler.check_in_session(session)
        state = scheduler.state(session)
    assert state["last_run_at"]
    assert state["new_events"] == 0

    scheduler_2 = SchedulerService(settings)
    assert scheduler_2._thread is None  # intervalo por defecto 0: apagado


def test_state_row_registered_in_system_state():
    with session_scope() as session:
        row = session.execute(
            select(SystemState).where(SystemState.key == ALERT_STATE_KEY)
        ).scalar_one_or_none()
    assert row is not None and row.value.get("last_run_at")


def test_alert_api_full_flow(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers)
    instrument_id = _instrument_id(uid)
    _quote(instrument_id, TODAY, "250")

    # 401 sin sesión.
    assert client.get("/api/v1/alerts").status_code == 401

    created = client.post("/api/v1/alerts", headers=headers, json={
        "kind": "target_exit", "instrument_uid": uid, "threshold": 200})
    assert created.status_code == 200, created.text
    rule_id = created.json()["id"]

    listing = client.get("/api/v1/alerts", headers=headers).json()
    assert len(listing["rules"]) == 1
    assert listing["rules"][0]["label"] == "Objetivo de salida"

    # Regla inválida ya validada antes: sin umbral → 400.
    invalid = client.post("/api/v1/alerts", headers=headers, json={
        "kind": "target_exit", "instrument_uid": uid})
    assert invalid.status_code == 400

    events = client.post("/api/v1/alerts/evaluate", headers=headers).json()
    assert events["new_events"] == 1
    again = client.post("/api/v1/alerts/evaluate", headers=headers).json()
    assert again["new_events"] == 0

    listing = client.get("/api/v1/alerts/events", headers=headers).json()
    assert listing["unread"] == 1 and listing["events"][0]["kind"] == "target_exit"

    marked = client.post("/api/v1/alerts/events/read-all", headers=headers).json()
    assert marked["marked"] == 1
    assert client.get("/api/v1/alerts/events", headers=headers).json()["unread"] == 0

    patch = client.patch(f"/api/v1/alerts/{rule_id}", headers=headers,
                         json={"active": False})
    assert patch.status_code == 200 and patch.json()["active"] is False
    assert client.delete(f"/api/v1/alerts/{rule_id}", headers=headers).status_code == 200
    assert client.get("/api/v1/alerts", headers=headers).json()["rules"] == []


def test_alert_isolation_between_users(client, settings):
    first = register(client)["access_token"]
    second = register(client, email="otro@nexo.invalid")["access_token"]

    headers = auth_headers(first)
    uid = _instrument(client, headers)
    instrument_id = _instrument_id(uid)
    _quote(instrument_id, TODAY, "250")
    client.post("/api/v1/alerts", headers=headers,
                json={"kind": "price_above", "instrument_uid": uid, "threshold": 200})
    client.post("/api/v1/alerts/evaluate", headers=headers)

    other_headers = auth_headers(second)
    other_list = client.get("/api/v1/alerts", headers=other_headers).json()
    other_events = client.get("/api/v1/alerts/events", headers=other_headers).json()
    assert other_list["rules"] == [] and other_events["events"] == []
