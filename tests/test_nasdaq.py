"""Pruebas del adaptador de la segunda fuente (Nasdaq).

Se trabaja sobre descargas reales congeladas como fixture: ninguna prueba usa red.
Los valores esperados se comprueban contra los documentos guardados, no contra la
implementación.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from nexo_invest.data.nasdaq import (
    NasdaqError,
    financials_from_fixture,
    historical_from_fixture,
    parse_financials,
    parse_historical,
    parse_money,
    parse_nasdaq_date,
)

FIXTURES = Path(__file__).parent / "fixtures"
FINANCIALS = FIXTURES / "nasdaq_aapl_financials.json"
HISTORY = FIXTURES / "nasdaq_aapl_historical_2026-10.json"


# -- parsing de celdas ------------------------------------------------------------------


def test_parse_money_with_thousands_separator():
    assert parse_money("$416,161,000") == 416161000.0
    assert parse_money("12,345") == 12345.0
    assert parse_money("$1,234.5") == 1234.5
    assert parse_money("$-1,000") == -1000.0
    assert parse_money(42) == 42.0


def test_parse_money_vacio_no_es_cero():
    assert parse_money("") is None
    assert parse_money(None) is None
    assert parse_money("   ") is None
    assert parse_money("n/d") is None
    assert parse_money("sin dato") is None
    assert parse_money("-") is None


def test_parse_date_nasdaq():
    assert parse_nasdaq_date("10/27/2026") == date(2026, 10, 27)
    assert parse_nasdaq_date("1/2/2024") == date(2024, 1, 2)
    assert parse_nasdaq_date("2026-10-27") is None
    assert parse_nasdaq_date("") is None
    assert parse_nasdaq_date(None) is None


# -- fixture de estado de resultados -----------------------------------------------------


def test_financials_fixture_estructura():
    table = financials_from_fixture(FINANCIALS, ticker="aapl")
    assert table.ticker == "AAPL"
    # Orden de las columnas tal y como las publica la fuente (más reciente primero).
    assert table.period_endings == [
        date(2025, 9, 27),
        date(2024, 9, 28),
        date(2023, 9, 30),
        date(2022, 9, 24),
    ]
    assert table.row("Total Revenue") == [416161000.0, 391035000.0, 383285000.0, 394328000.0]


def test_financials_fixture_celda_vacia_es_none():
    table = financials_from_fixture(FINANCIALS, ticker="AAPL")
    # «Operating Expenses» es una cabecera sin cifras en el documento original.
    assert table.row("Operating Expenses") == [None, None, None, None]
    assert table.value_for("Operating Expenses", date(2025, 9, 27)) is None


def test_financials_value_desconocido_no_existe():
    table = financials_from_fixture(FINANCIALS, ticker="AAPL")
    # Un periodo que la fuente no publica no se aproxima al más cercano.
    assert table.value_for("Total Revenue", date(2026, 9, 26)) is None
    assert table.value_for("Fila inexistente", date(2025, 9, 27)) is None


def test_financials_fixture_conserva_procedencia():
    table = financials_from_fixture(FINANCIALS, ticker="AAPL")
    digest = hashlib.sha256(FINANCIALS.read_bytes()).hexdigest()
    assert table.source is not None
    assert table.source.hash == digest
    # La URL registrada es la de origen; la copia local queda en las notas.
    assert table.source.url.startswith("https://api.nasdaq.com/")
    assert f"file://{FINANCIALS.as_posix()}" in (table.source.notes or "")
    assert table.source.origin.value == "external_unverified"
    assert any("Copia local congelada" in lim for lim in table.source.limitations)
    assert any("distribución independiente" in lim for lim in table.limitations)


def test_financials_payload_invalido_lanza_error():
    with pytest.raises(NasdaqError):
        parse_financials({"data": {}}, ticker="AAPL")
    with pytest.raises(NasdaqError):
        parse_financials({"data": {"incomeStatementTable": {"headers": {}}}}, ticker="AAPL")


def test_financials_cabeceras_no_fecha_se_ignoran():
    payload = {
        "data": {
            "incomeStatementTable": {
                "headers": {"value1": "Period Ending:", "value2": "n/d", "value3": "9/27/2025"},
                "rows": [{"value1": "Total Revenue", "value2": "100", "value3": "200"}],
            }
        }
    }
    table = parse_financials(payload, ticker="AAPL")
    # Solo la columna con fecha interpretable entra en la tabla.
    assert table.period_endings == [date(2025, 9, 27)]
    assert table.row("Total Revenue") == [200.0]


# -- fixture de cierres -------------------------------------------------------------------


def test_historical_fixture_estructura():
    history = historical_from_fixture(HISTORY, ticker="AAPL")
    assert history.ticker == "AAPL"
    assert len(history.dates) == 19
    # Orden ascendente aunque la fuente envíe primero la sesión más reciente.
    assert history.dates == sorted(history.dates)
    assert history.dates[0] == date(2026, 10, 1)
    assert history.dates[-1] == date(2026, 10, 27)
    assert history.close_on(date(2026, 10, 27)) == 347.10
    assert history.close_on(date(2026, 10, 26)) == 343.91


def test_historical_fecha_no_negociada_devuelve_none():
    history = historical_from_fixture(HISTORY, ticker="AAPL")
    # 2026-10-25 fue domingo: no existe sesión y no se sustituye por el día anterior.
    assert date(2026, 10, 25) not in history.dates
    assert history.close_on(date(2026, 10, 25)) is None


def test_historical_symbol_distinto_se_rechaza():
    payload = json.loads(HISTORY.read_text())
    payload["data"]["symbol"] = "MSFT"
    with pytest.raises(NasdaqError, match="no corresponde al activo"):
        parse_historical(payload, ticker="AAPL")


def test_historical_payload_sin_filas_se_rechaza():
    with pytest.raises(NasdaqError):
        parse_historical({"data": {"symbol": "AAPL", "tradesTable": {"rows": []}}}, ticker="AAPL")


def test_historical_fixture_conserva_procedencia():
    history = historical_from_fixture(HISTORY, ticker="AAPL")
    digest = hashlib.sha256(HISTORY.read_bytes()).hexdigest()
    assert history.source is not None
    assert history.source.hash == digest
    assert history.source.url.startswith("https://api.nasdaq.com/")
    assert f"file://{HISTORY.as_posix()}" in (history.source.notes or "")
    assert history.source.currency == "USD"
    assert history.source.data_type.value == "share_price"
    assert history.fetch is not None and history.fetch.sha256 == digest
