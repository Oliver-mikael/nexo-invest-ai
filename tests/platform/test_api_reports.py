"""Historial de informes, exportaciones y aislamiento."""

from __future__ import annotations

from tests.platform.conftest import auth_headers, register


def _engine_report(client, headers) -> int:
    response = client.get("/api/v1/companies/AAPL/report?save=true", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["saved_report_id"]


def test_export_formats(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    report_id = _engine_report(client, headers)

    markdown = client.get(f"/api/v1/reports/{report_id}/export?format=md", headers=headers)
    assert markdown.status_code == 200
    assert "text/markdown" in markdown.headers["content-type"]
    assert "attachment" in markdown.headers["content-disposition"]
    assert "# Nexo Invest AI" in markdown.text

    html = client.get(f"/api/v1/reports/{report_id}/export?format=html", headers=headers)
    assert html.status_code == 200
    assert "<table>" in html.text
    assert "<h1>" in html.text

    csv_export = client.get(f"/api/v1/reports/{report_id}/export?format=csv", headers=headers)
    assert csv_export.status_code == 200
    assert "text/csv" in csv_export.headers["content-type"]

    invalid = client.get(f"/api/v1/reports/{report_id}/export?format=pdf", headers=headers)
    assert invalid.status_code == 422


def test_reports_pagination_and_isolation(client):
    owner = register(client, email="informes1@nexo.invalid")["access_token"]
    other = register(client, email="informes2@nexo.invalid")["access_token"]
    owner_headers = auth_headers(owner)

    ids = [_engine_report(client, owner_headers) for _ in range(3)]
    page = client.get("/api/v1/reports?limit=2&offset=0", headers=owner_headers).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert page["has_more"] is True

    second_page = client.get("/api/v1/reports?limit=2&offset=2", headers=owner_headers).json()
    assert len(second_page["items"]) == 1

    assert client.get(f"/api/v1/reports/{ids[0]}", headers=auth_headers(other)).status_code == 404
    assert (
        client.get(f"/api/v1/reports/{ids[0]}/export", headers=auth_headers(other)).status_code
        == 404
    )

    deleted = client.delete(f"/api/v1/reports/{ids[0]}", headers=owner_headers)
    assert deleted.status_code == 200
    assert client.get("/api/v1/reports", headers=owner_headers).json()["total"] == 2


def test_filters_by_kind_and_ticker(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    _engine_report(client, headers)
    engine_only = client.get("/api/v1/reports?kind=engine&ticker=AAPL", headers=headers).json()
    assert engine_only["total"] == 1
    none = client.get("/api/v1/reports?kind=research", headers=headers).json()
    assert none["total"] == 0
