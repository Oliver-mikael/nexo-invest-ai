"""Pruebas de los indicadores financieros ampliados.

Cada valor esperado se calcula a mano en el propio test a partir de los datos de
entrada, de modo que la prueba es independiente de la implementación.
"""

from __future__ import annotations

from datetime import date

import pytest

from nexo_invest.core.metrics import (
    BalanceSheet,
    CashFlow,
    FinancialMetrics,
    FinancialState,
    IncomeStatement,
)
from nexo_invest.core.units import Frequency, Money, Period, Scale

ANNUAL_2024 = Period(start=date(2024, 1, 1), end=date(2024, 12, 31), frequency=Frequency.ANNUAL)
ANNUAL_2023 = Period(start=date(2023, 1, 1), end=date(2023, 12, 31), frequency=Frequency.ANNUAL)


def _m(value: float) -> Money:
    return Money(value, "USD", Scale.MILLIONS)


def build_state() -> FinancialState:
    state = FinancialState(company="Empresa Test", currency="USD")
    state.add_income_statement(
        IncomeStatement(
            period=ANNUAL_2024,
            revenue=_m(1000.0),
            gross_profit=_m(400.0),
            operating_income=_m(200.0),
            net_income=_m(120.0),
            interest_expense=_m(25.0),
            tax_provision=_m(30.0),
            income_before_tax=_m(150.0),
            depreciation_amortization=_m(80.0),
            shares_diluted=_m(110.0),
        )
    )
    state.add_income_statement(
        IncomeStatement(
            period=ANNUAL_2023,
            revenue=_m(900.0),
            operating_income=_m(180.0),
            net_income=_m(100.0),
            shares_diluted=_m(100.0),
        )
    )
    state.add_balance_sheet(
        BalanceSheet(
            period=ANNUAL_2024,
            total_assets=_m(2000.0),
            total_liabilities=_m(1200.0),
            shareholders_equity=_m(800.0),
            total_debt=_m(500.0),
            cash_and_equivalents=_m(150.0),
            current_assets=_m(600.0),
            current_liabilities=_m(300.0),
            inventory=_m(100.0),
            invested_capital=_m(1000.0),
        )
    )
    state.add_cash_flow(
        CashFlow(
            period=ANNUAL_2024,
            operating_cash_flow=_m(250.0),
            capital_expenditures=_m(50.0),
            free_cash_flow=_m(200.0),
            dividends_paid=_m(40.0),
            share_repurchases=_m(60.0),
        )
    )
    return state


@pytest.fixture()
def metrics() -> FinancialMetrics:
    return FinancialMetrics.from_state(build_state(), latest_end=ANNUAL_2024.end)


class TestLiquidity:
    def test_current_ratio(self, metrics):
        assert metrics.current_ratio == pytest.approx(600.0 / 300.0)

    def test_quick_ratio(self, metrics):
        assert metrics.quick_ratio == pytest.approx((600.0 - 100.0) / 300.0)

    def test_quick_ratio_none_without_inventory(self):
        state = build_state()
        state.balance_sheets[ANNUAL_2024.end].inventory = None
        m = FinancialMetrics.from_state(state, latest_end=ANNUAL_2024.end)
        assert m.quick_ratio is None
        assert "no se asume cero" in m.notes["quick_ratio"]

    def test_current_ratio_none_without_current_liabilities(self):
        state = build_state()
        state.balance_sheets[ANNUAL_2024.end].current_liabilities = None
        m = FinancialMetrics.from_state(state, latest_end=ANNUAL_2024.end)
        assert m.current_ratio is None

    def test_zero_current_liabilities_is_not_divided(self):
        state = build_state()
        state.balance_sheets[ANNUAL_2024.end].current_liabilities = _m(0.0)
        m = FinancialMetrics.from_state(state, latest_end=ANNUAL_2024.end)
        assert m.current_ratio is None
        assert "cero" in m.notes["current_ratio"]


class TestCoverageAndEbitda:
    def test_interest_coverage(self, metrics):
        assert metrics.interest_coverage == pytest.approx(200.0 / 25.0)

    def test_interest_coverage_uses_absolute_expense(self):
        state = build_state()
        state.income_statements[ANNUAL_2024.end].interest_expense = _m(-25.0)
        m = FinancialMetrics.from_state(state, latest_end=ANNUAL_2024.end)
        assert m.interest_coverage == pytest.approx(8.0)

    def test_ebitda_computed(self, metrics):
        assert metrics.ebitda_computed is not None
        assert metrics.ebitda_computed.value == pytest.approx(200.0 + 80.0)

    def test_net_debt_to_ebitda(self, metrics):
        expected_net_debt = 500.0 - 150.0
        expected_ebitda = 280.0
        assert metrics.net_debt.value == pytest.approx(expected_net_debt)
        assert metrics.net_debt_to_ebitda == pytest.approx(expected_net_debt / expected_ebitda)

    def test_net_debt_to_ebitda_none_without_ebitda(self):
        state = build_state()
        stmt = state.income_statements[ANNUAL_2024.end]
        stmt.depreciation_amortization = None
        stmt.operating_income = None
        m = FinancialMetrics.from_state(state, latest_end=ANNUAL_2024.end)
        assert m.net_debt_to_ebitda is None


class TestNopatAndRoic:
    def test_effective_tax_rate(self, metrics):
        assert metrics.effective_tax_rate == pytest.approx(30.0 / 150.0)

    def test_nopat(self, metrics):
        expected = 200.0 * (1.0 - 0.2)
        assert metrics.nopat is not None
        assert metrics.nopat.value == pytest.approx(expected)

    def test_roic_nopat_with_reported_capital(self, metrics):
        expected = (200.0 * 0.8) / 1000.0
        assert metrics.roic_nopat == pytest.approx(expected)
        assert metrics.invested_capital_estimated is False

    def test_roic_nopat_estimates_capital_and_flags_it(self):
        state = build_state()
        state.balance_sheets[ANNUAL_2024.end].invested_capital = None
        m = FinancialMetrics.from_state(state, latest_end=ANNUAL_2024.end)
        assert m.invested_capital_estimated is True
        assert m.invested_capital.value == pytest.approx(500.0 + 800.0)
        assert m.roic_nopat == pytest.approx((200.0 * 0.8) / 1300.0)
        assert "estimado" in m.notes["invested_capital"]

    def test_tax_rate_clamped_for_negative_pretax(self):
        state = build_state()
        stmt = state.income_statements[ANNUAL_2024.end]
        stmt.income_before_tax = _m(-50.0)
        m = FinancialMetrics.from_state(state, latest_end=ANNUAL_2024.end)
        assert m.effective_tax_rate is None
        assert "no calculable" in m.notes["effective_tax_rate"]

    def test_no_nopat_without_operating_income(self):
        state = build_state()
        state.income_statements[ANNUAL_2024.end].operating_income = None
        m = FinancialMetrics.from_state(state, latest_end=ANNUAL_2024.end)
        assert m.nopat is None
        assert m.roic_nopat is None


class TestCashQuality:
    def test_fcf_conversion_ocf(self, metrics):
        assert metrics.fcf_conversion_ocf == pytest.approx(200.0 / 250.0)

    def test_fcf_conversion_net_income(self, metrics):
        assert metrics.fcf_conversion_net_income == pytest.approx(200.0 / 120.0)

    def test_capex_to_revenue_uses_absolute_value(self):
        state = build_state()
        state.cash_flows[ANNUAL_2024.end].capital_expenditures = _m(-50.0)
        m = FinancialMetrics.from_state(state, latest_end=ANNUAL_2024.end)
        assert m.capex_to_revenue == pytest.approx(50.0 / 1000.0)

    def test_zero_ocf_does_not_divide(self):
        state = build_state()
        state.cash_flows[ANNUAL_2024.end].operating_cash_flow = _m(0.0)
        m = FinancialMetrics.from_state(state, latest_end=ANNUAL_2024.end)
        assert m.fcf_conversion_ocf is None

    def test_dividends_and_buybacks_are_exposed(self, metrics):
        assert metrics.dividends_paid.value == pytest.approx(40.0)
        assert metrics.share_repurchases.value == pytest.approx(60.0)


class TestDilution:
    def test_dilution_rate(self, metrics):
        assert metrics.shares_diluted.value == pytest.approx(110.0)
        assert metrics.shares_diluted_prior.value == pytest.approx(100.0)
        assert metrics.dilution_rate == pytest.approx(0.10)

    def test_negative_dilution_when_shares_fall(self):
        state = build_state()
        state.income_statements[ANNUAL_2024.end].shares_diluted = _m(90.0)
        m = FinancialMetrics.from_state(state, latest_end=ANNUAL_2024.end)
        assert m.dilution_rate == pytest.approx(-0.10)

    def test_dilution_none_without_prior(self):
        state = FinancialState(company="Sola", currency="USD")
        state.add_income_statement(
            IncomeStatement(period=ANNUAL_2024, revenue=_m(100.0), shares_diluted=_m(10.0))
        )
        m = FinancialMetrics.from_state(state, latest_end=ANNUAL_2024.end)
        assert m.dilution_rate is None
        assert "periodo anterior" in m.notes["dilution_rate"]


class TestRealCompanyIndicators:
    """Indicadores calculados con datos reales de Apple (fixture de SEC EDGAR)."""

    @pytest.fixture(scope="class")
    @classmethod
    def apple_metrics(cls):
        import json
        from pathlib import Path

        from nexo_invest.core.periods import FiscalCalendar
        from nexo_invest.data.sec_edgar import (
            build_registry_from_companyfacts,
            fiscal_calendar_for,
        )

        payload = json.loads(
            (Path(__file__).parent / "fixtures" / "sec_companyfacts_aapl_subset.json").read_text(
                encoding="utf-8"
            )
        )
        result = build_registry_from_companyfacts(payload, cik=320193, fetch_records=[])
        state = result.registry.to_financial_state()
        calendar = fiscal_calendar_for(payload)
        metrics = FinancialMetrics.from_state(
            state, latest_end=date(2024, 9, 28), fiscal_calendar=calendar
        )
        return metrics

    def test_fy2024_revenue_is_the_filed_figure(self, apple_metrics):
        assert apple_metrics.revenue.value == pytest.approx(391_035_000_000)

    def test_gross_margin(self, apple_metrics):
        # 180 683 / 391 035 según el 10-K del ejercicio 2024
        assert apple_metrics.gross_margin == pytest.approx(180_683_000_000 / 391_035_000_000)

    def test_net_debt_matches_independent_recomputation(self, apple_metrics):
        """Recalcula la deuda neta desde el JSON crudo, sin usar el motor de métricas.

        Apple, cierre del ejercicio 2024 (2024-09-28), cifras del 10-K en USD:
          deuda      = 10 912 (LP corriente) + 85 750 (LP no corriente) + 9 967 (papel
                       comercial) = 106 629 millones
          liquidos   = 29 943 (caja y equivalentes) + 35 228 (valores negociables
                       corrientes) = 65 171 millones
          deuda neta = 106 629 - 65 171 = 41 458 millones
        """
        end = "2024-09-28"
        debt = (
            self._instant("LongTermDebtCurrent", end)
            + self._instant("LongTermDebtNoncurrent", end)
            + self._instant("CommercialPaper", end)
        )
        liquid = self._instant("CashAndCashEquivalentsAtCarryingValue", end) + self._instant(
            "MarketableSecuritiesCurrent", end
        )
        expected = debt - liquid
        assert expected == pytest.approx(41_458_000_000)
        assert apple_metrics.total_debt.value == pytest.approx(debt)
        assert apple_metrics.net_debt.value == pytest.approx(expected)
        assert "no se restan inversiones a largo plazo" in apple_metrics.notes["net_debt"]

    @staticmethod
    def _instant(concept: str, end: str) -> float:
        """Valor de un concepto instantaneo del fixture, leido del JSON sin motor."""
        import json
        from pathlib import Path

        payload = json.loads(
            (Path(__file__).parent / "fixtures" / "sec_companyfacts_aapl_subset.json").read_text(
                encoding="utf-8"
            )
        )
        for entry in payload["facts"]["us-gaap"][concept]["units"]["USD"]:
            if entry["end"] == end and entry.get("start") is None:
                return float(entry["val"])
        raise AssertionError(f"El fixture no tiene {concept} en {end}")

    def test_current_ratio_is_plausible(self, apple_metrics):
        if apple_metrics.current_ratio is None:
            pytest.skip("el fixture no incluye corriente para ese cierre")
        assert 0.5 < apple_metrics.current_ratio < 2.0

    def test_dilution_is_small_for_apple(self, apple_metrics):
        assert apple_metrics.dilution_rate is not None
        assert -0.15 < apple_metrics.dilution_rate < 0.02

    def test_prior_period_used_for_growth_is_annual(self, apple_metrics):
        # El periodo anterior debe ser el cierre anual previo, no el trimestre más
        # cercano: comparar un anual contra un trimestre era un error real.
        assert apple_metrics.latest_period.frequency is Frequency.ANNUAL
        assert apple_metrics.previous_period.frequency is Frequency.ANNUAL
        assert apple_metrics.previous_period.end < apple_metrics.latest_period.end

    def test_free_cash_flow_is_marked_as_estimate_when_not_reported(self, apple_metrics):
        assert apple_metrics.free_cash_flow is not None
        assert apple_metrics.free_cash_flow_estimated is True
        expected = apple_metrics.operating_cash_flow.value - abs(
            apple_metrics.capital_expenditures.value
        )
        assert apple_metrics.free_cash_flow.value == pytest.approx(expected)
        assert "estimado" in apple_metrics.notes["free_cash_flow"]


class TestPreviousPeriodSelection:
    """Regresión: los balances instantáneos se etiquetan como anuales.

    Con datos reales de Apple, el periodo anterior se tomaba de la lista global de
    periodos, que incluye balances instantáneos trimestrales marcados como anuales.
    El resultado era comparar el ejercicio 2025 contra el balance del trimestre
    cerrado en junio de 2025: crecimiento y dilución quedaban mal o sin calcular.
    """

    QUARTER_2025Q3 = Period(
        start=date(2025, 3, 30), end=date(2025, 6, 28), frequency=Frequency.QUARTERLY
    )
    ANNUAL_2025 = Period(
        start=date(2024, 9, 29), end=date(2025, 9, 27), frequency=Frequency.ANNUAL
    )
    ANNUAL_2024 = Period(
        start=date(2023, 10, 1), end=date(2024, 9, 28), frequency=Frequency.ANNUAL
    )
    # Instantánea de balance en la misma fecha que el cierre trimestral.
    INSTANT_2025Q3 = Period(
        start=date(2025, 6, 28), end=date(2025, 6, 28), frequency=Frequency.ANNUAL
    )

    def _state(self) -> FinancialState:
        state = FinancialState(company="Apple-like", currency="USD")
        state.add_income_statement(
            IncomeStatement(period=self.ANNUAL_2024, revenue=_m(391.035), shares_diluted=_m(15.408))
        )
        state.add_income_statement(
            IncomeStatement(period=self.QUARTER_2025Q3, revenue=_m(94.036))
        )
        state.add_income_statement(
            IncomeStatement(period=self.ANNUAL_2025, revenue=_m(416.161), shares_diluted=_m(15.005))
        )
        state.add_balance_sheet(
            BalanceSheet(period=self.INSTANT_2025Q3, total_assets=_m(100.0))
        )
        return state

    def test_previous_period_is_the_prior_annual_close(self):
        m = FinancialMetrics.from_state(self._state(), latest_end=date(2025, 9, 27))
        assert m.previous_period == self.ANNUAL_2024
        assert m.revenue_growth == pytest.approx(416.161 / 391.035 - 1.0)

    def test_dilution_is_computed_across_two_annual_closes(self):
        m = FinancialMetrics.from_state(self._state(), latest_end=date(2025, 9, 27))
        assert m.dilution_rate == pytest.approx(15.005 / 15.408 - 1.0)

    def test_same_frequency_is_required(self):
        state = self._state()
        del state.income_statements[self.ANNUAL_2024.end]
        m = FinancialMetrics.from_state(state, latest_end=date(2025, 9, 27))
        assert m.dilution_rate is None
        assert "periodo anterior" in m.notes["dilution_rate"]
