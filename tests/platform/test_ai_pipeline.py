"""Auditoría determinista, orquestador, presupuesto y exportación."""

from __future__ import annotations

import pytest

from app.ai.audit import find_unsupported_numbers
from app.ai.base import BudgetExceeded, ProviderError
from app.ai.orchestrator import AIOrchestrator, extract_json, normalize_output
from app.ai.providers import FakeProvider
from app.config import ProviderConfig
from app.services.export import markdown_to_html, report_csv

LEDGER = [
    {"id": "metric:revenue", "label": "Ingresos", "value": 416_161_000_000.0, "unit": "money"},
    {"id": "metric:gross_margin", "label": "Margen bruto", "value": 0.4621, "unit": "fraction"},
    {"id": "valuation:base", "label": "Valor por acción", "value": 118.93, "unit": "currency"},
]


def test_audit_flags_invented_numbers():
    text = (
        "Los ingresos fueron de 416.161 millones y el margen bruto del 46,21%. "
        "El valor por acción es 118,93 y una cifra inventada es 999.888.777."
    )
    findings = find_unsupported_numbers(text, LEDGER)
    assert findings, "la cifra inventada debe marcarse"
    assert all("999" not in item.raw or item.kind == "money" for item in findings)
    flagged = [item.raw for item in findings]
    assert any(raw.replace(".", "").startswith("999") for raw in flagged)


def test_audit_ignores_years_small_numbers_and_supported_values():
    text = "En 2025 la empresa tenía 12 segmentos y un margen bruto del 46,21%."
    assert find_unsupported_numbers(text, LEDGER) == []


def test_extract_json_handles_fences_and_prose():
    raw = 'Aquí está:\n```json\n{"summary": "ok", "sections": {}}\n```\nFin.'
    assert extract_json(raw)["summary"] == "ok"
    with pytest.raises(ValueError):
        extract_json("sin json")


def test_normalize_output_limits_and_sanitizes():
    output = normalize_output(
        {
            "summary": "x" * 5000,
            "sections": {"a": 1},
            "claims": [{"text": "hola", "kind": "fact", "evidence_ids": ["metric:revenue"]}, "texto"],
            "sources": [{"title": "t", "url": "https://ejemplo.test"}],
        }
    )
    assert len(output["summary"]) == 2000
    assert len(output["claims"]) == 2
    assert output["claims"][1]["kind"] == "interpretation"
    assert output["sources"][0]["url"] == "https://ejemplo.test"


def _settings_with_fake(price: float = 0.0):
    from app.config import load_settings

    base = load_settings()
    return base.__class__(
        **{
            **base.__dict__,
            "providers": [
                ProviderConfig(name="fake", kind="fake", base_url="fake://", models=["fake-1"])
            ],
            "ai_prices": {"fake:fake-1": {"input": price, "output": price}},
            "ai_default_profile": "standard",
        }
    )


def test_orchestrator_degrades_when_provider_fails():
    settings = _settings_with_fake()
    provider = FakeProvider()
    provider.should_fail = True
    orchestrator = AIOrchestrator(settings, {"fake": provider}, sleep=lambda _s: None)
    result = orchestrator.run(
        profile="standard",
        identity={"ticker": "AAPL"},
        ledger=LEDGER,
        valuation={"scenarios": []},
        provenance={},
        budget_usd=1.0,
    )
    assert result.completed == []
    assert all(role.status == "failed" for role in result.roles)
    assert "ProviderError" in result.roles[0].error


def test_orchestrator_stops_on_budget():
    settings = _settings_with_fake(price=50.0)
    provider = FakeProvider(
        responder=lambda messages, model: '{"summary": "ok"}',
        price={"input": 50.0, "output": 50.0},
    )
    orchestrator = AIOrchestrator(settings, {"fake": provider}, sleep=lambda _s: None)
    result = orchestrator.run(
        profile="standard",
        identity={"ticker": "AAPL"},
        ledger=LEDGER,
        valuation={"scenarios": []},
        provenance={},
        budget_usd=1e-9,
    )
    assert result.stopped_reason == "presupuesto agotado"
    assert len(result.roles) <= 2


def test_orchestrator_plan_without_providers():
    settings = _settings_with_fake()
    orchestrator = AIOrchestrator(settings, {})
    assert orchestrator.available is False
    assert orchestrator.plan("standard")["profile"] == "basic"
    result = orchestrator.run(
        profile="standard",
        identity={},
        ledger=[],
        valuation={},
        provenance={},
        budget_usd=1.0,
    )
    assert result.profile == "standard"
    assert result.stopped_reason == "sin modelos disponibles"


def test_markdown_to_html_escapes_and_tables():
    markdown = "# Título\n\nTexto con <script> y **negrita**.\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n"
    html = markdown_to_html(markdown, title="Prueba")
    assert "<h1>Título</h1>" in html
    assert "&lt;script&gt;" in html
    assert "<table>" in html and "<td>1</td>" in html
    assert "<strong>negrita</strong>" in html


def test_report_csv_with_and_without_tables():
    csv_text = report_csv(
        {
            "metrics": [
                {
                    "key": "revenue",
                    "label": "Ingresos",
                    "value": 1.0,
                    "unit": "money",
                    "period_end": "2025-09-27",
                    "provenance": "external_validated",
                }
            ],
            "scenarios": [{"name": "base", "growth_rates": [0.04], "per_share_value": 10.0}],
        }
    )
    assert "metric,label,value" in csv_text
    assert "scenario,growth_rate" in csv_text
    assert "Sin datos tabulares" in report_csv({})


def test_budget_exceeded_is_raisable():
    with pytest.raises(BudgetExceeded):
        raise BudgetExceeded("sin presupuesto")


def test_provider_error_message_is_short():
    error = ProviderError("x" * 500)
    assert len(str(error)) == 500  # el recorte se aplica en short_error, no aquí
    from app.ai.base import short_error

    assert len(short_error(error)) <= 240
