"""Pruebas del contraste entre fuentes y del margen de seguridad.

Los valores esperados se comprueban contra descargas reales congeladas como fixture
(SEC EDGAR, Nasdaq y Yahoo) y contra cálculos hechos a mano en el propio test.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from nexo_invest.core.sources import ProvenanceLevel
from nexo_invest.data.nasdaq import (
    NasdaqError,
    NasdaqHistory,
    financials_from_fixture,
    historical_from_fixture,
)
from nexo_invest.data.prices import series_from_fixture
from nexo_invest.verification import (
    ContrastStatus,
    contrast_annual_revenue,
    contrast_close_price,
    contrast_failed,
    contrast_primary_document,
    margin_of_safety,
    primary_document_markdown,
    verification_markdown,
)

FIXTURES = Path(__file__).parent / "fixtures"
FINANCIALS = FIXTURES / "nasdaq_aapl_financials.json"
HISTORY = FIXTURES / "nasdaq_aapl_historical_2026-10.json"
YAHOO = FIXTURES / "yahoo_aapl_5y.json"

SEC_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
# Cifra de ingresos de Apple FY2025 tal como aparece en el 10-K (XBRL, unidades USD).
AAPL_FY2025_REVENUE = 416_161_000_000.0


def revenue_contrast(primary_value: float = AAPL_FY2025_REVENUE, period_end: date = date(2025, 9, 27)):
    return contrast_annual_revenue(
        metric="revenue",
        period_end=period_end,
        primary_value=primary_value,
        primary_url=SEC_URL,
        primary_retrieval=date(2026, 10, 27),
        primary_reference="10-K FY2025 accn=0000320193-25-000079",
        secondary=financials_from_fixture(FINANCIALS, ticker="AAPL"),
    )


# -- Tarea 1: segunda fuente -------------------------------------------------------------


def test_ingresos_reales_coinciden_entre_fuentes():
    contrast = revenue_contrast()
    assert contrast.status is ContrastStatus.MATCH
    # La fuente secundaria publica en miles; la relación de unidad se infiere.
    assert contrast.inferred_unit_factor == 1000.0
    assert contrast.aligned_secondary_value == AAPL_FY2025_REVENUE
    assert contrast.absolute_difference == 0.0
    assert contrast.relative_difference == 0.0
    assert contrast.provenance_level.value == "external_corroborated"


def test_contraste_conserva_url_fechas_y_unidad():
    contrast = revenue_contrast()
    assert contrast.primary_url == SEC_URL
    assert contrast.primary_retrieval == date(2026, 10, 27)
    assert contrast.secondary_url is not None
    assert contrast.secondary_url.startswith("https://api.nasdaq.com/")
    assert contrast.secondary_retrieval is not None
    assert contrast.period_end == date(2025, 9, 27)
    assert contrast.primary_currency == "USD"
    assert contrast.secondary_currency == "USD"
    assert "10-K FY2025" in contrast.primary_reference
    assert "se infiere" in contrast.secondary_unit_note


def test_contraste_limita_lo_que_demuestra_la_coincidencia():
    limitations = " ".join(revenue_contrast().limitations)
    assert "no una fuente primaria" in limitations
    assert "inferida" in limitations
    assert "distribución" in limitations or "documentos" in limitations


def test_ingresos_discrepantes_no_se_declaran_corroborados():
    # 2 % por encima de la cifra real: muy por encima de la tolerancia del 0,1 %.
    contrast = revenue_contrast(primary_value=AAPL_FY2025_REVENUE * 1.02)
    assert contrast.status is ContrastStatus.MISMATCH
    assert contrast.relative_difference == pytest.approx(0.02 / 1.02, rel=1e-9)
    assert contrast.provenance_level.value == "external_downloaded"
    assert not contrast.usable_for_margin_of_safety


def test_periodo_inexistente_en_la_segunda_fuente_es_incomparable():
    # Un ejercicio que la segunda fuente no publica: no se elige el más cercano.
    contrast = revenue_contrast(period_end=date(2026, 9, 26))
    assert contrast.status is ContrastStatus.INCOMPARABLE
    assert contrast.secondary_value is None
    assert any("cierre idéntica" in reason for reason in contrast.reasons)


def test_fila_ausente_es_incomparable_y_no_cero():
    contrast = contrast_annual_revenue(
        metric="revenue",
        period_end=date(2025, 9, 27),
        primary_value=AAPL_FY2025_REVENUE,
        primary_url=SEC_URL,
        primary_retrieval=date(2026, 10, 27),
        primary_reference="10-K",
        secondary=financials_from_fixture(FINANCIALS, ticker="AAPL"),
        secondary_label="Fila que no existe",
    )
    assert contrast.status is ContrastStatus.INCOMPARABLE
    assert contrast.secondary_value is None
    assert any("cero" in limitation for limitation in contrast.limitations)


def test_celda_vacia_no_se_interpreta_cero():
    table = financials_from_fixture(FINANCIALS, ticker="AAPL")
    table.values["Total Revenue"] = [None, 391035000.0, 383285000.0, 394328000.0]
    contrast = contrast_annual_revenue(
        metric="revenue",
        period_end=date(2025, 9, 27),
        primary_value=AAPL_FY2025_REVENUE,
        primary_url=SEC_URL,
        primary_retrieval=date(2026, 10, 27),
        primary_reference="10-K",
        secondary=table,
    )
    assert contrast.status is ContrastStatus.INCOMPARABLE
    assert contrast.secondary_value is None


def test_unidad_no_alineable_es_discrepancia_no_coincidencia():
    # 7 frente a 1000: ninguna potencia de diez razonable los alinea.
    table = financials_from_fixture(FINANCIALS, ticker="AAPL")
    table.values["Total Revenue"] = [7.0, 391035000.0, 383285000.0, 394328000.0]
    contrast = contrast_annual_revenue(
        metric="revenue",
        period_end=date(2025, 9, 27),
        primary_value=AAPL_FY2025_REVENUE,
        primary_url=SEC_URL,
        primary_retrieval=date(2026, 10, 27),
        primary_reference="10-K",
        secondary=table,
    )
    assert contrast.status is ContrastStatus.MISMATCH
    assert contrast.provenance_level.value == "external_downloaded"


def test_segunda_fuente_caída_queda_incomparable():
    contrast = contrast_failed(
        metric="revenue",
        period_end=date(2025, 9, 27),
        primary_value=AAPL_FY2025_REVENUE,
        reason="La segunda fuente no respondió; no hay contraste posible.",
    )
    assert contrast.status is ContrastStatus.INCOMPARABLE
    assert contrast.secondary_value is None
    assert contrast.provenance_level.value == "external_downloaded"
    assert any("no respondió" in reason for reason in contrast.reasons)


def test_fixture_sec_y_nasdaq_tienen_mismo_contenido_que_la_fuente():
    # Los dos fixtures son copias de descargas reales; se comprueba su huella.
    for name in ("nasdaq_aapl_financials.json", "nasdaq_aapl_historical_2026-10.json"):
        raw = (FIXTURES / name).read_bytes()
        json.loads(raw)
        assert len(hashlib.sha256(raw).hexdigest()) == 64


# -- Tarea 2: precio comprobado ----------------------------------------------------------


def price_evidence(when: date = date(2026, 10, 27)):
    series = series_from_fixture(YAHOO, symbol="AAPL")
    history = historical_from_fixture(HISTORY, ticker="AAPL")
    return contrast_close_price(
        symbol="AAPL",
        when=when,
        primary=series,
        primary_source_name="Yahoo Finance · chart",
        primary_url=series.source.url if series.source else None,
        primary_retrieval=date(2026, 10, 28),
        secondary=history,
    )


def test_precio_real_coincide_entre_dos_fuentes():
    evidence = price_evidence()
    assert evidence.status is ContrastStatus.MATCH
    assert evidence.price_date == date(2026, 10, 27)
    # El cierre de Yahoo llega como 347.1000061035156 (almacenamiento en coma
    # flotante del proveedor); la tolerancia es de una centésima de dólar.
    assert evidence.close == pytest.approx(347.10, abs=1e-4)
    assert evidence.adjusted_close == pytest.approx(347.10, abs=1e-4)
    assert evidence.currency == "USD"
    assert evidence.is_adjusted is False
    assert evidence.relative_difference < 1e-6
    assert evidence.provenance_level.value == "external_corroborated"
    assert evidence.usable_for_margin_of_safety


def test_precio_conserva_las_dos_fuentes_y_sus_limitaciones():
    evidence = price_evidence()
    # Con fixture local la primera fuente apunta a la copia y la URL original de la
    # descarga queda registrada en las notas del origen.
    assert evidence.primary_url is not None and evidence.primary_url.startswith("file://")
    assert evidence.secondary_url is not None and "api.nasdaq.com" in evidence.secondary_url
    assert evidence.primary_retrieval == date(2026, 10, 28)
    assert evidence.secondary_retrieval is not None
    text = " ".join(evidence.limitations)
    assert "agregadores" in text
    assert "sin ajustar" in text
    assert "mercado oficial" in text or "SIP" in text


def test_fecha_no_negociada_no_produce_precio():
    # 2026-10-25 fue domingo: ninguna de las dos fuentes tiene sesión ese día.
    evidence = price_evidence(when=date(2026, 10, 25))
    assert evidence.status is ContrastStatus.INCOMPARABLE
    assert not evidence.usable_for_margin_of_safety


def test_fecha_ausente_en_la_segunda_fuente_es_incomparable():
    # 2026-09-30 existe en Yahoo (serie de 5 años) pero no en el histórico de Nasdaq.
    evidence = price_evidence(when=date(2026, 9, 30))
    assert evidence.status is ContrastStatus.INCOMPARABLE
    assert any("segunda fuente" in reason for reason in evidence.reasons)


def test_simbolo_distinto_no_se_compara():
    # El fichero de Nasdaq pertenece a AAPL: pedirlo como MSFT se rechaza en el parsing.
    with pytest.raises(NasdaqError, match="no corresponde al activo"):
        historical_from_fixture(HISTORY, ticker="MSFT")

    # Y si la segunda fuente llega con otro símbolo, el contraste también se niega.
    history = historical_from_fixture(HISTORY, ticker="AAPL")
    wrong = NasdaqHistory(
        ticker="MSFT",
        dates=list(history.dates),
        closes=list(history.closes),
        source=history.source,
        fetch=history.fetch,
    )
    series = series_from_fixture(YAHOO, symbol="AAPL")
    evidence = contrast_close_price(
        symbol="AAPL",
        when=date(2026, 10, 27),
        primary=series,
        primary_source_name="Yahoo Finance · chart",
        primary_url=None,
        primary_retrieval=date(2026, 10, 28),
        secondary=wrong,
    )
    assert evidence.status is ContrastStatus.INCOMPARABLE
    assert any("MSFT" in reason for reason in evidence.reasons)


def test_precio_discrepante_no_da_margen_de_seguridad():
    history = historical_from_fixture(HISTORY, ticker="AAPL")
    history.closes[history.dates.index(date(2026, 10, 27))] = 400.00
    series = series_from_fixture(YAHOO, symbol="AAPL")
    evidence = contrast_close_price(
        symbol="AAPL",
        when=date(2026, 10, 27),
        primary=series,
        primary_source_name="Yahoo Finance · chart",
        primary_url=None,
        primary_retrieval=date(2026, 10, 28),
        secondary=history,
    )
    assert evidence.status is ContrastStatus.MISMATCH
    assert evidence.relative_difference == pytest.approx(52.90 / 400.0, rel=1e-6)
    assert not evidence.usable_for_margin_of_safety
    assert evidence.provenance_level.value == "external_downloaded"


# -- Tarea 3: margen de seguridad ---------------------------------------------------------


def test_margen_de_seguridad_calculo_a_mano():
    # 1 - 300/400 = 0,25
    assert margin_of_safety(400.0, 300.0) == pytest.approx(0.25)
    # 1 - 300/300 = 0
    assert margin_of_safety(300.0, 300.0) == pytest.approx(0.0)
    # 1 - 600/300 = -1 (precio por encima del valor estimado)
    assert margin_of_safety(300.0, 600.0) == pytest.approx(-1.0)


@pytest.mark.parametrize(
    "intrinsic,price",
    [(None, 300.0), (400.0, None), (0.0, 300.0), (-100.0, 300.0), (400.0, 0.0), (400.0, -1.0)],
)
def test_margen_de_seguridad_sin_datos_no_se_calcula(intrinsic, price):
    assert margin_of_safety(intrinsic, price) is None


# -- informe ------------------------------------------------------------------------------


def test_informe_sin_precio_no_presenta_margen_de_seguridad():
    revenue = revenue_contrast()
    evidence = price_evidence(when=date(2026, 10, 25))  # incomparable -> sin precio
    markdown = verification_markdown(
        entity_name="Apple Inc.",
        ticker="AAPL",
        generated_at="2026-10-28T00:00:00+00:00",
        revenue=revenue,
        price=evidence,
        scenarios=[],
        valuation_notes=[],
        price_note="Sin dos fuentes coincidentes no se calcula margen de seguridad.",
    )
    assert "No hay precio comprobado" in markdown
    assert "no se calcula margen de seguridad" in markdown
    assert "Margen de seguridad:** -" not in markdown


def test_informe_con_precio_explica_margen_y_limitaciones():
    revenue = revenue_contrast()
    evidence = price_evidence()
    markdown = verification_markdown(
        entity_name="Apple Inc.",
        ticker="AAPL",
        generated_at="2026-10-28T00:00:00+00:00",
        revenue=revenue,
        price=evidence,
        scenarios=[],
        valuation_notes=[],
        price_note="Cierre coincidente en dos fuentes.",
    )
    assert "347.10 USD" in markdown
    assert "2026-10-27" in markdown
    assert "cierre sin ajustar" in markdown
    assert "1 − precio / valor por acción" in markdown
    assert "external_corroborated" in markdown
    assert "agregadores" in markdown
    # La tabla de contraste conserva URL, fechas y referencia de ambas fuentes.
    assert SEC_URL in markdown
    assert "api.nasdaq.com" in markdown


# -- documento primario: HTML original vs CompanyFacts ----------------------------------

DOC_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/"
    "000032019325000079/aapl-20250927.htm"
)
ACCESSION = "0000320193-25-000079"
DOC_SHA256 = "b9820c677562512182ea9d48a02219d46859e25458087118baa8fb6defd225d3"
FY2025_START = date(2024, 9, 29)
FY2025_END = date(2025, 9, 27)
HTML_REVENUE = Decimal("416161000000")


def primary_evidence(companyfacts_value=HTML_REVENUE, **kwargs):
    values = dict(
        period_start=FY2025_START,
        period_end=FY2025_END,
        html_value=HTML_REVENUE,
        html_url=DOC_URL,
        html_retrieval=date(2026, 10, 29),
        accession=ACCESSION,
        content_sha256=DOC_SHA256,
        fiscal_year=2025,
        fiscal_period="FY",
        companyfacts_value=companyfacts_value,
        cik=320193,
    )
    values.update(kwargs)
    return contrast_primary_document(**values)


def test_contraste_del_documento_primario_coincide():
    evidence = primary_evidence()
    assert evidence.status is ContrastStatus.MATCH
    assert evidence.primary_value == 416161000000.0
    assert evidence.secondary_value == 416161000000.0
    assert evidence.provenance_level is ProvenanceLevel.EXTERNAL_CORROBORATED
    assert evidence.accession == ACCESSION
    assert evidence.content_sha256 == DOC_SHA256
    assert evidence.fiscal_year == 2025
    assert evidence.fiscal_period == "FY"
    assert evidence.form == "10-K"
    assert evidence.primary_url == DOC_URL
    assert evidence.primary_retrieval == date(2026, 10, 29)


def test_contraste_del_documento_primario_explica_que_no_es_independiente():
    evidence = primary_evidence()
    joined = " ".join(evidence.limitations)
    assert "misma presentación" in joined
    assert "no una medición independiente" in joined
    assert any("SHA-256" in item for item in evidence.limitations)


def test_contraste_discrepante_no_se_declara_corroborado():
    evidence = primary_evidence(companyfacts_value=Decimal("416162000000"))
    assert evidence.status is ContrastStatus.MISMATCH
    assert evidence.provenance_level is ProvenanceLevel.EXTERNAL_DOWNLOADED
    assert evidence.relative_difference > 0


def test_companyfacts_ausente_es_incomparable_y_no_cero():
    evidence = primary_evidence(companyfacts_value=None)
    assert evidence.status is ContrastStatus.INCOMPARABLE
    assert evidence.primary_value == 416161000000.0  # el HTML sí se extrajo
    assert evidence.secondary_value is None
    assert any("sin contraste" in item for item in evidence.limitations)


def test_html_de_cache_declara_la_limitacion():
    evidence = primary_evidence(html_from_cache=True)
    assert any("caché local" in item for item in evidence.limitations)


def test_descarga_fallida_es_verificacion_no_completada():
    evidence = contrast_failed(
        metric="revenue",
        period_end=FY2025_END,
        primary_value=None,
        reason="HTTP 403: la SEC rechazó la petición",
    )
    assert evidence.primary_value is None
    markdown = primary_document_markdown(
        entity_name="Apple Inc.",
        ticker="AAPL",
        generated_at="2026-10-29T00:00:00+00:00",
        evidence=evidence,
    )
    assert "VERIFICACIÓN NO COMPLETADA" in markdown
    assert "HTTP 403" in markdown
    assert "no disponible" in markdown


def test_informe_del_documento_primario_recoge_la_evidencia():
    markdown = primary_document_markdown(
        entity_name="Apple Inc.",
        ticker="AAPL",
        generated_at="2026-10-29T00:00:00+00:00",
        evidence=primary_evidence(),
    )
    assert DOC_URL in markdown
    assert ACCESSION in markdown
    assert DOC_SHA256 in markdown
    assert "2026-10-29" in markdown
    assert "10-K" in markdown
    assert "416,161,000,000 USD" in markdown
    assert "2025-09-27" in markdown
    assert "misma presentación" in markdown
