"""Pruebas del adaptador de SEC EDGAR.

Ninguna prueba de este fichero hace peticiones de red: se usa el subconjunto real
guardado en `tests/fixtures/sec_companyfacts_aapl_subset.json`, documentado en
`tests/fixtures/README.md`.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from nexo_invest.core.sources import (
    DataOrigin,
    ProvenanceLevel,
    ProvenanceRegistry,
)
from nexo_invest.core.units import Frequency, Money, Scale
from nexo_invest.data.sec_edgar import (
    ACCEPT_HTML,
    ACCEPT_JSON,
    CONCEPT_MAP,
    DEFAULT_CONTACT_PLACEHOLDER,
    ContactNotConfiguredError,
    FetchRecord,
    PrimaryDocumentError,
    SecEdgarClient,
    SecEdgarError,
    build_registry_from_companyfacts,
    companyfacts_fact_value,
    extract_observations,
    parse_primary_document,
    period_from_fact,
    select_annual_facts,
    select_quarterly_facts,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sec_companyfacts_aapl_subset.json"
HTML_10K = Path(__file__).parent / "fixtures" / "inline_xbrl" / "sample_10k.htm"
DOC_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/"
    "000032019325000079/sample-20250927.htm"
)
ACCESSION = "0000320193-25-000079"
REAL_CONTACT = "analista@dominio-real.com"


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fetch_record() -> FetchRecord:
    return FetchRecord(
        url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        retrieved_at=date(2026, 10, 27).isoformat() and __import__("datetime").datetime(2026, 10, 27, 12, 0, tzinfo=__import__("datetime").timezone.utc),
        status=200,
        bytes_received=FIXTURE.stat().st_size,
        sha256="73a86c6aedc31f77cac2ea4df5f80f0b3bd7e6eb58bb4e01444fbedf3afb9c43",
        from_cache=False,
    )


@pytest.fixture(scope="module")
def result(payload, fetch_record):
    return build_registry_from_companyfacts(
        payload, cik=320193, fetch_records=[fetch_record]
    )


class TestExtraction:
    def test_entity_and_cik_come_from_payload(self, result):
        assert result.entity_name == "Apple Inc."
        assert result.cik == 320193

    def test_only_mapped_metrics_are_extracted(self, payload):
        facts = extract_observations(payload)
        assert set(facts).issubset(set(CONCEPT_MAP))
        assert "revenue" in facts

    def test_annual_and_quarterly_are_separated(self, payload):
        facts = extract_observations(payload)
        annual = select_annual_facts(facts["revenue"])
        quarterly = select_quarterly_facts(facts["revenue"])
        assert annual, "debe haber hechos anuales reales"
        assert quarterly, "debe haber hechos trimestrales reales"
        for fact in annual:
            assert 330 <= (fact.end - fact.start).days <= 400
        for fact in quarterly:
            assert 80 <= (fact.end - fact.start).days <= 100

    def test_ytd_accumulated_never_treated_as_quarter(self, payload):
        """Los periodos YTD (6 y 9 meses) no deben clasificarse como trimestrales."""

        facts = extract_observations(payload)
        quarters = select_quarterly_facts(facts["revenue"])
        for fact in quarters:
            assert (fact.end - fact.start).days <= 100
        # los YTD siguen existiendo en el conjunto, pero no se usan como trimestre
        ytd = [
            f
            for f in facts["revenue"]
            if f.start and 150 <= (f.end - f.start).days <= 290
        ]
        assert ytd, "el fixture contiene periodos YTD reales"
        assert all(f not in quarters for f in ytd)

    def test_period_frequency_from_days(self, payload):
        facts = extract_observations(payload)
        annual = select_annual_facts(facts["revenue"])[-1]
        quarterly = select_quarterly_facts(facts["revenue"])[-1]
        assert period_from_fact(annual).frequency is Frequency.ANNUAL
        assert period_from_fact(quarterly).frequency is Frequency.QUARTERLY

    def test_flow_without_start_is_rejected(self):
        synthetic = {
            "cik": 1,
            "entityName": "Sin inicio",
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {"USD": [{"end": "2024-12-31", "val": 100, "form": "10-K"}]}
                    }
                }
            },
        }
        assert extract_observations(synthetic) == {}

    def test_non_sec_form_is_ignored(self):
        synthetic = {
            "cik": 1,
            "entityName": "Formulario raro",
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "units": {
                            "USD": [
                                {"end": "2024-12-31", "val": 100, "form": "8-K"},
                                {"end": "2024-12-31", "val": 100, "form": "10-K"},
                            ]
                        }
                    }
                }
            },
        }
        facts = extract_observations(synthetic)
        assert len(facts["total_assets"]) == 1
        assert facts["total_assets"][0].form == "10-K"


class TestProvenance:
    def test_download_is_not_verified_data(self, result):
        for obs in result.registry.observations.values():
            assert obs.value_origin is DataOrigin.EXTERNAL_UNVERIFIED
            assert obs.is_verified is False

    def test_levels_are_downloaded_or_better(self, result):
        levels = {obs.effective_provenance_level for obs in result.registry.observations.values()}
        assert levels <= {
            ProvenanceLevel.EXTERNAL_DOWNLOADED,
            ProvenanceLevel.EXTERNAL_VALIDATED,
            ProvenanceLevel.EXTERNAL_CORROBORATED,
        }
        assert ProvenanceLevel.EXTERNAL_VALIDATED in levels
        assert ProvenanceLevel.EXTERNAL_CORROBORATED in levels
        assert ProvenanceLevel.LOCAL_FIXTURE not in levels
        assert ProvenanceLevel.SYNTHETIC not in levels

    def test_source_keeps_url_hash_and_date(self, result):
        for source in result.registry.sources.values():
            assert source.url == "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
            assert source.retrieval_date == date(2026, 10, 27)
            assert source.hash == "73a86c6aedc31f77cac2ea4df5f80f0b3bd7e6eb58bb4e01444fbedf3afb9c43"
            assert source.origin is DataOrigin.EXTERNAL_UNVERIFIED

    def test_observation_notes_keep_accession_and_form(self, result):
        obs = result.registry.observations_for_metric("revenue")[-1]
        assert "form=10-K" in (obs.notes or "")
        assert "accn=" in (obs.notes or "")

    def test_inconsistent_period_is_withheld_not_hidden(self):
        """Un balance que no cuadra debe quedarse en 'descargado' y decirlo."""

        payload = {
            "cik": 5,
            "entityName": "Empresa Cuadre",
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "units": {
                            "USD": [
                                {"end": "2023-12-31", "val": 1000, "form": "10-K", "fy": 2023, "fp": "FY", "filed": "2024-02-01"},
                                {"end": "2024-12-31", "val": 1200, "form": "10-K", "fy": 2024, "fp": "FY", "filed": "2025-02-01"},
                            ]
                        }
                    },
                    "Liabilities": {
                        "units": {
                            "USD": [
                                {"end": "2023-12-31", "val": 400, "form": "10-K", "fy": 2023, "fp": "FY", "filed": "2024-02-01"},
                                {"end": "2024-12-31", "val": 500, "form": "10-K", "fy": 2024, "fp": "FY", "filed": "2025-02-01"},
                            ]
                        }
                    },
                    "StockholdersEquity": {
                        "units": {
                            "USD": [
                                {"end": "2023-12-31", "val": 600, "form": "10-K", "fy": 2023, "fp": "FY", "filed": "2024-02-01"},
                                {"end": "2024-12-31", "val": 800, "form": "10-K", "fy": 2024, "fp": "FY", "filed": "2025-02-01"},
                            ]
                        }
                    },
                }
            },
        }
        res = build_registry_from_companyfacts(payload, cik=5, fetch_records=[])
        assets = {o.period.end: o for o in res.registry.observations_for_metric("total_assets")}
        assert assets[date(2023, 12, 31)].effective_provenance_level is ProvenanceLevel.EXTERNAL_VALIDATED
        assert assets[date(2024, 12, 31)].effective_provenance_level is ProvenanceLevel.EXTERNAL_DOWNLOADED
        assert "2024-12-31" in assets[date(2024, 12, 31)].notes
        assert "identidad contable" in assets[date(2024, 12, 31)].notes
        assert any("2024-12-31" in n for n in res.validation_notes)

    def test_validation_promotes_most_metrics(self, result):
        assert "revenue" in result.validated_metrics
        assert len(result.validated_metrics) >= 15

    def test_corroboration_is_declared_as_internal(self, result):
        assert result.corroborated_metrics, "debe existir al menos una corroboración aritmética"
        any_note = "\n".join(result.validation_notes)
        assert "corroborad" in any_note
        joined = " ".join(result.limitations)
        assert "no una segunda fuente independiente" in joined


class TestRegistryIntegration:
    def test_balance_and_cash_flow_reach_financial_state(self, result):
        state = result.registry.to_financial_state()
        assert state.balance_sheets, "el balance real debe llegar al estado financiero"
        assert state.cash_flows, "el flujo de caja real debe llegar al estado financiero"

    def test_annual_revenue_values_match_filings(self, result):
        """Cifras contrastables: ingresos anuales de Apple en sus 10-K."""

        obs = {o.period.end: o for o in result.registry.observations_for_metric("revenue")}
        expected = {
            date(2022, 9, 24): 394_328_000_000,
            date(2023, 9, 30): 383_285_000_000,
            date(2024, 9, 28): 391_035_000_000,
        }
        for end, value in expected.items():
            assert end in obs, f"falta el ejercicio cerrado en {end}"
            assert obs[end].value.value == pytest.approx(value)

    def test_ttm_is_none_when_only_three_consecutive_quarters_exist(self, result):
        """Sin cuatro trimestres consecutivos el TTM debe ser None y no estimarse."""

        from nexo_invest.core.metrics import FinancialMetrics
        from nexo_invest.core.periods import FiscalCalendar

        state = result.registry.to_financial_state()
        metrics = FinancialMetrics.from_state(
            state,
            latest_end=date(2024, 6, 29),
            fiscal_calendar=FiscalCalendar(close_month=9),
        )
        quarters = [
            o
            for o in result.registry.observations_for_metric("revenue")
            if o.period.frequency is Frequency.QUARTERLY and o.period.end <= date(2024, 6, 29)
        ]
        assert len(quarters) >= 3, "el fixture debe contener trimestres reales de 10-Q"
        assert metrics.revenue_ttm is None, "no se puede sumar un TTM sin cuatro trimestres"

    def test_ttm_with_reported_quarters_equals_reported_annual(self, result):
        """TTM de cuatro trimestres consecutivos = cifra anual presentada.

        Apple no presenta un 10-Q para su cuarto trimestre, así que el cuarto se
        obtiene con la transformación documentada `anual - tres trimestres`. El valor
        derivado se registra explícitamente como derivado y el TTM resultante debe
        coincidir con los ingresos anuales presentados en el 10-K.
        """

        from nexo_invest.core.metrics import FinancialMetrics
        from nexo_invest.core.periods import FiscalCalendar
        from nexo_invest.core.units import Period as P

        annual = {
            o.period.end: o
            for o in result.registry.observations_for_metric("revenue")
            if o.period.frequency is Frequency.ANNUAL
        }
        quarters = sorted(
            [
                o
                for o in result.registry.observations_for_metric("revenue")
                if o.period.frequency is Frequency.QUARTERLY
                and date(2023, 10, 1) <= o.period.start
                and o.period.end <= date(2024, 6, 29)
            ],
            key=lambda o: o.period.end,
        )
        assert len(quarters) == 3, f"se esperaban 3 trimestres de 10-Q, hay {len(quarters)}"
        fy2024 = annual[date(2024, 9, 28)]
        three = sum(o.value.value for o in quarters)
        derived_q4 = fy2024.value.value - three
        assert derived_q4 > 0

        result.registry.observation(
            source_id=fy2024.source.id,
            metric="revenue",
            period=P(start=date(2024, 6, 30), end=date(2024, 9, 28), frequency=Frequency.QUARTERLY),
            value=Money(derived_q4, "USD", Scale.UNITS, label="derivado_q4"),
            value_origin=DataOrigin.EXTERNAL_UNVERIFIED,
            verified=False,
            notes="derivado: ingresos anuales 10-K menos la suma de los tres 10-Q",
            provenance_level=ProvenanceLevel.EXTERNAL_VALIDATED,
        )
        state = result.registry.to_financial_state()
        metrics = FinancialMetrics.from_state(
            state,
            latest_end=date(2024, 9, 28),
            fiscal_calendar=FiscalCalendar(close_month=9),
        )
        assert metrics.revenue_ttm is not None
        assert metrics.revenue_ttm.value == pytest.approx(fy2024.value.value)

    def test_derived_quarter_is_not_a_silent_substitution(self, result):
        """El cuarto trimestre derivado solo existe si se registra explícitamente."""

        annual = [
            o
            for o in result.registry.observations_for_metric("revenue")
            if o.period.frequency is Frequency.ANNUAL
        ]
        assert all(
            "derivado" not in (o.notes or "")
            for o in annual
        ), "ninguna observación anual del fixture debe ser un valor derivado"

    def test_scale_is_units_not_millions(self, result):
        obs = result.registry.observations_for_metric("revenue")[-1]
        assert obs.value.scale is Scale.UNITS
        assert obs.value.currency == "USD"


class TestClientBehaviour:
    def test_default_contact_is_a_placeholder_that_is_flagged(self, monkeypatch):
        # La prueba debe ser determinista y no depender de si el entorno define
        # NEXO_SEC_CONTACT. Aíslese el contacto explicitando el marcador.
        monkeypatch.delenv("NEXO_SEC_CONTACT", raising=False)
        client = SecEdgarClient(contact=DEFAULT_CONTACT_PLACEHOLDER)
        assert client.contact == DEFAULT_CONTACT_PLACEHOLDER
        assert client.contact_is_placeholder is True
        assert "@" in client.user_agent

    def test_custom_contact_is_used_in_user_agent(self):
        client = SecEdgarClient(contact="analista@dominio-real.com")
        assert "analista@dominio-real.com" in client.user_agent
        assert client.contact_is_placeholder is False

    def test_rate_limit_floor_is_enforced(self):
        client = SecEdgarClient(min_interval_seconds=0.0)
        assert client.min_interval_seconds >= 0.11, "nunca por encima de ~9 req/s"

    def test_http_error_is_recorded_and_raised(self, monkeypatch):
        import urllib.error

        client = SecEdgarClient(cache_dir=None)

        def boom(*args, **kwargs):
            raise urllib.error.HTTPError("https://data.sec.gov/x", 403, "Forbidden", None, None)

        monkeypatch.setattr("urllib.request.urlopen", boom)
        with pytest.raises(SecEdgarError, match="403"):
            client.get_raw("https://data.sec.gov/x")
        assert client.fetches and client.fetches[-1].status == 403
        assert client.fetches[-1].error == "HTTP 403"

    def test_network_failure_does_not_invent_data(self, monkeypatch):
        import socket

        client = SecEdgarClient(cache_dir=None)

        def boom(*args, **kwargs):
            raise socket.timeout("timeout simulado")

        monkeypatch.setattr("urllib.request.urlopen", boom)
        with pytest.raises(SecEdgarError):
            client.company_facts(320193)
        assert client.fetches[-1].error is not None

    def test_placeholder_contact_blocks_the_primary_document(self, monkeypatch):
        """El marcador por defecto no emite la petición HTML del documento primario."""

        called = []

        def boom(*args, **kwargs):
            called.append(1)
            raise AssertionError("no debería emitirse ninguna petición")

        monkeypatch.delenv("NEXO_SEC_CONTACT", raising=False)
        monkeypatch.setattr("urllib.request.urlopen", boom)
        client = SecEdgarClient(contact=DEFAULT_CONTACT_PLACEHOLDER)
        with pytest.raises(ContactNotConfiguredError, match="NEXO_SEC_CONTACT"):
            client.get_document(DOC_URL)
        assert called == []
        assert client.fetches == [], "ni siquiera se registra una descarga"

    def test_empty_contact_blocks_the_primary_document(self, monkeypatch):
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("sin red"))
        client = SecEdgarClient(contact="   ")
        assert client.contact == ""
        with pytest.raises(ContactNotConfiguredError):
            client.get_document(DOC_URL)


class TestEmptyAndDegenerate:
    def test_empty_payload_produces_empty_registry(self):
        res = build_registry_from_companyfacts({"cik": 1, "entityName": ""}, cik=1, fetch_records=[])
        assert res.registry.observations == {}
        assert res.validated_metrics == []

    def test_registry_can_be_shared(self):
        registry = ProvenanceRegistry()
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        build_registry_from_companyfacts(payload, cik=320193, fetch_records=[], registry=registry)
        assert registry.sources


class TestFiscalCalendarInference:
    def test_close_month_uses_annual_closings(self, payload):
        from nexo_invest.data.sec_edgar import fiscal_calendar_for

        calendar = fiscal_calendar_for(payload)
        assert calendar.close_month == 9, "Apple cierra su ejercicio en septiembre"

    def test_fallback_is_december_without_data(self):
        from nexo_invest.data.sec_edgar import fiscal_calendar_for

        assert fiscal_calendar_for({"facts": {}}).close_month == 12


# -- documento primario: descarga HTML + validación ---------------------------------


class _FakeResponse:
    """Respuesta HTTP simulada con la interfaz mínima que usa el cliente."""

    def __init__(
        self, payload: bytes, *, status: int = 200, content_type: str = "text/html"
    ):
        self.payload = payload
        self.status = status
        self.headers = {"Content-Type": content_type}

    def read(self) -> bytes:
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _install_urlopen(
    monkeypatch,
    payload: bytes = b"",
    *,
    status: int = 200,
    content_type: str = "text/html",
    error: Exception | None = None,
):
    seen: dict = {}

    def fake(request, timeout=None):
        seen["request"] = request
        if error is not None:
            raise error
        return _FakeResponse(payload, status=status, content_type=content_type)

    monkeypatch.setattr("urllib.request.urlopen", fake)
    return seen


def _doc_record(
    raw: bytes,
    *,
    url: str = DOC_URL,
    status: int = 200,
    content_type: str | None = "text/html",
) -> FetchRecord:
    return FetchRecord(
        url=url,
        retrieved_at=datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc),
        status=status,
        bytes_received=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        from_cache=False,
        content_type=content_type,
    )


def _parse(raw: bytes, *, url: str = DOC_URL, expected_fiscal_year=2025, **kwargs):
    return parse_primary_document(
        raw,
        url=url,
        accession=ACCESSION,
        cik=320193,
        fetch=kwargs.pop("fetch", _doc_record(raw, url=url)),
        expected_fiscal_year=expected_fiscal_year,
        **kwargs,
    )


class TestPrimaryDocumentDownload:
    def test_missing_contact_blocks_any_request(self, monkeypatch):
        """Cuando no hay contacto configurado, el cliente no debe emitir ninguna
        petición HTTP, ni siquiera una simulada."""

        called = []

        def boom(*args, **kwargs):
            called.append(1)
            raise AssertionError("no debería emitirse ninguna petición")

        monkeypatch.delenv("NEXO_SEC_CONTACT", raising=False)
        monkeypatch.setattr("urllib.request.urlopen", boom)
        client = SecEdgarClient(contact=DEFAULT_CONTACT_PLACEHOLDER)
        with pytest.raises(ContactNotConfiguredError, match="NEXO_SEC_CONTACT"):
            client.get_document(DOC_URL)
        assert called == []
        assert client.fetches == [], "ni siquiera se registra una descarga"

    def test_empty_contact_is_not_a_real_contact(self, monkeypatch):
        monkeypatch.delenv("NEXO_SEC_CONTACT", raising=False)
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("sin red"))
        client = SecEdgarClient(contact="   ")
        assert client.contact == ""
        with pytest.raises(ContactNotConfiguredError):
            client.get_document(DOC_URL)

    def test_document_request_uses_html_accept_and_records_evidence(self, monkeypatch):
        payload = HTML_10K.read_bytes()
        seen = _install_urlopen(monkeypatch, payload, content_type="text/html; charset=utf-8")
        client = SecEdgarClient(contact=REAL_CONTACT, cache_dir=None)

        raw, record = client.get_document(DOC_URL, use_cache=False)

        assert raw == payload
        request = seen["request"]
        assert request.get_header("Accept") == ACCEPT_HTML
        # `Request` normaliza la cabecera a «User-agent».
        assert request.get_header("User-agent") == client.user_agent
        assert record.status == 200
        assert record.content_type == "text/html"
        assert record.from_cache is False
        assert record.bytes_received == len(payload)
        assert record.sha256 == hashlib.sha256(payload).hexdigest()

    def test_placeholder_client_cannot_download_the_primary_document(self, monkeypatch):
        """Un cliente con el marcador por defecto no requiere una variable externa
        para demostrar el bloqueo: basta con usar el contacto placeholder explícito."""

        monkeypatch.delenv("NEXO_SEC_CONTACT", raising=False)
        client = SecEdgarClient(contact=DEFAULT_CONTACT_PLACEHOLDER, cache_dir=None)
        with pytest.raises(ContactNotConfiguredError, match="NEXO_SEC_CONTACT"):
            client.get_document(DOC_URL, use_cache=False)
        assert client.fetches == [], "el bloqueo evita registrar cualquier fetch"

    def test_json_requests_keep_the_json_accept(self, monkeypatch):
        seen = _install_urlopen(
            monkeypatch, b'{"facts": {}}', content_type="application/json"
        )
        client = SecEdgarClient(contact=REAL_CONTACT, cache_dir=None)
        client.get_raw("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json")
        assert seen["request"].get_header("Accept") == ACCEPT_JSON

    def test_json_calls_do_not_require_a_contact(self, monkeypatch):
        _install_urlopen(
            monkeypatch, b'{"cik": "0000320193", "facts": {}}',
            content_type="application/json",
        )
        client = SecEdgarClient()  # sin contacto real: las llamadas JSON siguen igual
        payload, record = client.company_facts(320193)
        assert payload["cik"] == "0000320193"
        assert record.status == 200

    def test_http_error_leaves_no_document(self, monkeypatch):
        import urllib.error

        error = urllib.error.HTTPError(DOC_URL, 403, "Forbidden", None, None)
        _install_urlopen(monkeypatch, error=error)
        client = SecEdgarClient(contact=REAL_CONTACT, cache_dir=None)
        with pytest.raises(SecEdgarError, match="403"):
            client.get_document(DOC_URL, use_cache=False)
        assert client.fetches[-1].status == 403
        assert client.fetches[-1].error == "HTTP 403"

    def test_cached_download_is_flagged_as_such(self, tmp_path, monkeypatch):
        payload = HTML_10K.read_bytes()
        _install_urlopen(monkeypatch, payload)
        client = SecEdgarClient(contact=REAL_CONTACT, cache_dir=tmp_path)
        _, first = client.get_document(DOC_URL, use_cache=True)
        _, second = client.get_document(DOC_URL, use_cache=True)
        assert first.from_cache is False
        assert second.from_cache is True
        assert second.sha256 == first.sha256, "la caché devuelve los mismos bytes"


class TestPrimaryDocumentValidation:
    def test_valid_document_is_identified_and_extracted(self):
        raw = HTML_10K.read_bytes()
        primary = _parse(raw)
        assert primary.form == "10-K"
        assert primary.fiscal_year == 2025
        assert primary.fiscal_period == "FY"
        assert primary.entity_cik == "0000320193"
        assert primary.entity_name == "Apple Inc."
        assert primary.sha256 == hashlib.sha256(raw).hexdigest()

        fact = primary.annual_revenue(
            period_start=date(2024, 9, 29), period_end=date(2025, 9, 27)
        )
        assert fact.value == Decimal("416161000000")

    def test_error_page_is_not_a_10k(self):
        raw = b"<html><body><h1>Access Denied</h1></body></html>"
        with pytest.raises(PrimaryDocumentError, match="Inline XBRL"):
            _parse(raw)

    def test_non_html_payload_is_rejected(self):
        raw = b'{"error": "rate limited"}'
        with pytest.raises(PrimaryDocumentError, match="documento HTML"):
            _parse(raw)

    def test_wrong_content_type_is_rejected(self):
        raw = HTML_10K.read_bytes()
        record = _doc_record(raw, content_type="text/plain")
        with pytest.raises(PrimaryDocumentError, match="text/plain"):
            parse_primary_document(
                raw, url=DOC_URL, accession=ACCESSION, cik=320193,
                fetch=record, expected_fiscal_year=2025,
            )

    def test_non_200_status_is_rejected(self):
        raw = HTML_10K.read_bytes()
        record = _doc_record(raw, status=503)
        with pytest.raises(PrimaryDocumentError, match="503"):
            parse_primary_document(
                raw, url=DOC_URL, accession=ACCESSION, cik=320193,
                fetch=record, expected_fiscal_year=2025,
            )

    def test_wrong_form_is_rejected(self):
        html = HTML_10K.read_text(encoding="utf-8").replace(">10-K<", ">10-Q<")
        with pytest.raises(PrimaryDocumentError, match="10-Q"):
            _parse(html.encode("utf-8"))

    def test_wrong_cik_is_rejected(self):
        html = re.sub(
            r'(name="dei:EntityCentralIndexKey"[^>]*>)[^<]+',
            r"\g<1>0000320194",
            HTML_10K.read_text(encoding="utf-8"),
        )
        with pytest.raises(PrimaryDocumentError, match="0000320193"):
            _parse(html.encode("utf-8"))

    def test_wrong_fiscal_year_is_rejected(self):
        raw = HTML_10K.read_bytes()
        with pytest.raises(PrimaryDocumentError, match="2024"):
            _parse(raw, expected_fiscal_year=2024)

    def test_accession_mismatch_is_rejected(self):
        raw = HTML_10K.read_bytes()
        other_url = "https://www.sec.gov/Archives/edgar/data/320193/0000111111111111/x.htm"
        with pytest.raises(PrimaryDocumentError, match="accession"):
            _parse(raw, url=other_url)


class TestCompanyFactsValueLookup:
    def test_periodo_exacto_devuelve_el_valor(self, payload):
        value = companyfacts_fact_value(
            payload, period_start=date(2024, 9, 29), period_end=date(2025, 9, 27)
        )
        assert value == Decimal("416161000000")

    def test_periodo_ausente_devuelve_none(self, payload):
        value = companyfacts_fact_value(
            payload, period_start=date(2030, 1, 1), period_end=date(2030, 12, 31)
        )
        assert value is None

    def test_payload_invalido_devuelve_none(self):
        assert companyfacts_fact_value(
            {}, period_start=date(2024, 9, 29), period_end=date(2025, 9, 27)
        ) is None
