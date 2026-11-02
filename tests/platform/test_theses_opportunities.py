"""Fase 7: tesis versionadas, watchlist, oportunidades y roles nuevos (sin red).

Las tesis se comprueban con cotizaciones y fundamentales sembrados en la base:
el motor debe registrar indicios sin invalidar nada por sí mismo, y los
estudios de oportunidad deben declarar qué le falta a cada instrumento.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict

from app.db import session_scope
from app.models import FundamentalFact, Quote
from tests.platform.conftest import auth_headers, register

TODAY = date.today()


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


def _seed_quotes(instrument_id: int, *, days: int = 40, price: Decimal = Decimal("100")) -> None:
    with session_scope() as session:
        for offset in range(days, 0, -1):
            session.add(
                Quote(
                    instrument_id=instrument_id,
                    price=price + Decimal(offset) * Decimal(2),
                    currency="USD",
                    as_of=TODAY - timedelta(days=offset),
                    source="stockanalysis",
                    quality="close",
                )
            )


def _seed_fundamentals(instrument_id: int, *, old_revenue: str, current_revenue: str) -> None:
    with session_scope() as session:
        session.add(FundamentalFact(
            instrument_id=instrument_id, period_type="annual",
            fiscal_end=TODAY - timedelta(days=440), currency="USD",
            revenue=Decimal(old_revenue), net_income=Decimal("80000000"),
            source="sec", quality="reported"))
        session.add(FundamentalFact(
            instrument_id=instrument_id, period_type="annual",
            fiscal_end=TODAY - timedelta(days=80), currency="USD",
            revenue=Decimal(current_revenue), net_income=Decimal("80000000"),
            source="sec", quality="reported"))


def _instrument_id(uid: str) -> int:
    from app.models import Instrument

    with session_scope() as session:
        row = session.execute(
            select(Instrument).where(Instrument.uid == uid)
        ).scalar_one()
        return row.id


from sqlalchemy import select  # noqa: E402


# -- watchlist -----------------------------------------------------------------


def test_watchlist_flow_and_isolation(client):
    owner = auth_headers(register(client)["access_token"])
    intruder = auth_headers(register(client, email="mirada@nexo.invalid")["access_token"])
    uid = _instrument(client, owner)

    added = client.post("/api/v1/watchlist", headers=owner,
                        json={"instrument_uid": uid, "note": "seguimiento"})
    assert added.status_code == 200 and added.json()["already"] is False

    duplicate = client.post("/api/v1/watchlist", headers=owner, json={"instrument_uid": uid})
    assert duplicate.json()["already"] is True

    listing = client.get("/api/v1/watchlist", headers=owner).json()
    assert len(listing["items"]) == 1 and listing["items"][0]["symbol"] == "AAPL"

    assert client.get("/api/v1/watchlist", headers=intruder).json()["items"] == []
    assert client.get("/api/v1/instruments").status_code == 401

    assert client.delete(f"/api/v1/watchlist/{uid}", headers=owner).status_code == 200
    assert client.get("/api/v1/watchlist", headers=owner).json()["items"] == []


# -- tesis ----------------------------------------------------------------------


def _thesis_body(uid: str, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "instrument_uid": uid,
        "horizon": "medium",
        "title": "Pricing power en hardware premium",
        "hypothesis": "La empresa sostiene márgenes altos gracias a premium de marca y ecosistema.",
        "invalidation_conditions": [
            {"type": "price_below", "price": 80, "note": "huída de múltiplo"},
            {"type": "text", "text": "Margen bruto bajo 30 % en dos reportes seguidos"},
        ],
        "entry_target": 90,
        "exit_target": 200,
    }
    body.update(overrides)
    return body


def test_thesis_create_requires_session_and_validations(client):
    uid = _instrument(client, auth_headers(register(client)["access_token"]))
    assert client.get("/api/v1/theses").status_code == 401
    headers = auth_headers(register(client, email="tesis1@nexo.invalid")["access_token"])

    short = client.post("/api/v1/theses", headers=headers,
                        json=_thesis_body(uid, title="no"))
    assert short.status_code == 422

    bad_condition = client.post(
        "/api/v1/theses", headers=headers,
        json=_thesis_body(uid, invalidation_conditions=[{"type": "text", "text": ""}]),
    )
    assert bad_condition.status_code == 400

    duplicate_open = None
    created = client.post("/api/v1/theses", headers=headers, json=_thesis_body(uid))
    assert created.status_code == 200, created.text
    thesis_id = created.json()["id"]
    try_again = client.post("/api/v1/theses", headers=headers, json=_thesis_body(uid))
    assert try_again.status_code == 400  # solo una abierta por instrumento
    assert duplicate_open is None

    detail = client.get(f"/api/v1/theses/{thesis_id}", headers=headers).json()
    assert detail["version_count"] == 1
    assert len(detail["versions"]) == 1 and detail["versions"][0]["note"].startswith("Versión")
    assert detail["status"] == "open"


def test_thesis_versions_and_events(client):
    headers = auth_headers(register(client, email="tesis2@nexo.invalid")["access_token"])
    uid = _instrument(client, headers)
    thesis_id = client.post("/api/v1/theses", headers=headers, json=_thesis_body(uid)).json()["id"]

    unchanged = client.post(f"/api/v1/theses/{thesis_id}/versions", headers=headers,
                            json={})
    assert unchanged.status_code == 400

    version = client.post(f"/api/v1/theses/{thesis_id}/versions", headers=headers, json={
        "hypothesis": "Revisión: el premium se sostiene pero el ciclo de producto se frena.",
        "note": "Comentarios del último trimestre.",
    })
    assert version.status_code == 200
    assert version.json()["number"] == 2

    detail = client.get(f"/api/v1/theses/{thesis_id}", headers=headers).json()
    assert detail["version_count"] == 2
    assert detail["status"] == "under_review"
    kinds = [event["kind"] for event in detail["events"]]
    assert kinds[0] == "thesis_revision"

    decision = client.post(f"/api/v1/theses/{thesis_id}/events", headers=headers, json={
        "kind": "decision", "payload": {"note": "Mantener en seguimiento"}})
    assert decision.status_code == 200

    rejected = client.post(f"/api/v1/theses/{thesis_id}/events", headers=headers, json={
        "kind": "invalidated", "payload": {}})
    assert rejected.status_code == 400  # solo cambia por PATCH de estado


def test_thesis_engine_records_price_signal_and_dedupes(client):
    headers = auth_headers(register(client, email="tesis3@nexo.invalid")["access_token"])
    uid = _instrument(client, headers)
    instrument_id = _instrument_id(uid)
    _seed_quotes(instrument_id, days=5, price=Decimal("60"))  # último cierre 112: bajo la entrada 90? no

    thesis_id = client.post(
        "/api/v1/theses", headers=headers,
        json=_thesis_body(uid, invalidation_conditions=[{"type": "price_below", "price": 120}]),
    ).json()["id"]
    # Precios sembrados: 100+2*offset → rango 102..108 (5 sesiones); rompe price_below 120? NO.
    # Ajustamos: condición de precio por debajo de 120 exige precio ≤120.
    first = client.post("/api/v1/theses/evaluate", headers=headers).json()
    assert first["new_events"] == 1
    detail = client.get(f"/api/v1/theses/{thesis_id}", headers=headers).json()
    assert detail["events"][0]["kind"] == "price_signal"
    assert detail["events"][0]["payload"]["trigger"] == "price_below"
    assert detail["status"] == "under_review"  # sugerido por el motor

    second = client.post("/api/v1/theses/evaluate", headers=headers).json()
    assert second["new_events"] == 0  # misma fecha de dato, sin duplicado


def test_thesis_status_transitions_and_isolation(client):
    owner = auth_headers(register(client, email="tesis4@nexo.invalid")["access_token"])
    intruder = register(client, email="tesis5@nexo.invalid")["access_token"]
    uid = _instrument(client, owner)
    thesis_id = client.post("/api/v1/theses", headers=owner, json=_thesis_body(uid)).json()["id"]

    direct_invalid = client.patch(f"/api/v1/theses/{thesis_id}/status", headers=owner,
                                  json={"status": "invalidated"})
    assert direct_invalid.status_code == 400

    to_review = client.patch(f"/api/v1/theses/{thesis_id}/status", headers=owner,
                             json={"status": "under_review"})
    assert to_review.status_code == 200
    check = client.patch(f"/api/v1/theses/{thesis_id}/status", headers=owner,
                         json={"status": "validated", "note": "Datos confirman la hipótesis"})
    assert check.status_code == 200
    detail = client.get(f"/api/v1/theses/{thesis_id}", headers=owner).json()
    statuses = [event["kind"] for event in detail["events"]]
    assert "validated" in statuses

    # Un usuario ajeno ni siquiera ve la tesis.
    assert client.get(f"/api/v1/theses/{thesis_id}", headers=auth_headers(intruder)).status_code == 404
    listing = client.get("/api/v1/theses", headers=auth_headers(intruder)).json()
    assert listing["theses"] == []

    close = client.patch(f"/api/v1/theses/{thesis_id}/status", headers=owner,
                         json={"status": "closed"})
    assert close.status_code == 200
    assert client.get(f"/api/v1/theses/{thesis_id}", headers=owner).json()["status"] == "closed"


# -- oportunidades --------------------------------------------------------------


def test_opportunities_only_for_sufficient_data(client):
    headers = auth_headers(register(client, email="oportunidades@nexo.invalid")["access_token"])
    good_uid = _instrument(client, headers, symbol="GOOD")
    thin_uid = _instrument(client, headers, symbol="THIN", market="XLON",
                           currency="GBP", country="GB")
    _seed_quotes(_instrument_id(good_uid), days=40, price=Decimal("70"))
    _seed_fundamentals(_instrument_id(good_uid), old_revenue="300000000",
                       current_revenue="330000000")
    _seed_quotes(_instrument_id(thin_uid), days=3)

    result = client.get("/api/v1/opportunities", headers=headers).json()
    assert result["kind"] == "study"
    scored = {item["instrument"]["symbol"]: item for item in result["items"]}
    assert "GOOD" in scored
    assert 0 < scored["GOOD"]["score"] <= 100
    assert scored["GOOD"]["signals"]["revenue_growth_pct"] == "10.00"
    assert scored["GOOD"]["horizon"] in ("short", "medium", "long")

    skip_reasons = {row["symbol"]: row["reason"] for row in result["skipped"]}
    assert "THIN" in skip_reasons and "cierres" in skip_reasons["THIN"]

    by_horizon = client.get("/api/v1/opportunities?horizon=long", headers=headers).json()
    for item in by_horizon["items"]:
        assert item["horizon"] == "long"


def test_opportunities_empty_is_declared_not_invented(client):
    headers = auth_headers(register(client, email="vacio@nexo.invalid")["access_token"])
    result = client.get("/api/v1/opportunities", headers=headers).json()
    assert result["kind"] == "study"
    assert result["items"] == []
    assert "No se fuerza ninguna oportunidad" in result["note"]


# -- roles nuevos en el informe ---------------------------------------------------


def test_report_includes_technical_macro_and_risk_sections(client):
    headers = auth_headers(register(client, email="roles@nexo.invalid")["access_token"])
    created = client.post("/api/v1/research", headers=headers,
                          json={"ticker": "AAPL", "profile": "standard"})
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]

    import time as _time

    for _ in range(200):
        finished = client.get(f"/api/v1/research/{job_id}", headers=headers).json()
        if finished["status"] in {"completed", "failed"}:
            break
        _time.sleep(0.05)
    assert finished["status"] == "completed", finished

    report = client.get(f"/api/v1/reports/{finished['report_id']}", headers=headers).json()
    sections = {section["id"]: section for section in report["sections"]}
    assert sections["technical"]["basis"] == "ai"
    assert sections["macro"]["paragraphs"]
    risk_paragraphs = " ".join(sections["risks"]["paragraphs"])
    assert "Matiz de riesgos estructural" in risk_paragraphs

    plan = client.get("/api/v1/research/plan?profile=standard", headers=headers).json()
    labels = [role["label"] for role in plan["plan"]["roles"]]
    assert "Analista técnico" in labels and "Analista macro" in labels
    assert "Analista de riesgos" in labels
