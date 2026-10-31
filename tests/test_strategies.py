"""Pruebas de las dos estrategias de inversión (Hito 5).

Las empresas y los criterios son sintéticos o derivados del fixture real de Apple.
Ninguna prueba hace peticiones de red ni afirma rentabilidad de nada.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from nexo_invest.core.metrics import (
    BalanceSheet,
    CashFlow,
    FinancialMetrics,
    FinancialState,
    IncomeStatement,
)
from nexo_invest.core.periods import FiscalCalendar
from nexo_invest.core.units import Frequency, Money, Period, Scale
from nexo_invest.data.sec_edgar import build_registry_from_companyfacts, fiscal_calendar_for
from nexo_invest.strategies import (
    TACTICAL_REQUIRED_DATA,
    TacticalReadiness,
    ValueScreenResult,
    screen_value_contrarian,
    strategies_markdown,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sec_companyfacts_aapl_subset.json"
ANNUAL_2023 = Period(start=date(2023, 1, 1), end=date(2023, 12, 31), frequency=Frequency.ANNUAL)
ANNUAL_2024 = Period(start=date(2024, 1, 1), end=date(2024, 12, 31), frequency=Frequency.ANNUAL)


def _m(value: float) -> Money:
    return Money(value, "USD", Scale.MILLIONS)


def strong_state() -> FinancialState:
    """Empresa de calidad: rentable, sin deuda neta, con conversión de caja alta."""

    state = FinancialState(company="Calidad S.A.", currency="USD")
    state.add_income_statement(
        IncomeStatement(
            period=ANNUAL_2023,
            revenue=_m(1000.0),
            gross_profit=_m(500.0),
            operating_income=_m(200.0),
            net_income=_m(150.0),
            income_before_tax=_m(190.0),
            tax_provision=_m(40.0),
            depreciation_amortization=_m(60.0),
            shares_diluted=_m(100.0),
        )
    )
    state.add_income_statement(
        IncomeStatement(
            period=ANNUAL_2024,
            revenue=_m(1100.0),
            gross_profit=_m(550.0),
            operating_income=_m(240.0),
            net_income=_m(180.0),
            income_before_tax=_m(225.0),
            tax_provision=_m(45.0),
            depreciation_amortization=_m(65.0),
            shares_diluted=_m(100.0),
        )
    )
    state.add_balance_sheet(
        BalanceSheet(
            period=ANNUAL_2024,
            total_debt=_m(100.0),
            cash_and_equivalents=_m(400.0),
            shareholders_equity=_m(900.0),
            invested_capital=_m(1000.0),
        )
    )
    state.add_cash_flow(
        CashFlow(
            period=ANNUAL_2024,
            operating_cash_flow=_m(260.0),
            capital_expenditures=_m(40.0),
            free_cash_flow=_m(220.0),
        )
    )
    return state


def weak_state() -> FinancialState:
    """Empresa con dos criterios incumplidos y el resto no evaluable."""

    state = FinancialState(company="Debil S.A.", currency="USD")
    state.add_income_statement(
        IncomeStatement(
            period=ANNUAL_2024,
            revenue=_m(1000.0),
            gross_profit=_m(150.0),
            operating_income=_m(50.0),
            net_income=_m(20.0),
        )
    )
    state.add_balance_sheet(
        BalanceSheet(
            period=ANNUAL_2024,
            total_debt=_m(3000.0),
            cash_and_equivalents=_m(100.0),
        )
    )
    return state


def metrics_for(state: FinancialState) -> FinancialMetrics:
    return FinancialMetrics.from_state(state, latest_end=ANNUAL_2024.end)


@pytest.fixture()
def strong_result() -> ValueScreenResult:
    return screen_value_contrarian(metrics_for(strong_state()))


def apple_metrics() -> FinancialMetrics:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = build_registry_from_companyfacts(payload, cik=320193, fetch_records=[])
    state = result.registry.to_financial_state()
    return FinancialMetrics.from_state(
        state, latest_end=date(2025, 9, 27), fiscal_calendar=fiscal_calendar_for(payload)
    )


class TestValueCriteria:
    def test_strong_company_passes_every_criterion(self, strong_result):
        assert strong_result.failed_count == 0
        assert strong_result.not_evaluable_count == 0
        assert strong_result.status == "candidato_calidad"
        # ROIC: 240*(1-0.2)/1000 = 19,2 %
        assert strong_result.criteria[0].key == "roic_nopat"
        assert strong_result.criteria[0].value == pytest.approx(0.192)

    def test_debt_and_margin_can_discard_a_company(self):
        result = screen_value_contrarian(metrics_for(weak_state()))
        assert result.criteria[1].passed is False  # margen bruto 15 % < 25 %
        assert result.failed_count >= 1
        assert any("Márgen bruto" in reason for reason in result.excluded) or any(
            "Deuda neta" in reason for reason in result.excluded
        )

    def test_two_failures_discard_the_candidate(self):
        state = weak_state()
        # Margen bruto bajo y deuda neta/EBITDA alta: descarte documentado.
        state.income_statements[ANNUAL_2024.end].depreciation_amortization = _m(10.0)
        result = screen_value_contrarian(metrics_for(state))
        assert result.failed_count >= 2
        assert result.status == "descartado"

    def test_missing_data_is_not_evidence_against(self):
        state = FinancialState(company="Sin datos S.A.", currency="USD")
        state.add_income_statement(
            IncomeStatement(period=ANNUAL_2024, revenue=_m(1000.0), gross_profit=_m(400.0))
        )
        result = screen_value_contrarian(metrics_for(state))
        assert result.status == "insuficiente_datos"
        assert result.not_evaluable_count > 0
        assert result.failed_count == 0

    def test_no_company_can_be_recommended(self, strong_result):
        assert strong_result.can_recommend is False
        assert "no se recomienda su compra" in strong_result.markdown()


class TestTacticalStrategy:
    def test_tactical_is_not_ready_and_lists_missing_data(self):
        tactical = TacticalReadiness()
        assert tactical.is_ready is False
        text = tactical.markdown()
        assert "no lista" in text
        for item in TACTICAL_REQUIRED_DATA:
            assert item in text

    def test_tactical_emits_no_signals(self):
        text = TacticalReadiness().markdown()
        assert "No se emite ninguna señal táctica" in text
        assert "comprar" not in text.lower()


class TestStrategiesReport:
    def test_report_never_issues_a_recommendation(self, strong_result):
        text = strategies_markdown([strong_result], generated_at="2026-10-27")
        assert "No contiene recomendaciones de compra o venta" in text
        assert "**No se recomienda su compra.**" in text
        assert "Ninguna prueba afi" not in text

    def test_report_without_candidates_says_so(self):
        result = screen_value_contrarian(metrics_for(weak_state()))
        text = strategies_markdown([result], generated_at="2026-10-27")
        assert "no se propone ninguna candidata" in text or "no recomendar ninguna" in text

    def test_failures_are_recorded_not_hidden(self, strong_result):
        text = strategies_markdown(
            [strong_result],
            generated_at="2026-10-27",
            notes=["XXYZ: no se pudo analizar (SecEdgarError: HTTP 404)"],
        )
        assert "XXYZ: no se pudo analizar" in text

    def test_ranking_orders_by_criteria_compliance(self, strong_result):
        weak = screen_value_contrarian(metrics_for(weak_state()))
        text = strategies_markdown([weak, strong_result], generated_at="2026-10-27")
        assert text.index("Calidad S.A.") < text.index("Debil S.A.")


class TestAppleRealData:
    """La estrategia se ejecuta sobre datos reales descargados, sin valores inventados."""

    @pytest.fixture(scope="class")
    @classmethod
    def result(cls) -> ValueScreenResult:
        return screen_value_contrarian(apple_metrics())

    def test_screen_runs_and_reports_its_limits(self, result):
        assert result.company == "Apple Inc."
        assert result.status in {"candidato_calidad", "insuficiente_datos", "descartado"}
        assert result.can_recommend is False

    def test_tax_and_debt_criteria_are_evaluated(self, result):
        by_key = {c.key: c for c in result.criteria}
        assert by_key["roic_nopat"].passed is True
        assert by_key["gross_margin"].passed is True
        assert by_key["net_debt_to_ebitda"].passed is True

    def test_dilution_requires_two_comparable_periods(self, result):
        by_key = {c.key: c for c in result.criteria}
        # Con cierres anuales consecutivos la dilución es calculable y negativa.
        assert by_key["dilution_rate"].passed is True
        assert by_key["dilution_rate"].value < 0

    def test_fcf_estimate_is_disclosed_as_a_caveat(self, result):
        assert any("estimación" in reason for reason in result.excluded)

    def test_report_text_for_apple_has_no_price_claim(self, result):
        text = result.markdown()
        assert "margen de seguridad" in text
        assert "no se recomienda" in text.lower() or "no se recomienda su compra" in text


