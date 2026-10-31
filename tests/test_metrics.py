from __future__ import annotations

import pytest
from datetime import date

from nexo_invest.core.metrics import (
    FinancialMetrics,
    FinancialState,
    growth_rate,
    margin,
    summarize,
    IncomeStatement,
)
from nexo_invest.core.units import Money, Period, Frequency, Scale


class TestGrowthRate:
    def test_growth_positive(self):
        c = Money(120.0, "USD", Scale.MILLIONS)
        p = Money(100.0, "USD", Scale.MILLIONS)
        assert growth_rate(c, p) == pytest.approx(0.20)

    def test_growth_negative(self):
        c = Money(80.0, "USD", Scale.MILLIONS)
        p = Money(100.0, "USD", Scale.MILLIONS)
        assert growth_rate(c, p) == pytest.approx(-0.20)

    def test_growth_missing_current(self):
        assert growth_rate(None, Money(100.0)) is None

    def test_growth_missing_prior(self):
        assert growth_rate(Money(100.0), None) is None

    def test_growth_zero_prior(self):
        assert growth_rate(Money(100.0), Money(0.0)) is None

    def test_growth_same(self):
        assert growth_rate(Money(100.0, scale=Scale.MILLIONS), Money(100.0, scale=Scale.MILLIONS)) == pytest.approx(0.0)


class TestMargin:
    def test_margin_gross(self):
        assert margin(Money(50.0, "USD", Scale.MILLIONS), Money(100.0, "USD", Scale.MILLIONS)) == pytest.approx(0.50)

    def test_margin_net(self):
        assert margin(Money(14.0, "USD", Scale.MILLIONS), Money(120.0, "USD", Scale.MILLIONS)) == pytest.approx(14.0 / 120.0)

    def test_margin_missing_num(self):
        assert margin(None, Money(100.0, scale=Scale.MILLIONS)) is None

    def test_margin_missing_denom(self):
        assert margin(Money(50.0, scale=Scale.MILLIONS), None) is None

    def test_margin_zero_denom(self):
        assert margin(Money(50.0, scale=Scale.MILLIONS), Money(0.0, scale=Scale.MILLIONS)) is None

    def test_margin_incompatible_scales_returns_none(self):
        num = Money(50.0, "USD", Scale.MILLIONS)
        denom = Money(100000.0, "USD", Scale.UNITS)
        assert margin(num, denom, same_scale_required=True) is None

    def test_margin_allows_incompatible_when_flag_false(self):
        num = Money(50.0, "USD", Scale.MILLIONS)
        denom = Money(100.0, "USD", Scale.MILLIONS)
        assert margin(num, denom, same_scale_required=False) == pytest.approx(0.50)


class TestFinancialMetricsFromState:
    def test_revenue_and_growth(self, example_state):
        m = FinancialMetrics.from_state(example_state, latest_end=date(2024, 12, 31))
        assert m.revenue is not None
        assert m.revenue.value == pytest.approx(120.0)
        assert m.revenue_growth is not None
        assert m.revenue_growth == pytest.approx(0.20)

    def test_margins(self, example_state):
        m = FinancialMetrics.from_state(example_state, latest_end=date(2024, 12, 31))
        assert m.gross_margin == pytest.approx(0.50)
        assert m.operating_margin == pytest.approx(21.0 / 120.0)
        assert m.net_margin == pytest.approx(14.0 / 120.0)
        assert m.ebitda_margin == pytest.approx(25.0 / 120.0)

    def test_fcf_and_net_debt(self, example_state):
        m = FinancialMetrics.from_state(example_state, latest_end=date(2024, 12, 31))
        assert m.free_cash_flow is not None
        assert m.free_cash_flow.value == pytest.approx(23.0)
        assert m.net_debt is not None
        assert m.net_debt.value == pytest.approx(60.0)
        assert m.net_debt.scale is Scale.MILLIONS

    def test_roic_when_available(self, example_state):
        m = FinancialMetrics.from_state(example_state, latest_end=date(2024, 12, 31))
        assert m.invested_capital is not None
        assert m.return_on_invested_capital is not None
        assert m.return_on_invested_capital == pytest.approx(21.0 / 400.0)

    def test_roic_missing_without_invested_capital(self):
        state = FinancialState(company="X", currency="USD")
        p = Period(start=date(2024, 1, 1), end=date(2024, 12, 31), frequency=Frequency.ANNUAL)
        state.add_income_statement(
            IncomeStatement(period=p, revenue=Money(100.0, "USD", "millions"), operating_income=Money(10.0, "USD", "millions"))
        )
        m = FinancialMetrics.from_state(state, latest_end=date(2024, 12, 31))
        assert m.invested_capital is None
        assert m.return_on_invested_capital is None

    def test_missing_revenue_period(self):
        state = FinancialState(company="vacio", currency="USD")
        m = FinancialMetrics.from_state(state, latest_end=date(2024, 12, 31))
        assert m.revenue is None
        assert m.revenue_growth is None
        assert m.notes.get("latest_period_missing") is not None

    def test_company_and_currency_preserved(self, example_state):
        m = FinancialMetrics.from_state(example_state, latest_end=date(2024, 12, 31))
        assert m.company == "Ejemplo S.A."
        assert m.currency == "USD"


class TestSummarize:
    def test_summarize_includes_metric_lines(self, example_state):
        m = FinancialMetrics.from_state(example_state, latest_end=date(2024, 12, 31))
        text = summarize(m)
        assert "Ejemplo S.A." in text
        assert "USD" in text
        assert "Crecimiento interanual:" in text
        assert "50.00%" in text  # gross margin
