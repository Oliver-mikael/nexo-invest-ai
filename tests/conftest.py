from __future__ import annotations

import pytest
from datetime import date

from nexo_invest.core.units import Money, Period, Frequency, Scale
from nexo_invest.core.metrics import FinancialState, IncomeStatement, BalanceSheet, CashFlow


@pytest.fixture
def example_state() -> FinancialState:
    state = FinancialState(company="Ejemplo S.A.", currency="USD")
    p1 = Period(start=date(2023, 1, 1), end=date(2023, 12, 31), frequency=Frequency.ANNUAL)
    p2 = Period(start=date(2024, 1, 1), end=date(2024, 12, 31), frequency=Frequency.ANNUAL)
    state.add_income_statement(
        IncomeStatement(
            period=p1,
            revenue=Money(100.0, "USD", Scale.MILLIONS),
            gross_profit=Money(50.0, "USD", Scale.MILLIONS),
            operating_income=Money(18.0, "USD", Scale.MILLIONS),
            net_income=Money(12.0, "USD", Scale.MILLIONS),
            ebitda=Money(22.0, "USD", Scale.MILLIONS),
        )
    )
    state.add_income_statement(
        IncomeStatement(
            period=p2,
            revenue=Money(120.0, "USD", Scale.MILLIONS),
            gross_profit=Money(60.0, "USD", Scale.MILLIONS),
            operating_income=Money(21.0, "USD", Scale.MILLIONS),
            net_income=Money(14.0, "USD", Scale.MILLIONS),
            ebitda=Money(25.0, "USD", Scale.MILLIONS),
        )
    )
    state.add_balance_sheet(
        BalanceSheet(
            period=p2,
            total_debt=Money(80.0, "USD", Scale.MILLIONS),
            cash_and_equivalents=Money(20.0, "USD", Scale.MILLIONS),
            invested_capital=Money(400.0, "USD", Scale.MILLIONS),
        )
    )
    state.add_cash_flow(
        CashFlow(
            period=p2,
            operating_cash_flow=Money(28.0, "USD", Scale.MILLIONS),
            capital_expenditures=Money(5.0, "USD", Scale.MILLIONS),
            free_cash_flow=Money(23.0, "USD", Scale.MILLIONS),
        )
    )
    return state
