"""Prueba de integración de los comandos `nexo verify` y `nexo primary-verify` sin red.

Se sustituyen las fuentes por las descargas reales congeladas como fixture, de
modo que el flujo completo (fuente primaria → contraste con la segunda fuente →
precio comprobado → valoración → auditoría de la prueba histórica → informe) se
ejecuta entero y se comprueba su salida. Si el comando dependiera de la red o
mintiera resultados, estas pruebas lo delatarían.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


from nexo_invest.cli import main
from nexo_invest.data.nasdaq import (
    NasdaqClient,
    NasdaqError,
    financials_from_fixture,
    historical_from_fixture,
)
from nexo_invest.data.prices import YahooPriceClient, series_from_fixture
from nexo_invest.data.sec_edgar import FetchRecord, SecEdgarClient

FIXTURES = Path(__file__).parent / "fixtures"
SEC_PAYLOAD = FIXTURES / "sec_companyfacts_aapl_subset.json"
FINANCIALS = FIXTURES / "nasdaq_aapl_financials.json"
HISTORY = FIXTURES / "nasdaq_aapl_historical_2026-10.json"
YAHOO = FIXTURES / "yahoo_aapl_5y.json"
SEC_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"


def _sec_record() -> FetchRecord:
    return FetchRecord(
        url=SEC_URL,
        retrieved_at=datetime(2026, 10, 27, tzinfo=timezone.utc),
        status=200,
        bytes_received=SEC_PAYLOAD.stat().st_size,
        sha256="73a86c6aedc31f77cac2ea4df5f80f0b3bd7e6eb58bb4e01444fbedf3afb9c43",
        from_cache=True,
    )


def _patch_sec(monkeypatch) -> None:
    payload = json.loads(SEC_PAYLOAD.read_text())
    record = _sec_record()
    monkeypatch.setattr(SecEdgarClient, "resolve_cik", lambda self, ticker: 320193)
    monkeypatch.setattr(
        SecEdgarClient, "company_facts", lambda self, cik: (payload, record)
    )


def _patch_nasdaq(monkeypatch) -> None:
    monkeypatch.setattr(
        NasdaqClient,
        "financials",
        lambda self, ticker: financials_from_fixture(FINANCIALS, ticker=ticker),
    )
    monkeypatch.setattr(
        NasdaqClient,
        "historical",
        lambda self, ticker, start, end, limit=4000: historical_from_fixture(
            HISTORY, ticker=ticker
        ),
    )


def _patch_yahoo(monkeypatch) -> None:
    monkeypatch.setattr(
        YahooPriceClient,
        "fetch_series",
        lambda self, symbol, **kwargs: series_from_fixture(YAHOO, symbol=symbol),
    )


def _run(tmp_path: Path, *extra: str) -> tuple:
    out = tmp_path / "verify.md"
    code = main(
        ["verify", "--ticker", "AAPL", "--out", str(out), "--backtest-fixture", str(YAHOO), *extra]
    )
    return code, out.read_text(encoding="utf-8") if out.exists() else ""


def test_verify_end_to_end_con_dos_fuentes(monkeypatch, tmp_path, capsys):
    _patch_sec(monkeypatch)
    _patch_nasdaq(monkeypatch)
    _patch_yahoo(monkeypatch)

    code, markdown = _run(tmp_path, "--price-date", "2026-10-27")

    assert code == 0
    # Contraste de ingresos con evidencia completa.
    assert "coincide con la segunda fuente" in markdown
    assert "416,161,000,000 USD" in markdown
    assert SEC_URL in markdown
    assert "api.nasdaq.com" in markdown
    assert "unidad inferida" in markdown
    assert "no una fuente primaria" in markdown

    # Precio comprobado en dos fuentes para la fecha pedida.
    assert "2026-10-27" in markdown
    assert "347.10 USD" in markdown
    assert "external_corroborated" in markdown
    assert "cierre sin ajustar" in markdown

    # Valoración con fórmulas declaradas y margen de seguridad con interpretación.
    assert "Valor estimado por acción" in markdown
    assert "1 − precio / valor por acción" in markdown
    assert "Margen de seguridad" in markdown
    assert "**negativo**" in markdown
    for scenario in ("bajista", "base", "alcista"):
        assert scenario in markdown

    # Auditoría de la prueba histórica incluida en el informe.
    assert "ausencia de sesgo de anticipación" in markdown
    assert "no supera" in markdown

    # La salida por pantalla refleja la subida de nivel de la cifra primaria.
    stdout = capsys.readouterr().out
    assert "external_corroborated" in stdout
    assert "fuentes en el registro: 26" in stdout


def test_verify_con_segunda_fuente_caída_no_mintiera(monkeypatch, tmp_path, capsys):
    _patch_sec(monkeypatch)
    _patch_yahoo(monkeypatch)

    def _explode(self, *args, **kwargs):
        raise NasdaqError("Timeout simulado")

    monkeypatch.setattr(NasdaqClient, "financials", _explode)
    monkeypatch.setattr(NasdaqClient, "historical", _explode)

    code, markdown = _run(tmp_path)

    # Estado seguro: informe escrito, pero sin corrobación ni precio ni margen.
    assert code == 0
    assert "no comparable con la segunda fuente" in markdown
    assert "no hay contraste posible" in markdown
    assert "No hay precio comprobado" in markdown
    assert "Margen de seguridad:** -" not in markdown
    assert "coincide con la segunda fuente" not in markdown

    stdout = capsys.readouterr().out
    assert "external_validated" in stdout  # no se promovió sin segunda fuente
    assert "sin dos fuentes coincidentes" in stdout


def test_verify_fecha_no_negociada_no_calcula_margen(monkeypatch, tmp_path, capsys):
    _patch_sec(monkeypatch)
    _patch_nasdaq(monkeypatch)
    _patch_yahoo(monkeypatch)

    code, markdown = _run(tmp_path, "--price-date", "2026-10-25")

    assert code == 0
    assert "No hay precio comprobado" in markdown
    assert "2026-10-25" in markdown
    assert "no tiene sesión con fecha" in markdown
    assert "Margen de seguridad:** -" not in markdown
    # Los ingresos sí quedan contrastados: el precio no arrastra al resto.
    assert "coincide con la segunda fuente" in markdown


def test_verify_sin_fixture_de_backtest_escribe_informe(monkeypatch, tmp_path):
    _patch_sec(monkeypatch)
    _patch_nasdaq(monkeypatch)
    _patch_yahoo(monkeypatch)

    out = tmp_path / "sin-backtest.md"
    code = main(
        ["verify", "--ticker", "AAPL", "--out", str(out), "--price-date", "2026-10-27"]
    )
    assert code == 0
    markdown = out.read_text(encoding="utf-8")
    assert "coincide con la segunda fuente" in markdown
    assert "ausencia de sesgo de anticipación" not in markdown


# -- comando primary-verify ----------------------------------------------------------

PRIMARY_HTML = FIXTURES / "inline_xbrl" / "sample_10k.htm"
PRIMARY_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/"
    "000032019325000079/sample-20250927.htm"
)
PRIMARY_ACCESSION = "0000320193-25-000079"
PRIMARY_CONTACT = "analista@dominio-real.com"


def _doc_record() -> FetchRecord:
    raw = PRIMARY_HTML.read_bytes()
    return FetchRecord(
        url=PRIMARY_URL,
        retrieved_at=datetime(2026, 10, 29, tzinfo=timezone.utc),
        status=200,
        bytes_received=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        from_cache=False,
        content_type="text/html",
    )


def _patch_primary(monkeypatch, html: bytes | None = None) -> None:
    payload = json.loads(SEC_PAYLOAD.read_text())
    raw = PRIMARY_HTML.read_bytes() if html is None else html
    monkeypatch.setattr(
        SecEdgarClient,
        "get_document",
        lambda self, url, use_cache=True: (raw, _doc_record()),
    )
    monkeypatch.setattr(
        SecEdgarClient, "company_facts", lambda self, cik: (payload, _sec_record())
    )


def _run_primary(tmp_path: Path, *extra: str) -> tuple:
    out = tmp_path / "primary.md"
    code = main(
        [
            "primary-verify",
            "--ticker",
            "AAPL",
            "--cik",
            "320193",
            "--accession",
            PRIMARY_ACCESSION,
            "--url",
            PRIMARY_URL,
            "--fiscal-year",
            "2025",
            "--period-start",
            "2024-09-29",
            "--period-end",
            "2025-09-27",
            "--out",
            str(out),
            *extra,
        ]
    )
    return code, out


def test_primary_verify_end_to_end_sin_red(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("NEXO_SEC_CONTACT", PRIMARY_CONTACT)
    _patch_primary(monkeypatch)

    code, out = _run_primary(tmp_path)

    assert code == 0
    markdown = out.read_text(encoding="utf-8")
    assert "VERIFICADA" in markdown
    assert PRIMARY_URL in markdown
    assert PRIMARY_ACCESSION in markdown
    assert "10-K" in markdown
    assert "416,161,000,000 USD" in markdown
    assert "misma presentación" in markdown
    assert hashlib.sha256(PRIMARY_HTML.read_bytes()).hexdigest() in markdown
    captured = capsys.readouterr()
    assert "Resultado:" in captured.out


def test_primary_verify_sin_contacto_no_inventa_una_descarga(monkeypatch, tmp_path):
    monkeypatch.delenv("NEXO_SEC_CONTACT", raising=False)

    def boom(*args, **kwargs):
        raise AssertionError("no debería descargarse nada sin contacto real")

    monkeypatch.setattr(SecEdgarClient, "get_document", boom)

    code, out = _run_primary(tmp_path)

    assert code == 1
    markdown = out.read_text(encoding="utf-8")
    assert "VERIFICACIÓN NO COMPLETADA" in markdown
    assert "NEXO_SEC_CONTACT" in markdown


def test_primary_verify_documento_invalido_no_declara_exito(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXO_SEC_CONTACT", PRIMARY_CONTACT)
    _patch_primary(monkeypatch, html=b"<html><body>Access Denied</body></html>")

    code, out = _run_primary(tmp_path)

    assert code == 1
    markdown = out.read_text(encoding="utf-8")
    assert "VERIFICACIÓN NO COMPLETADA" in markdown
    assert "Inline XBRL" in markdown
    assert "416,161,000,000" not in markdown, "no se inventa una cifra extraída"
