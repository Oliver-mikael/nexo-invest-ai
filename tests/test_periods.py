from __future__ import annotations

import pytest
from datetime import date

from nexo_invest.core.units import Money, Period, Frequency, Scale
from nexo_invest.core.metrics import FinancialMetrics, FinancialState, IncomeStatement, growth_rate_strict
from nexo_invest.core.periods import FiscalCalendar, ttm_periods, compute_ttm_from_quarters


class TestFiscalCalendar:
    def test_close_month_12(self):
        cal = FiscalCalendar(close_month=12)
        assert cal.fiscal_year_of_finish(date(2024, 12, 31)) == 2024
        assert cal.fiscal_year_of_finish(date(2024, 10, 1)) == 2024

    def test_close_month_3_semantics(self):
        cal = FiscalCalendar(close_month=3)
        # finish.month <= close_month => finish.year; else finish.year + 1.
        assert cal.fiscal_year_of_finish(date(2024, 3, 31)) == 2024  # mes de cierre
        assert cal.fiscal_year_of_finish(date(2024, 4, 30)) == 2025  # despues del cierre
        assert cal.fiscal_year_of_finish(date(2024, 2, 29)) == 2024  # antes del cierre

    def test_same_fiscal_year(self):
        cal = FiscalCalendar(close_month=12)
        a = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY)
        b = Period(start=date(2024, 4, 1), end=date(2024, 6, 30), frequency=Frequency.QUARTERLY)
        assert cal.is_same_fiscal_year(a, b) is True
        c = Period(start=date(2023, 10, 1), end=date(2023, 12, 31), frequency=Frequency.QUARTERLY)
        assert cal.is_same_fiscal_year(a, c) is False


class TestTtmPeriods:
    def test_four_quarters_consecutive(self):
        cal = FiscalCalendar(close_month=12)
        ends = {
            date(2023, 12, 31): Period(start=date(2023, 10, 1), end=date(2023, 12, 31), frequency=Frequency.QUARTERLY),
            date(2024, 3, 31): Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY),
            date(2024, 6, 30): Period(start=date(2024, 4, 1), end=date(2024, 6, 30), frequency=Frequency.QUARTERLY),
            date(2024, 9, 30): Period(start=date(2024, 7, 1), end=date(2024, 9, 30), frequency=Frequency.QUARTERLY),
            date(2024, 12, 31): Period(start=date(2024, 10, 1), end=date(2024, 12, 31), frequency=Frequency.QUARTERLY),
        }
        result = ttm_periods({k: v for k, v in ends.items()}, latest_end=date(2024, 12, 31), calendar=cal)
        assert len(result) == 4
        assert result[0] == date(2024, 3, 31)
        assert result[1] == date(2024, 6, 30)
        assert result[2] == date(2024, 9, 30)
        assert result[3] == date(2024, 12, 31)

    def test_two_quarters_returns_two(self):
        ends = {
            date(2024, 3, 31): Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY),
            date(2024, 6, 30): Period(start=date(2024, 4, 1), end=date(2024, 6, 30), frequency=Frequency.QUARTERLY),
        }
        result = ttm_periods(ends, latest_end=date(2024, 6, 30))
        assert len(result) == 2


class TestComputeTtmFromQuarters:
    def test_ttm_sum(self):
        cal = FiscalCalendar(close_month=12)
        ends = {
            date(2023, 12, 31): Period(start=date(2023, 10, 1), end=date(2023, 12, 31), frequency=Frequency.QUARTERLY),
            date(2024, 3, 31): Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY),
            date(2024, 6, 30): Period(start=date(2024, 4, 1), end=date(2024, 6, 30), frequency=Frequency.QUARTERLY),
            date(2024, 9, 30): Period(start=date(2024, 7, 1), end=date(2024, 9, 30), frequency=Frequency.QUARTERLY),
            date(2024, 12, 31): Period(start=date(2024, 10, 1), end=date(2024, 12, 31), frequency=Frequency.QUARTERLY),
        }
        vals = {
            date(2023, 12, 31): Money(20.0, "USD", Scale.MILLIONS),
            date(2024, 3, 31): Money(22.0, "USD", Scale.MILLIONS),
            date(2024, 6, 30): Money(24.0, "USD", Scale.MILLIONS),
            date(2024, 9, 30): Money(26.0, "USD", Scale.MILLIONS),
            date(2024, 12, 31): Money(30.0, "USD", Scale.MILLIONS),
        }
        ttm = compute_ttm_from_quarters(ends, vals, latest_end=date(2024, 12, 31), calendar=cal)
        assert ttm is not None
        assert ttm.value == pytest.approx(102.0)
        assert ttm.scale is Scale.MILLIONS

    def test_ttm_insufficient_quarters(self):
        ends = {
            date(2024, 3, 31): Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY),
            date(2024, 6, 30): Period(start=date(2024, 4, 1), end=date(2024, 6, 30), frequency=Frequency.QUARTERLY),
        }
        vals = {
            date(2024, 3, 31): Money(10.0, "USD", Scale.MILLIONS),
            date(2024, 6, 30): Money(12.0, "USD", Scale.MILLIONS),
        }
        ttm = compute_ttm_from_quarters(ends, vals, latest_end=date(2024, 6, 30))
        assert ttm is None

    def test_ttm_missing_value_returns_none(self):
        cal = FiscalCalendar(close_month=12)
        ends = {
            date(2023, 12, 31): Period(start=date(2023, 10, 1), end=date(2023, 12, 31), frequency=Frequency.QUARTERLY),
            date(2024, 3, 31): Period(start=date(2024, 1, 1), end=date(2024, 3, 31), frequency=Frequency.QUARTERLY),
            date(2024, 6, 30): Period(start=date(2024, 4, 1), end=date(2024, 6, 30), frequency=Frequency.QUARTERLY),
            date(2024, 9, 30): Period(start=date(2024, 7, 1), end=date(2024, 9, 30), frequency=Frequency.QUARTERLY),
            date(2024, 12, 31): Period(start=date(2024, 10, 1), end=date(2024, 12, 31), frequency=Frequency.QUARTERLY),
        }
        vals = {
            date(2023, 12, 31): Money(20.0, "USD", Scale.MILLIONS),
            date(2024, 3, 31): Money(22.0, "USD", Scale.MILLIONS),
            date(2024, 6, 30): None,  # ausente
            date(2024, 9, 30): Money(26.0, "USD", Scale.MILLIONS),
            date(2024, 12, 31): Money(30.0, "USD", Scale.MILLIONS),
        }
        ttm = compute_ttm_from_quarters(ends, vals, latest_end=date(2024, 12, 31), calendar=cal)
        assert ttm is None


class TestGrowthRateStrict:
    def test_same_scale(self):
        a = Money(120.0, "USD", Scale.MILLIONS)
        b = Money(100.0, "USD", Scale.MILLIONS)
        assert growth_rate_strict(a, b) == pytest.approx(0.20)

    def test_incompatible_scale_returns_none(self):
        a = Money(120.0, "USD", Scale.MILLIONS)
        b = Money(100000.0, "USD", Scale.UNITS)
        assert growth_rate_strict(a, b) is None

    def test_missing_returns_none(self):
        assert growth_rate_strict(Money(120.0, "USD", Scale.MILLIONS), None) is None
        assert growth_rate_strict(None, Money(100.0, "USD", Scale.MILLIONS)) is None


class TestPeriodDuplication:
    def test_duplicate_period_end_same_date(self):
        state = FinancialState(company="Z", currency="USD")
        p = Period(start=date(2024, 1, 1), end=date(2024, 12, 31), frequency=Frequency.ANNUAL)
        state.add_income_statement(IncomeStatement(period=p, revenue=Money(100.0, "USD", Scale.MILLIONS)))
        state.add_income_statement(IncomeStatement(period=p, revenue=Money(105.0, "USD", Scale.MILLIONS)))
        m = FinancialMetrics.from_state(state, latest_end=date(2024, 12, 31))
        assert m.revenue.value == pytest.approx(105.0)


class TestTTMQuarterlyDurationRegression:
    """Regresión: un periodo anual no puede contarse como trimestre.

    Con datos reales de Apple se detectó que el TTM sumaba el ejercicio anual más
    dos trimestres (679 390 millones) porque solo se miraba la distancia entre
    fechas de cierre, sin comprobar la duración de cada periodo.
    """

    def test_annual_period_is_not_used_as_quarter(self):
        from nexo_invest.core.periods import is_quarterly_period, ttm_periods
        from nexo_invest.core.units import Frequency, Period

        annual = Period(start=date(2022, 9, 25), end=date(2023, 9, 30), frequency=Frequency.ANNUAL)
        q1 = Period(start=date(2023, 10, 1), end=date(2023, 12, 30), frequency=Frequency.QUARTERLY)
        q2 = Period(start=date(2023, 12, 31), end=date(2024, 3, 30), frequency=Frequency.QUARTERLY)
        q3 = Period(start=date(2024, 3, 31), end=date(2024, 6, 29), frequency=Frequency.QUARTERLY)

        assert is_quarterly_period(annual) is False
        assert is_quarterly_period(q1) is True

        selection = ttm_periods(
            {annual.end: annual, q1.end: q1, q2.end: q2, q3.end: q3},
            latest_end=date(2024, 6, 29),
        )
        assert date(2023, 9, 30) not in selection
        assert len(selection) == 3, "solo hay tres trimestres reales"

    def test_four_real_quarters_are_selected(self):
        from nexo_invest.core.periods import ttm_periods
        from nexo_invest.core.units import Frequency, Period

        quarters = [
            Period(start=date(2023, 10, 1), end=date(2023, 12, 30), frequency=Frequency.QUARTERLY),
            Period(start=date(2023, 12, 31), end=date(2024, 3, 30), frequency=Frequency.QUARTERLY),
            Period(start=date(2024, 3, 31), end=date(2024, 6, 29), frequency=Frequency.QUARTERLY),
            Period(start=date(2024, 6, 30), end=date(2024, 9, 28), frequency=Frequency.QUARTERLY),
        ]
        selection = ttm_periods(
            {q.end: q for q in quarters}, latest_end=date(2024, 9, 28)
        )
        assert len(selection) == 4
        assert selection == [q.end for q in quarters]

    def test_overlapping_periods_are_rejected(self):
        from nexo_invest.core.periods import ttm_periods
        from nexo_invest.core.units import Frequency, Period

        # Dos periodos que se solapan no son trimestres consecutivos distintos.
        a = Period(start=date(2023, 10, 1), end=date(2023, 12, 30), frequency=Frequency.QUARTERLY)
        b = Period(start=date(2023, 10, 15), end=date(2024, 1, 15), frequency=Frequency.QUARTERLY)
        c = Period(start=date(2024, 1, 16), end=date(2024, 4, 15), frequency=Frequency.QUARTERLY)
        d = Period(start=date(2024, 4, 16), end=date(2024, 7, 15), frequency=Frequency.QUARTERLY)
        selection = ttm_periods(
            {p.end: p for p in (a, b, c, d)}, latest_end=date(2024, 7, 15)
        )
        assert len(selection) < 4
