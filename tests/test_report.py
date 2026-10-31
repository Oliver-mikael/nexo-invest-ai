from __future__ import annotations


from nexo_invest.core.report import AnalysisReport
from nexo_invest.core.metrics import FinancialMetrics
from nexo_invest.core.units import Money, Period, Frequency
from datetime import date


def _basic_report() -> AnalysisReport:
    period = Period(start=date(2024, 1, 1), end=date(2024, 12, 31), frequency=Frequency.ANNUAL)
    m = FinancialMetrics(company="X", currency="USD", latest_period=period, revenue=Money(100, "USD", "millions"))
    return AnalysisReport(
        company="X",
        analysis_date=date(2025, 3, 1),
        metrics=m,
        thesis="Prueba de tesis.",
        evidence_for=["Evidencia A"],
        evidence_against=["Evidencia B"],
        risks=["Riesgo 1"],
        key_assumptions=["SC1"],
        invalidation_conditions=["Condición 1"],
        data_quality="parcial",
        conclusion="Investigar más.",
        sources=["Fuente 1"],
        limitations=["Limitación 1"],
    )


class TestAnalysisReport:
    def test_markdown_includes_sections(self):
        report = _basic_report()
        md = report.markdown()
        assert "# Informe de análisis: X" in md
        assert "## 1. Resumen de la empresa" in md
        assert "## 2. Calidad y cobertura de los datos" in md
        assert "## 3. Indicadores fundamentales" in md
        assert "## 4. Valoración y escenarios" in md
        assert "## 5. Riesgos y argumentos contrarios" in md
        assert "## 6. Supuestos que más influyen" in md
        assert "## 7. Condiciones para reconsiderar la tesis" in md
        assert "## 8. Fuentes y limitaciones" in md
        assert "## 9. Conclusión" in md
        assert "Prueba de tesis." in md
        assert "- Evidencia A" in md
        assert "- Evidencia B" in md
        assert "- Riesgo 1" in md
        assert "- Fuente 1" in md
        assert "- Limitación 1" in md
        assert "Investigar más." in md
        assert "Fecha del análisis:" in md
        assert "Cobertura: parcial" in md

    def test_legal_notice_present(self):
        report = _basic_report()
        md = report.markdown()
        assert "No constituye" in md and "asesoramiento financiero" in md

    def test_without_valuation_section(self):
        report = _basic_report()
        report.valuation = None
        md = report.markdown()
        assert "Sin valoración calculada" in md

    def test_valuation_values_present(self):
        from nexo_invest.core.dcf import run_dcf, DCFAssumptions
        base = Money(100.0, "USD", "millions")
        a = DCFAssumptions(
            currency="USD", forecast_years=1, discount_rate=0.10,
            terminal_growth=0.02, shares_outstanding=10.0,
        )
        run = run_dcf(base, [0.0], a)
        report = _basic_report()
        report.valuation = run
        md = report.markdown()
        assert "Valor de empresa:" in md
        assert "100.00" in md or "Valor de empresa:" in md
