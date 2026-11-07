"""Explorador de empresas, análisis del motor y valoración con supuestos."""

from __future__ import annotations

from tests.platform.conftest import auth_headers, register


def test_company_lookup_and_analysis(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)

    empty = client.get("/api/v1/companies", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["total"] == 0

    company = client.get("/api/v1/companies/AAPL", headers=headers)
    assert company.status_code == 200
    assert company.json()["cik"] == 320193

    search = client.get("/api/v1/companies?q=aapl", headers=headers)
    assert search.json()["total"] == 1

    analysis = client.get("/api/v1/companies/AAPL/analysis", headers=headers)
    assert analysis.status_code == 200
    payload = analysis.json()
    assert payload["identity"]["ticker"] == "AAPL"
    assert payload["identity"]["latest_period_end"]
    assert payload["provenance"]["counts"]["total"] > 100
    assert payload["provenance"]["quality_label"] in {"validada", "parcial", "no validada"}

    metrics = {item["key"]: item for item in payload["metrics"]}
    revenue = metrics["revenue"]
    assert revenue["value"] and revenue["value"] > 0
    assert revenue["provenance"] in {
        "external_downloaded",
        "external_validated",
        "external_corroborated",
    }
    assert metrics["gross_margin"]["kind"] == "percent"

    scenarios = payload["valuation"]["scenarios"]
    assert {s["name"] for s in scenarios} == {"bajista", "base", "alcista"}
    base = next(s for s in scenarios if s["name"] == "base")
    assert base["per_share_value"] and base["per_share_value"] > 0
    assert payload["valuation"]["sensitivity"]["available"] is True
    assert len(payload["valuation"]["sensitivity"]["cells"]) >= 9

    series = payload["series"]["revenue"]
    assert len(series) >= 3
    assert series[-1]["period_end"] >= series[0]["period_end"]


def test_custom_valuation_and_validation(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)

    response = client.post(
        "/api/v1/companies/AAPL/valuation",
        headers=headers,
        json={
            "forecast_years": 5,
            "discount_rate": 0.09,
            "terminal_growth": 0.02,
            "growth_rate": 0.03,
            "fcf_adjustment": 0.0,
            "sensitivity_steps": 1,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["per_share_value"] > 0
    assert body["assumptions"]["discount_rate"] == 0.09
    assert len(body["sensitivity"]["cells"]) == 9
    assert "no es precio objetivo" in body["warning"].lower()

    too_low_discount = client.post(
        "/api/v1/companies/AAPL/valuation",
        headers=headers,
        json={"discount_rate": 0.02, "terminal_growth": 0.03},
    )
    assert too_low_discount.status_code == 422
    assert too_low_discount.json()["error"]["code"] == "validation_error"

    out_of_range = client.post(
        "/api/v1/companies/AAPL/valuation",
        headers=headers,
        json={"forecast_years": 30},
    )
    assert out_of_range.status_code == 422


def test_engine_report_markdown(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    response = client.get("/api/v1/companies/AAPL/report?save=true", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert "# Nexo Invest AI" in body["markdown"]
    assert "Sensibilidad del escenario base" in body["markdown"]
    assert body["saved_report_id"]

    reports = client.get("/api/v1/reports", headers=headers)
    assert reports.json()["total"] == 1
    assert reports.json()["items"][0]["kind"] == "engine"


def test_engine_failure_returns_503(settings, orchestrator, prices):
    """Sin datos de la SEC la API responde 503 con un mensaje accionable."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.services.engine import EngineService, EngineUnavailable

    def failing_loader(ticker: str):
        raise EngineUnavailable("Falta NEXO_SEC_CONTACT para descargar datos")

    app = create_app(
        settings,
        engine=EngineService(settings, loader=failing_loader),
        orchestrator=orchestrator,
        price_provider=prices,
        start_workers=False,
    )
    with TestClient(app) as failing_client:
        token = register(failing_client)["access_token"]
        response = failing_client.get(
            "/api/v1/companies/MSFT", headers=auth_headers(token)
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "engine_unavailable"
        assert "NEXO_SEC_CONTACT" in response.json()["error"]["message"]
