"""API multimercado y cartera real: cifras, aislamiento e importación."""

from __future__ import annotations

import base64
from decimal import Decimal

from app.services.ocr import Extraction
from tests.platform.conftest import auth_headers, register


def _instrument(client, headers, symbol="AAPL", market="XNAS", currency="USD") -> str:
    response = client.post(
        "/api/v1/instruments",
        headers=headers,
        json={
            "symbol": symbol,
            "name": f"{symbol} Test",
            "market_code": market,
            "currency": currency,
            "instrument_type": "stock",
            "country_code": "US" if market == "XNAS" else "DE",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["uid"]


def _account(client, headers, *, name="Cuenta real", currency="USD") -> int:
    response = client.post(
        "/api/v1/real/accounts",
        headers=headers,
        json={
            "name": name,
            "broker_name": "Broker de prueba",
            "broker_country": "US",
            "base_currency": currency,
            "cost_method": "fifo",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _movement(client, headers, account_id, body):
    return client.post(
        f"/api/v1/real/accounts/{account_id}/movements", headers=headers, json=body
    )


def test_markets_instruments_quotes_and_fx(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    markets = client.get("/api/v1/markets", headers=headers)
    assert markets.status_code == 200
    codes = {market["code"] for market in markets.json()}
    assert {"XNYS", "XNAS", "XETR", "XBOL", "XTKS"} <= codes

    uid = _instrument(client, headers)
    duplicate = client.post(
        "/api/v1/instruments",
        headers=headers,
        json={"symbol": "AAPL", "name": "Otra", "market_code": "XNAS", "currency": "USD"},
    )
    assert duplicate.status_code == 409

    quote = client.post(
        f"/api/v1/instruments/{uid}/quotes",
        headers=headers,
        json={
            "price": "230.125",
            "as_of": "2024-06-28",
            "source": "manual-broker",
            "quality": "close",
        },
    )
    assert quote.status_code == 201, quote.text
    assert quote.json()["price"] == "230.125"
    assert quote.json()["source"] == "manual-broker"

    fx = client.post(
        "/api/v1/fx-rates",
        headers=headers,
        json={
            "base_currency": "EUR",
            "quote_currency": "USD",
            "rate": "1.0855",
            "as_of": "2024-06-28",
            "source": "manual-broker",
        },
    )
    assert fx.status_code == 201, fx.text
    assert fx.json()["rate"] == "1.0855"

    found = client.get("/api/v1/instruments?q=aapl", headers=headers).json()
    assert found["total"] == 1
    assert found["items"][0]["uid"] == uid


def test_real_account_summary_with_fifo_dividends_and_isolation(client):
    token = register(client, email="real1@nexo.invalid")["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers)
    account_id = _account(client, headers)

    created = _movement(
        client,
        headers,
        account_id,
        {"movement_type": "deposit", "movement_date": "2024-01-01", "amount": "10000"},
    )
    assert created.status_code == 201, created.text
    assert _movement(
        client,
        headers,
        account_id,
        {
            "movement_type": "buy",
            "movement_date": "2024-01-02",
            "instrument_uid": uid,
            "quantity": "10",
            "price": "200",
            "fee": "5",
        },
    ).status_code == 201
    assert _movement(
        client,
        headers,
        account_id,
        {
            "movement_type": "dividend",
            "movement_date": "2024-01-15",
            "instrument_uid": uid,
            "amount": "20",
            "tax": "2",
        },
    ).status_code == 201
    assert _movement(
        client,
        headers,
        account_id,
        {
            "movement_type": "sell",
            "movement_date": "2024-02-01",
            "instrument_uid": uid,
            "quantity": "5",
            "price": "240",
            "fee": "1",
        },
    ).status_code == 201
    quote = client.post(
        f"/api/v1/instruments/{uid}/quotes",
        headers=headers,
        json={"price": "250", "as_of": "2024-02-01", "source": "manual", "quality": "close"},
    )
    assert quote.status_code == 201

    summary = client.get(
        f"/api/v1/real/accounts/{account_id}/summary?as_of=2024-02-02&twr=false",
        headers=headers,
    )
    assert summary.status_code == 200, summary.text
    data = summary.json()
    # Efectivo: 10.000 - 2.005 + 18 + 1.199 = 9.212
    assert data["cash_base"] == "9212.00"
    # 5 acciones a 250 = 1.250; coste FIFO restante 1.002,50; no realizado 247,50.
    assert data["market_value_base"] == "1250.00"
    assert data["unrealized_base"] == "247.50"
    # Venta: 1.200 - 1 - 1.002,50 = 196,50; dividendo neto 18.
    assert data["realized_base"] == "196.50"
    assert data["dividends_base"] == "18.00"
    assert data["total_value_base"] == "10462.00"
    assert data["net_contributions_base"] == "10000.00"
    assert data["net_gain_base"] == "462.00"
    assert data["xirr_available"] is True
    assert Decimal(data["xirr_pct"]) > 0
    assert data["complete"] is True
    assert data["positions"][0]["symbol"] == "AAPL"
    assert data["positions"][0]["quantity"] == "5.0000000000"

    # La cartera simulada sigue vacía: no se mezclan tablas ni resultados.
    simulated = client.get("/api/v1/portfolios", headers=headers).json()
    assert simulated["total"] == 0

    other = register(client, email="real2@nexo.invalid")["access_token"]
    other_headers = auth_headers(other)
    assert (
        client.get(f"/api/v1/real/accounts/{account_id}", headers=other_headers).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/real/accounts/{account_id}/summary", headers=other_headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/real/accounts/{account_id}/movements", headers=other_headers
        ).status_code
        == 404
    )
    assert client.get("/api/v1/real/overview", headers=other_headers).json()["accounts"] == []


def test_rejects_oversell_duplicate_and_requires_fx(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers)
    account_id = _account(client, headers)

    assert _movement(
        client,
        headers,
        account_id,
        {"movement_type": "deposit", "movement_date": "2024-01-01", "amount": "1000"},
    ).status_code == 201
    assert _movement(
        client,
        headers,
        account_id,
        {
            "movement_type": "buy",
            "movement_date": "2024-01-02",
            "instrument_uid": uid,
            "quantity": "1",
            "price": "50",
        },
    ).status_code == 201
    oversell = _movement(
        client,
        headers,
        account_id,
        {
            "movement_type": "sell",
            "movement_date": "2024-01-03",
            "instrument_uid": uid,
            "quantity": "2",
            "price": "50",
        },
    )
    assert oversell.status_code == 422
    assert oversell.json()["error"]["code"] == "invalid_movement"

    duplicate = _movement(
        client,
        headers,
        account_id,
        {"movement_type": "deposit", "movement_date": "2024-01-01", "amount": "1000"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_movement"

    # Instrumento en EUR dentro de una cuenta USD: el tipo de cambio es obligatorio.
    eur_uid = _instrument(client, headers, symbol="SAP", market="XETR", currency="EUR")
    no_fx = _movement(
        client,
        headers,
        account_id,
        {
            "movement_type": "buy",
            "movement_date": "2024-01-04",
            "instrument_uid": eur_uid,
            "quantity": "1",
            "price": "100",
        },
    )
    assert no_fx.status_code == 422
    assert no_fx.json()["error"]["code"] == "fx_rate_required"

    with_fx = _movement(
        client,
        headers,
        account_id,
        {
            "movement_type": "buy",
            "movement_date": "2024-01-04",
            "instrument_uid": eur_uid,
            "quantity": "1",
            "price": "100",
            "fx_rate": "1.10",
            "fx_source": "manual",
        },
    )
    assert with_fx.status_code == 201, with_fx.text
    assert Decimal(with_fx.json()["movement"]["fx_rate"]) == Decimal("1.10")


def test_summary_marks_missing_quote_instead_of_inventing_it(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers)
    account_id = _account(client, headers)
    _movement(
        client,
        headers,
        account_id,
        {"movement_type": "deposit", "movement_date": "2024-01-01", "amount": "1000"},
    )
    _movement(
        client,
        headers,
        account_id,
        {
            "movement_type": "buy",
            "movement_date": "2024-01-02",
            "instrument_uid": uid,
            "quantity": "2",
            "price": "100",
        },
    )
    summary = client.get(
        f"/api/v1/real/accounts/{account_id}/summary?twr=false", headers=headers
    ).json()
    assert summary["complete"] is False
    assert summary["total_value_base"] is None
    assert uid in summary["missing_prices"]
    assert summary["positions"][0]["price"] is None


def test_manual_quotes_are_private_and_cannot_affect_other_users(client):
    owner = auth_headers(register(client, email="quote1@nexo.invalid")["access_token"])
    other = auth_headers(register(client, email="quote2@nexo.invalid")["access_token"])
    uid = _instrument(client, owner)
    quote = client.post(
        f"/api/v1/instruments/{uid}/quotes",
        headers=owner,
        json={"price": "250", "as_of": "2024-02-01", "source": "manual", "quality": "close"},
    )
    assert quote.status_code == 201

    for headers, email in ((owner, "owner"), (other, "other")):
        account_id = _account(client, headers, name=f"Cuenta {email}")
        assert _movement(
            client,
            headers,
            account_id,
            {"movement_type": "deposit", "movement_date": "2024-01-01", "amount": "1000"},
        ).status_code == 201
        assert _movement(
            client,
            headers,
            account_id,
            {
                "movement_type": "buy",
                "movement_date": "2024-01-02",
                "instrument_uid": uid,
                "quantity": "1",
                "price": "200",
            },
        ).status_code == 201
        summary = client.get(
            f"/api/v1/real/accounts/{account_id}/summary?twr=false", headers=headers
        ).json()
        if headers is owner:
            assert summary["complete"] is True
            assert Decimal(summary["positions"][0]["price"]) == Decimal("250")
        else:
            assert summary["complete"] is False
            assert summary["positions"][0]["price"] is None

    visible = client.get(f"/api/v1/instruments/{uid}/quotes", headers=other).json()
    assert visible["total"] == 0


def test_summary_respects_as_of_and_ignores_later_movements(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    account_id = _account(client, headers)
    _movement(
        client,
        headers,
        account_id,
        {"movement_type": "deposit", "movement_date": "2024-01-01", "amount": "1000"},
    )
    _movement(
        client,
        headers,
        account_id,
        {"movement_type": "deposit", "movement_date": "2025-01-01", "amount": "500"},
    )
    old = client.get(
        f"/api/v1/real/accounts/{account_id}/summary?as_of=2024-12-31&twr=false",
        headers=headers,
    ).json()
    assert old["cash_base"] == "1000.00"
    assert old["movements"] == 1
    current = client.get(
        f"/api/v1/real/accounts/{account_id}/summary?as_of=2025-06-30&twr=false",
        headers=headers,
    ).json()
    assert current["cash_base"] == "1500.00"
    assert current["movements"] == 2


def test_overview_groups_by_base_currency(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    usd_account = _account(client, headers, name="USD", currency="USD")
    bob_account = _account(client, headers, name="BOB", currency="BOB")
    for account_id, currency, amount in (
        (usd_account, "USD", "1000"),
        (bob_account, "BOB", "5000"),
    ):
        response = _movement(
            client,
            headers,
            account_id,
            {
                "movement_type": "deposit",
                "movement_date": "2024-01-01",
                "amount": amount,
                "currency": currency,
            },
        )
        assert response.status_code == 201, response.text
    data = client.get("/api/v1/real/overview", headers=headers).json()
    assert data["currencies"] == ["BOB", "USD"]
    by_currency = {group["currency"]: group for group in data["groups"]}
    assert by_currency["USD"]["total_value"] == "1000.00"
    assert by_currency["BOB"]["total_value"] == "5000.00"
    # No se suma BOB + USD sin tipo de cambio.
    assert "total" not in data


def test_csv_import_preview_requires_confirmation_and_detects_duplicates(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    _instrument(client, headers)
    account_id = _account(client, headers)
    csv_content = (
        "fecha;tipo;simbolo;cantidad;precio;comision;moneda;importe\n"
        "01/01/2024;deposito;;;;;USD;10000\n"
        "02/01/2024;compra;AAPL;10;200;1;USD;\n"
    ).encode("utf-8")
    files = {"file": ("movimientos.csv", csv_content, "text/csv")}
    preview = client.post(
        f"/api/v1/real/accounts/{account_id}/imports/preview",
        headers=headers,
        files=files,
        data={"date_order": "dmy"},
    )
    assert preview.status_code == 201, preview.text
    data = preview.json()
    assert data["total_rows"] == 2
    assert data["error_rows"] == 0
    assert data["ready_to_confirm"] is True
    assert data["status"] == "preview"
    # La previsualización no registra nada.
    assert (
        client.get(
            f"/api/v1/real/accounts/{account_id}/movements", headers=headers
        ).json()["total"]
        == 0
    )

    confirmed = client.post(
        f"/api/v1/real/accounts/{account_id}/imports/{data['id']}/confirm",
        headers=headers,
        json={},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["created"] == 2
    movements = client.get(
        f"/api/v1/real/accounts/{account_id}/movements", headers=headers
    ).json()
    assert movements["total"] == 2
    summary = client.get(
        f"/api/v1/real/accounts/{account_id}/summary?twr=false", headers=headers
    ).json()
    assert summary["cash_base"] == "7999.00"

    # Reimportar el mismo archivo detecta los duplicados y no crea movimientos.
    again = client.post(
        f"/api/v1/real/accounts/{account_id}/imports/preview",
        headers=headers,
        files={"file": ("movimientos.csv", csv_content, "text/csv")},
    )
    assert again.status_code == 201
    assert again.json()["duplicate_rows"] == 2
    confirm_again = client.post(
        f"/api/v1/real/accounts/{account_id}/imports/{again.json()['id']}/confirm",
        headers=headers,
        json={},
    )
    assert confirm_again.status_code == 200
    assert confirm_again.json()["created"] == 0
    assert confirm_again.json()["skipped_duplicates"] == 2

    other = auth_headers(register(client, email="import2@nexo.invalid")["access_token"])
    assert (
        client.get(
            f"/api/v1/real/accounts/{account_id}/imports/{again.json()['id']}",
            headers=other,
        ).status_code
        == 404
    )


def test_csv_import_invalid_rows_block_confirmation_unless_partial(client):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    _instrument(client, headers)
    account_id = _account(client, headers)
    csv_content = (
        "date,type,symbol,quantity,price,amount\n"
        "2024-01-01,deposit,,,,1000\n"
        "not-a-date,buy,AAPL,1,100,\n"
    ).encode("utf-8")
    preview = client.post(
        f"/api/v1/real/accounts/{account_id}/imports/preview",
        headers=headers,
        files={"file": ("mal.csv", csv_content, "text/csv")},
    )
    assert preview.status_code == 201, preview.text
    assert preview.json()["ready_to_confirm"] is False
    blocked = client.post(
        f"/api/v1/real/accounts/{account_id}/imports/{preview.json()['id']}/confirm",
        headers=headers,
        json={},
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "import_has_errors"
    partial = client.post(
        f"/api/v1/real/accounts/{account_id}/imports/{preview.json()['id']}/confirm",
        headers=headers,
        json={"allow_partial": True},
    )
    assert partial.status_code == 200
    assert partial.json()["created"] == 1
    assert partial.json()["errors"]


def test_document_upload_extract_confirm_and_delete_controls(client, monkeypatch):
    token = register(client, email="doc1@nexo.invalid")["access_token"]
    headers = auth_headers(token)
    uid = _instrument(client, headers)
    account_id = _account(client, headers)
    _movement(
        client,
        headers,
        account_id,
        {"movement_type": "deposit", "movement_date": "2024-01-01", "amount": "1000"},
    )

    def fake_extract(path, content_type):
        del path, content_type
        return Extraction(
            text="Compra AAPL 2 100 USD 01/02/2024",
            engine="fake",
            fields={
                "movement_type": "buy",
                "movement_date": "2024-02-01",
                "symbol": "AAPL",
                "quantity": "2",
                "price": "100",
                "currency": "USD",
            },
        )

    monkeypatch.setattr("app.api.v1.documents.extract", fake_extract)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lK3Q6wAAAABJRU5ErkJggg=="
    )
    upload = client.post(
        "/api/v1/real/documents",
        headers=headers,
        files={"file": ("captura.png", png, "image/png")},
        data={"account_id": str(account_id)},
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["id"]
    assert upload.json()["size_bytes"] == len(png)

    spoofed = client.post(
        "/api/v1/real/documents",
        headers=headers,
        files={"file": ("falso.pdf", b"no soy un pdf", "application/pdf")},
    )
    assert spoofed.status_code == 415
    assert spoofed.json()["error"]["code"] == "content_type_mismatch"

    extracted = client.post(
        f"/api/v1/real/documents/{document_id}/extract", headers=headers
    )
    assert extracted.status_code == 200, extracted.text
    assert extracted.json()["extraction"]["fields"]["symbol"] == "AAPL"
    assert extracted.json()["extraction"]["review_required"] is True
    # Extraer no registra el movimiento.
    assert (
        client.get(
            f"/api/v1/real/accounts/{account_id}/movements", headers=headers
        ).json()["total"]
        == 1
    )

    confirmed = client.post(
        f"/api/v1/real/documents/{document_id}/confirm",
        headers=headers,
        json={
            "account_id": account_id,
            "movement": {
                "movement_type": "buy",
                "movement_date": "2024-02-01",
                "instrument_uid": uid,
                "quantity": "2",
                "price": "100",
            },
        },
    )
    assert confirmed.status_code == 201, confirmed.text
    assert confirmed.json()["movement"]["source"] == "ocr"
    assert confirmed.json()["movement"]["document_id"] == document_id
    assert (
        client.get(
            f"/api/v1/real/accounts/{account_id}/movements", headers=headers
        ).json()["total"]
        == 2
    )
    linked_delete = client.delete(
        f"/api/v1/real/documents/{document_id}", headers=headers
    )
    assert linked_delete.status_code == 409

    other = register(client, email="doc2@nexo.invalid")["access_token"]
    other_headers = auth_headers(other)
    assert client.get("/api/v1/real/documents", headers=other_headers).json()["total"] == 0
    assert (
        client.get(f"/api/v1/real/documents/{document_id}", headers=other_headers).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/real/documents/{document_id}/file", headers=other_headers
        ).status_code
        == 404
    )
