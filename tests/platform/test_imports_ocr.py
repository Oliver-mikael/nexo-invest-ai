"""Normalización de importaciones y extracción local de campos."""

from __future__ import annotations

import io
from datetime import date

from openpyxl import Workbook

from app.services.imports import _parse_date, _parse_decimal, parse_tabular
from app.services.ocr import extract_fields


def test_decimal_parser_distinguishes_prices_from_thousands():
    assert _parse_decimal("1.234", "precio") == _parse_decimal("1.234", "cantidad")
    assert str(_parse_decimal("1.234", "precio")) == "1.234"
    assert str(_parse_decimal("1.234", "importe")) == "1234"
    assert str(_parse_decimal("1.234,56", "importe")) == "1234.56"
    assert str(_parse_decimal("1,234.56", "importe")) == "1234.56"
    assert str(_parse_decimal("(12,50)", "importe")) == "-12.50"


def test_date_parser_honours_explicit_order():
    assert _parse_date("03/04/2024", "dmy") == date(2024, 4, 3)
    assert _parse_date("03/04/2024", "mdy") == date(2024, 3, 4)
    assert _parse_date("2024-04-03", "dmy") == date(2024, 4, 3)


def test_parse_csv_semicolon_and_xlsx():
    headers, records = parse_tabular(
        "movimientos.csv",
        "fecha;tipo;importe\n01/02/2024;deposito;1.234,56\n".encode("utf-8"),
    )
    assert headers == ["fecha", "tipo", "importe"]
    assert records[0]["importe"] == "1.234,56"

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["fecha", "tipo", "importe"])
    sheet.append(["2024-02-01", "deposito", 1000])
    buffer = io.BytesIO()
    workbook.save(buffer)
    headers, records = parse_tabular("movimientos.xlsx", buffer.getvalue())
    assert headers == ["fecha", "tipo", "importe"]
    assert records[0]["tipo"] == "deposito"


def test_ocr_field_extraction_marks_missing_data_instead_of_inventing_it():
    fields = extract_fields(
        "BROKER EJEMPLO\nFecha: 01/02/2024\nCompra AAPL\nCantidad: 10\n"
        "Precio: 200,50 USD\nComisión: 1,25\nTotal: 2.006,25"
    )
    assert fields["movement_type"] == "buy"
    assert fields["movement_date"] == "2024-02-01"
    assert fields["symbol"] == "AAPL"
    assert fields["quantity"] == "10"
    assert fields["price"] == "200.5"
    assert fields["fee"] == "1.25"
    assert fields["amount"] == "2006.25"
    assert fields["currency"] == "USD"


def test_ocr_text_without_fields_returns_empty_proposal():
    fields = extract_fields("Documento sin datos estructurados")
    assert fields == {}
