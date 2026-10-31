"""Motor contable de la cartera real: ejemplos numéricos verificables.

Cada prueba fija cifras conocidas y comprueba el resultado exacto. No se usan
`float` en las entradas ni se aceptan aproximaciones donde el cálculo es exacto.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.accounting import (
    InstrumentInfo,
    LedgerError,
    LedgerMovement,
    QuotePoint,
    build_flows,
    replay,
    twr,
    value_portfolio,
    xirr,
)

AAPL = InstrumentInfo(
    id=1,
    uid="inst-aapl",
    symbol="AAPL",
    name="Apple Inc.",
    currency="USD",
    country_code="US",
    market_code="XNAS",
    instrument_type="stock",
)
SAP = InstrumentInfo(
    id=2,
    uid="inst-sap",
    symbol="SAP",
    name="SAP SE",
    currency="EUR",
    country_code="DE",
    market_code="XETR",
    instrument_type="stock",
)


def movement(
    id: int,
    kind: str,
    *,
    day: str = "2024-01-01",
    instrument=None,
    quantity: str = "0",
    price: str = "0",
    amount: str = "0",
    fee: str = "0",
    tax: str = "0",
    currency: str = "USD",
    fx: str = "1",
    transfer_basis: str | None = None,
) -> LedgerMovement:
    return LedgerMovement(
        id=id,
        kind=kind,
        date=date.fromisoformat(day),
        instrument_id=instrument.id if instrument else None,
        currency=currency,
        quantity=Decimal(quantity),
        price=Decimal(price),
        amount=Decimal(amount),
        fee=Decimal(fee),
        tax=Decimal(tax),
        fx_rate=Decimal(fx),
        transfer_cost_basis=None if transfer_basis is None else Decimal(transfer_basis),
    )


def _replay(items, *, base="USD", method="fifo", allow_negative=False):
    return replay(
        base_currency=base,
        cost_method=method,
        instruments={AAPL.id: AAPL, SAP.id: SAP},
        movements=items,
        allow_negative_cash=allow_negative,
    )


def test_fifo_and_average_cost_differ_on_partial_sale():
    items = [
        movement(1, "deposit", amount="10000"),
        movement(2, "buy", instrument=AAPL, quantity="10", price="100", day="2024-01-02"),
        movement(3, "buy", instrument=AAPL, quantity="10", price="200", day="2024-01-03"),
        movement(
            4,
            "sell",
            instrument=AAPL,
            quantity="10",
            price="300",
            fee="10",
            day="2024-01-04",
        ),
    ]
    fifo = _replay(items, method="fifo")
    book = fifo.positions[AAPL.id]
    assert book.quantity == Decimal("10")
    assert book.realized_local == Decimal("1990")
    assert book.fifo_cost_local == Decimal("2000")
    assert fifo.cash["USD"] == Decimal("9990")

    average = _replay(items, method="average")
    average_book = average.positions[AAPL.id]
    assert average_book.realized_local == Decimal("1490")
    assert average_book.average_cost_local == Decimal("1500")
    assert average_book.fifo_cost_local == Decimal("2000")


def test_dividends_fees_and_taxes_reconcile_with_value():
    items = [
        movement(1, "deposit", amount="1000"),
        movement(2, "buy", instrument=AAPL, quantity="10", price="10", fee="5"),
        movement(
            3,
            "dividend",
            instrument=AAPL,
            amount="20",
            tax="2",
            day="2024-02-01",
        ),
        movement(
            4,
            "sell",
            instrument=AAPL,
            quantity="10",
            price="12",
            fee="1",
            day="2024-03-01",
        ),
    ]
    result = _replay(items)
    book = result.positions[AAPL.id]
    assert book.realized_local == Decimal("14")
    assert book.dividend_local == Decimal("20")
    assert result.cash["USD"] == Decimal("1032")

    valuation = value_portfolio(
        result, as_of=date(2024, 3, 2), quotes={}, fx_rates={}
    )
    assert valuation.total_value_base == Decimal("1032")
    assert valuation.net_contributions_base == Decimal("1000")
    assert valuation.net_gain_base == Decimal("32")
    assert valuation.dividends_base == Decimal("18")
    assert valuation.realized_base == Decimal("14")
    assert valuation.complete is True


def test_fx_effect_is_separate_from_price_effect():
    items = [
        movement(1, "deposit", amount="2000"),
        movement(
            2,
            "buy",
            instrument=SAP,
            quantity="10",
            price="100",
            currency="EUR",
            fx="1.10",
            day="2024-01-02",
        ),
    ]
    result = _replay(items)
    valuation = value_portfolio(
        result,
        as_of=date(2024, 6, 30),
        quotes={SAP.id: QuotePoint(Decimal("120"), date(2024, 6, 28), "manual", "close")},
        fx_rates={"EUR": QuotePoint(Decimal("1.20"), date(2024, 6, 28), "manual", "close")},
    )
    position = valuation.positions[0]
    assert position.cost_base == Decimal("1100.00")
    assert position.market_value_base == Decimal("1440.00")
    assert position.unrealized_base == Decimal("340.00")
    # 200 EUR de ganancia local al cambio actual = 240 USD; 1000 EUR de coste
    # revalorizados por el cambio (1,20 - 1,10) = 100 USD.
    assert position.price_effect_base == Decimal("240.00")
    assert position.fx_effect_base == Decimal("100.00")
    assert valuation.total_value_base == Decimal("2340.00")
    assert valuation.net_gain_base == Decimal("340.00")


def test_split_preserves_cost_basis():
    items = [
        movement(1, "deposit", amount="1000"),
        movement(2, "buy", instrument=AAPL, quantity="10", price="100"),
        movement(3, "split", instrument=AAPL, quantity="10", day="2024-02-01"),
        movement(
            4,
            "sell",
            instrument=AAPL,
            quantity="20",
            price="60",
            day="2024-03-01",
        ),
    ]
    result = _replay(items)
    book = result.positions[AAPL.id]
    assert book.realized_local == Decimal("200")
    assert book.quantity == Decimal("0")


def test_transfer_between_accounts_does_not_create_gain():
    out_items = [
        movement(1, "deposit", amount="1000"),
        movement(2, "buy", instrument=AAPL, quantity="10", price="100"),
        movement(
            3,
            "transfer_out",
            instrument=AAPL,
            quantity="10",
            transfer_basis="1000",
            day="2024-02-01",
        ),
    ]
    incoming = [
        movement(
            4,
            "transfer_in",
            instrument=AAPL,
            quantity="10",
            transfer_basis="1000",
            day="2024-02-01",
        )
    ]
    outgoing = _replay(out_items)
    received = _replay(incoming)
    assert outgoing.positions[AAPL.id].quantity == Decimal("0")
    assert received.positions[AAPL.id].quantity == Decimal("10")

    valuation = value_portfolio(
        received,
        as_of=date(2024, 2, 2),
        quotes={AAPL.id: QuotePoint(Decimal("110"), date(2024, 2, 2), "manual", "close")},
        fx_rates={},
    )
    assert valuation.net_contributions_base == Decimal("1000")
    assert valuation.net_gain_base == Decimal("100")


def test_transfer_out_uses_removed_cost_not_a_claimed_basis():
    # Un traspaso mal declarado (900) no puede fabricar una pérdida de 100.
    items = [
        movement(1, "deposit", amount="1000"),
        movement(2, "buy", instrument=AAPL, quantity="10", price="100"),
        movement(
            3,
            "transfer_out",
            instrument=AAPL,
            quantity="10",
            transfer_basis="900",
            day="2024-02-01",
        ),
    ]
    result = _replay(items)
    assert sum((amount for _, amount in result.external_flows), Decimal("0")) == Decimal("0")
    valuation = value_portfolio(result, as_of=date(2024, 2, 2), quotes={}, fx_rates={})
    assert valuation.net_contributions_base == Decimal("0")
    assert valuation.total_value_base == Decimal("0")
    assert valuation.net_gain_base == Decimal("0")


def test_oversell_and_negative_cash_are_rejected():
    items = [
        movement(1, "deposit", amount="100"),
        movement(2, "buy", instrument=AAPL, quantity="1", price="90"),
    ]
    with pytest.raises(LedgerError):
        _replay(items + [movement(3, "sell", instrument=AAPL, quantity="2", price="90")])
    with pytest.raises(LedgerError):
        _replay(items + [movement(3, "withdrawal", amount="11")])


def test_xirr_matches_known_annual_return():
    # 1.000 → 1.100 en 366 días (2020 fue bisiesto): 9,97 % anualizado a 365 días.
    rate = xirr(
        [
            (date(2020, 1, 1), Decimal("-1000")),
            (date(2021, 1, 1), Decimal("1100")),
        ]
    )
    assert rate is not None
    assert abs(rate - Decimal("0.0997")) < Decimal("0.0002")


def test_twr_neutralizes_the_timing_of_contributions():
    values = {
        date(2024, 1, 1): Decimal("1000"),
        date(2024, 7, 1): Decimal("1200"),  # 1.100 de mercado + 100 aportados
        date(2024, 12, 31): Decimal("1320"),
    }
    result = twr(
        [(date(2024, 1, 1), Decimal("1000")), (date(2024, 7, 1), Decimal("100"))],
        lambda day: values.get(day),
        as_of=date(2024, 12, 31),
    )
    assert result is not None
    assert abs(result - Decimal("0.21")) < Decimal("0.000001")


def test_missing_price_is_reported_not_invented():
    items = [
        movement(1, "deposit", amount="1000"),
        movement(2, "buy", instrument=AAPL, quantity="5", price="100"),
    ]
    result = _replay(items)
    valuation = value_portfolio(result, as_of=date(2024, 2, 1), quotes={}, fx_rates={})
    assert valuation.complete is False
    assert valuation.total_value_base is None
    assert valuation.positions[0].price is None
    assert AAPL.uid in valuation.missing_prices


def test_build_flows_excludes_dividends_and_includes_final_value():
    items = [
        movement(1, "deposit", amount="1000", day="2024-01-01"),
        movement(2, "dividend", instrument=AAPL, amount="10", day="2024-02-01"),
    ]
    result = _replay(items)
    flows = build_flows(result, final_value=Decimal("1010"), as_of=date(2024, 3, 1))
    assert flows == [
        (date(2024, 1, 1), Decimal("-1000")),
        (date(2024, 3, 1), Decimal("1010")),
    ]
