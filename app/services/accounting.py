"""Contabilidad de la cartera real, independiente de la cartera simulada.

Principios:

- Todos los importes se calculan con `Decimal`. La base de datos usa `Numeric`;
  SQLite la almacena con afinidad numérica, pero el motor nunca opera con `float`.
- El tipo de cambio de cada movimiento se guarda con el movimiento y no se
  recalcula: una operación histórica conserva el cambio aplicado entonces.
- Se calculan FIFO y coste medio. La cuenta elige cuál se usa como método
  principal; el otro queda disponible para comparación y auditoría.
- Una posición sin cotización o sin tipo de cambio se marca como no valorada.
  Nunca se rellena un precio con el coste ni se presenta como mercado.
- Los flujos externos (aportes, retiros, traspasos y ajustes de conciliación)
  alimentan XIRR y TWR. Dividendos, comisiones e impuestos son resultado, no
  aportes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

ZERO = Decimal("0")
ONE = Decimal("1")
CENT = Decimal("0.01")
UNIT = Decimal("0.0000000001")

MOVEMENT_TYPES = {
    "deposit",
    "withdrawal",
    "buy",
    "sell",
    "dividend",
    "fee",
    "tax",
    "adjustment",
    "split",
    "transfer_in",
    "transfer_out",
}

INSTRUMENT_TYPES = {"stock", "etf", "index", "fund", "bond", "reit", "crypto", "other"}
COST_METHODS = {"fifo", "average"}


class LedgerError(ValueError):
    """El movimiento no es contablemente válido."""


def dec(value: Any) -> Decimal:
    """Convierte de forma segura a Decimal (nunca pasa por binario si es texto)."""
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return ZERO
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value))


def qty(value: Any) -> Decimal:
    return dec(value).quantize(UNIT, rounding=ROUND_HALF_UP)


def money(value: Any) -> Decimal:
    return dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        raise LedgerError("división por cero en el cálculo contable")
    return numerator / denominator


@dataclass(frozen=True)
class InstrumentInfo:
    id: int
    uid: str
    symbol: str
    name: str
    currency: str
    country_code: str
    market_code: str
    instrument_type: str


@dataclass(frozen=True)
class LedgerMovement:
    id: int
    kind: str
    date: date
    instrument_id: Optional[int]
    currency: str
    quantity: Decimal = ZERO
    price: Decimal = ZERO
    amount: Decimal = ZERO
    fee: Decimal = ZERO
    tax: Decimal = ZERO
    fx_rate: Decimal = ONE
    transfer_group: Optional[str] = None
    transfer_cost_basis: Optional[Decimal] = None
    note: str = ""

    @property
    def is_external(self) -> bool:
        return self.kind in {
            "deposit",
            "withdrawal",
            "adjustment",
            "transfer_in",
            "transfer_out",
        }


@dataclass
class QuotePoint:
    price: Decimal
    as_of: date
    source: str = ""
    quality: str = "close"

    @property
    def is_market(self) -> bool:
        return self.source not in {"", "cost"} and self.quality != "estimated"


@dataclass
class Lot:
    quantity: Decimal
    unit_cost_local: Decimal
    unit_cost_base: Decimal
    acquired: date
    movement_id: int


@dataclass
class PositionBook:
    instrument: InstrumentInfo
    lots: List[Lot] = field(default_factory=list)
    quantity: Decimal = ZERO
    avg_cost_local: Decimal = ZERO
    avg_cost_base: Decimal = ZERO
    realized_local: Decimal = ZERO
    realized_base: Decimal = ZERO
    dividend_local: Decimal = ZERO
    dividend_base: Decimal = ZERO
    dividend_tax_base: Decimal = ZERO
    sell_fees_base: Decimal = ZERO
    sell_taxes_base: Decimal = ZERO
    price_effect_base: Decimal = ZERO
    fx_effect_base: Decimal = ZERO

    @property
    def fifo_cost_local(self) -> Decimal:
        return sum((lot.quantity * lot.unit_cost_local for lot in self.lots), ZERO)

    @property
    def fifo_cost_base(self) -> Decimal:
        return sum((lot.quantity * lot.unit_cost_base for lot in self.lots), ZERO)

    @property
    def average_cost_local(self) -> Decimal:
        return self.avg_cost_local

    @property
    def average_cost_base(self) -> Decimal:
        return self.avg_cost_base


@dataclass
class ReplayResult:
    base_currency: str
    cost_method: str
    cash: Dict[str, Decimal] = field(default_factory=dict)
    positions: Dict[int, PositionBook] = field(default_factory=dict)
    external_flows: List[Tuple[date, Decimal]] = field(default_factory=list)
    other_fees_base: Decimal = ZERO
    other_taxes_base: Decimal = ZERO
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    movements: int = 0

    def position(self, instrument: InstrumentInfo) -> PositionBook:
        book = self.positions.get(instrument.id)
        if book is None:
            book = PositionBook(instrument=instrument)
            self.positions[instrument.id] = book
        return book


def _flow_base(movement: LedgerMovement) -> Decimal:
    """Valor en moneda base de un flujo externo (positivo = aporte)."""
    if movement.kind in {"transfer_in", "transfer_out"}:
        if movement.instrument_id is None:
            gross = movement.amount * movement.fx_rate
        else:
            gross = movement.transfer_cost_basis or ZERO
        return gross if movement.kind == "transfer_in" else -gross
    if movement.kind == "deposit":
        return movement.amount * movement.fx_rate
    if movement.kind == "withdrawal":
        return -movement.amount * movement.fx_rate
    if movement.kind == "adjustment":
        return (movement.amount - movement.fee - movement.tax) * movement.fx_rate
    return ZERO


def _validate(
    movement: LedgerMovement,
    instruments: Dict[int, InstrumentInfo],
    base_currency: str,
) -> List[str]:
    problems: List[str] = []
    if movement.kind not in MOVEMENT_TYPES:
        problems.append(f"tipo de movimiento desconocido: {movement.kind}")
    if movement.fx_rate <= 0:
        problems.append("el tipo de cambio debe ser positivo")
    if movement.quantity < 0 or movement.fee < 0 or movement.tax < 0:
        problems.append("cantidad, comisión e impuesto no pueden ser negativos")
    needs_instrument = movement.kind in {
        "buy",
        "sell",
        "dividend",
        "split",
        "transfer_in",
        "transfer_out",
    }
    if needs_instrument and movement.instrument_id is None:
        problems.append(f"{movement.kind} requiere un instrumento")
    if movement.instrument_id is not None:
        instrument = instruments.get(movement.instrument_id)
        if instrument is None:
            problems.append("el instrumento no existe")
        elif movement.currency.upper() != instrument.currency.upper():
            problems.append(
                f"la moneda del movimiento ({movement.currency}) no coincide con la del "
                f"instrumento ({instrument.currency})"
            )
        if movement.kind in {"transfer_in", "transfer_out"}:
            if movement.quantity <= 0:
                problems.append("los traspasos de valores requieren cantidad positiva")
            if movement.transfer_cost_basis is None:
                problems.append("los traspasos de valores requieren coste de adquisición")
            elif movement.transfer_cost_basis < 0:
                problems.append("el coste de adquisición no puede ser negativo")
    if movement.kind in {"deposit", "withdrawal", "fee", "tax"} and movement.amount <= 0:
        problems.append(f"{movement.kind} requiere un importe positivo")
    if movement.kind == "buy" and (movement.quantity <= 0 or movement.price < 0):
        problems.append("la compra requiere cantidad positiva y precio no negativo")
    if movement.kind == "sell" and (movement.quantity <= 0 or movement.price <= 0):
        problems.append("la venta requiere cantidad y precio positivos")
    if movement.kind == "dividend" and movement.amount <= 0:
        problems.append("el dividendo requiere importe bruto positivo")
    if movement.kind in {"deposit", "withdrawal", "split", "transfer_in", "transfer_out"} and (
        movement.fee or movement.tax
    ):
        problems.append("este tipo de movimiento no admite comisión ni impuesto; regístralos aparte")
    if movement.kind == "split" and movement.quantity == 0:
        problems.append("el split requiere una variación de cantidad distinta de cero")
    if movement.kind == "adjustment" and movement.amount == 0 and movement.fee == 0 and movement.tax == 0:
        problems.append("el ajuste requiere un importe distinto de cero")
    if movement.kind == "transfer_in" and movement.instrument_id is None and movement.amount <= 0:
        problems.append("el traspaso de efectivo entrante requiere importe positivo")
    if movement.kind == "transfer_out" and movement.instrument_id is None and movement.amount <= 0:
        problems.append("el traspaso de efectivo saliente requiere importe positivo")
    if movement.currency.upper() == base_currency.upper() and movement.fx_rate != ONE:
        problems.append("si la moneda del movimiento es la moneda base, el cambio debe ser 1")
    return problems


def _apply_buy(
    book: PositionBook,
    movement: LedgerMovement,
    cash: Dict[str, Decimal],
    base_currency: str,
) -> None:
    gross = movement.quantity * movement.price
    cost_local = gross + movement.fee + movement.tax
    cost_base = cost_local * movement.fx_rate
    # El efectivo de la cuenta se lleva en su moneda base al cambio histórico.
    cash[base_currency] = cash.get(base_currency, ZERO) - cost_base
    book.lots.append(
        Lot(
            quantity=movement.quantity,
            unit_cost_local=_ratio(cost_local, movement.quantity),
            unit_cost_base=_ratio(cost_base, movement.quantity),
            acquired=movement.date,
            movement_id=movement.id,
        )
    )
    book.quantity += movement.quantity
    book.avg_cost_local += cost_local
    book.avg_cost_base += cost_base


def _consume_fifo(book: PositionBook, quantity: Decimal) -> Tuple[Decimal, Decimal]:
    remaining = quantity
    cost_local = ZERO
    cost_base = ZERO
    while remaining > 0 and book.lots:
        lot = book.lots[0]
        take = min(lot.quantity, remaining)
        cost_local += take * lot.unit_cost_local
        cost_base += take * lot.unit_cost_base
        lot.quantity -= take
        remaining -= take
        if lot.quantity <= 0:
            book.lots.pop(0)
    if remaining > 0:
        raise LedgerError("la venta supera la cantidad disponible")
    avg_removed_local = book.avg_cost_local * _ratio(quantity, book.quantity)
    avg_removed_base = book.avg_cost_base * _ratio(quantity, book.quantity)
    book.quantity -= quantity
    book.avg_cost_local = max(ZERO, book.avg_cost_local - avg_removed_local)
    book.avg_cost_base = max(ZERO, book.avg_cost_base - avg_removed_base)
    return cost_local, cost_base


def _consume_average(book: PositionBook, quantity: Decimal) -> Tuple[Decimal, Decimal]:
    if quantity > book.quantity:
        raise LedgerError("la venta supera la cantidad disponible")
    cost_local = book.avg_cost_local * _ratio(quantity, book.quantity)
    cost_base = book.avg_cost_base * _ratio(quantity, book.quantity)
    book.quantity -= quantity
    book.avg_cost_local -= cost_local
    book.avg_cost_base -= cost_base
    if book.quantity <= 0:
        book.quantity = ZERO
        book.avg_cost_local = ZERO
        book.avg_cost_base = ZERO

    # FIFO también se conserva para poder comparar métodos; se consume en paralelo.
    remaining = quantity
    while remaining > 0 and book.lots:
        lot = book.lots[0]
        take = min(lot.quantity, remaining)
        lot.quantity -= take
        remaining -= take
        if lot.quantity <= 0:
            book.lots.pop(0)
    return cost_local, cost_base


def _apply_sell(
    book: PositionBook,
    movement: LedgerMovement,
    cash: Dict[str, Decimal],
    method: str,
    base_currency: str,
) -> None:
    if movement.quantity > book.quantity:
        raise LedgerError(
            f"venta de {movement.quantity} {book.instrument.symbol} sin posición suficiente "
            f"({book.quantity})"
        )
    if method == "average":
        cost_local, cost_base = _consume_average(book, movement.quantity)
    else:
        cost_local, cost_base = _consume_fifo(book, movement.quantity)
    gross_local = movement.quantity * movement.price
    net_local = gross_local - movement.fee - movement.tax
    net_base = net_local * movement.fx_rate
    cash[base_currency] = cash.get(base_currency, ZERO) + net_base
    realized_local = net_local - cost_local
    realized_base = net_base - cost_base
    book.realized_local += realized_local
    book.realized_base += realized_base
    book.sell_fees_base += movement.fee * movement.fx_rate
    book.sell_taxes_base += movement.tax * movement.fx_rate
    # Efecto precio valorado al cambio de la venta; el resto es efecto cambiario.
    price_effect = realized_local * movement.fx_rate
    book.price_effect_base += price_effect
    book.fx_effect_base += realized_base - price_effect


def _apply_split(book: PositionBook, movement: LedgerMovement) -> None:
    if book.quantity <= 0:
        raise LedgerError("no se puede aplicar un split sin posición")
    new_quantity = book.quantity + movement.quantity
    if new_quantity <= 0:
        raise LedgerError("el split dejaría una cantidad nula o negativa")
    factor = _ratio(new_quantity, book.quantity)
    for lot in book.lots:
        lot.quantity *= factor
        lot.unit_cost_local = _ratio(lot.unit_cost_local, factor)
        lot.unit_cost_base = _ratio(lot.unit_cost_base, factor)
    book.quantity = new_quantity
    book.avg_cost_local = book.fifo_cost_local
    book.avg_cost_base = book.fifo_cost_base


def _apply_transfer_in(book: PositionBook, movement: LedgerMovement) -> None:
    if movement.transfer_cost_basis is None:
        raise LedgerError("el traspaso entrante requiere coste de adquisición")
    basis = movement.transfer_cost_basis
    unit_local = _ratio(basis, movement.fx_rate) / movement.quantity
    book.lots.append(
        Lot(
            quantity=movement.quantity,
            unit_cost_local=unit_local,
            unit_cost_base=_ratio(basis, movement.quantity),
            acquired=movement.date,
            movement_id=movement.id,
        )
    )
    book.quantity += movement.quantity
    book.avg_cost_local += unit_local * movement.quantity
    book.avg_cost_base += basis


def replay(
    *,
    base_currency: str,
    cost_method: str,
    instruments: Dict[int, InstrumentInfo],
    movements: Sequence[LedgerMovement],
    allow_negative_cash: bool = False,
    allow_short: bool = False,
    collect_errors: bool = False,
) -> ReplayResult:
    """Reproduce el libro de una cuenta en orden cronológico.

    Con `collect_errors=False` (creación de una operación) el primer problema
    lanza `LedgerError`. Con `collect_errors=True` (valoración de datos ya
    guardados) se anota el problema y se continúa para no ocultar el resto.
    """

    method = cost_method if cost_method in COST_METHODS else "fifo"
    result = ReplayResult(base_currency=base_currency.upper(), cost_method=method)
    ordered = sorted(movements, key=lambda item: (item.date, item.id))
    base = result.base_currency
    for movement in ordered:
        problems = _validate(movement, instruments, base)
        if problems:
            if collect_errors:
                result.errors.append(f"movimiento {movement.id}: " + "; ".join(problems))
                continue
            raise LedgerError("; ".join(problems))
        result.movements += 1
        book: Optional[PositionBook] = None
        if movement.instrument_id is not None:
            instrument = instruments[movement.instrument_id]
            book = result.position(instrument)
        try:
            if movement.kind == "deposit":
                result.cash[base] = (
                    result.cash.get(base, ZERO) + movement.amount * movement.fx_rate
                )
                result.external_flows.append((movement.date, _flow_base(movement)))
            elif movement.kind == "withdrawal":
                result.cash[base] = (
                    result.cash.get(base, ZERO) - movement.amount * movement.fx_rate
                )
                result.external_flows.append((movement.date, _flow_base(movement)))
            elif movement.kind == "buy":
                assert book is not None
                _apply_buy(book, movement, result.cash, base)
            elif movement.kind == "sell":
                assert book is not None
                _apply_sell(book, movement, result.cash, method, base)
            elif movement.kind == "dividend":
                assert book is not None
                net = movement.amount - movement.fee - movement.tax
                result.cash[base] = (
                    result.cash.get(base, ZERO) + net * movement.fx_rate
                )
                book.dividend_local += movement.amount
                book.dividend_base += movement.amount * movement.fx_rate
                book.dividend_tax_base += movement.tax * movement.fx_rate
                # La comisión de cobro no es una retención: se contabiliza como gasto.
                result.other_fees_base += movement.fee * movement.fx_rate
            elif movement.kind == "fee":
                total = movement.amount + movement.fee + movement.tax
                result.cash[base] = (
                    result.cash.get(base, ZERO) - total * movement.fx_rate
                )
                result.other_fees_base += total * movement.fx_rate
                if book is not None:
                    book.sell_fees_base += total * movement.fx_rate
            elif movement.kind == "tax":
                total = movement.amount + movement.fee + movement.tax
                result.cash[base] = (
                    result.cash.get(base, ZERO) - total * movement.fx_rate
                )
                result.other_taxes_base += total * movement.fx_rate
                if book is not None:
                    book.sell_taxes_base += total * movement.fx_rate
            elif movement.kind == "adjustment":
                result.cash[base] = (
                    result.cash.get(base, ZERO)
                    + (movement.amount - movement.fee - movement.tax) * movement.fx_rate
                )
                result.external_flows.append((movement.date, _flow_base(movement)))
            elif movement.kind == "split":
                assert book is not None
                _apply_split(book, movement)
            elif movement.kind in {"transfer_in", "transfer_out"}:
                if movement.instrument_id is None:
                    sign = ONE if movement.kind == "transfer_in" else -ONE
                    result.cash[base] = (
                        result.cash.get(base, ZERO)
                        + sign * movement.amount * movement.fx_rate
                    )
                else:
                    assert book is not None
                    if movement.kind == "transfer_in":
                        _apply_transfer_in(book, movement)
                        result.external_flows.append((movement.date, _flow_base(movement)))
                    else:
                        if movement.quantity > book.quantity:
                            raise LedgerError("el traspaso supera la posición disponible")
                        if method == "average":
                            _, removed_base = _consume_average(book, movement.quantity)
                        else:
                            _, removed_base = _consume_fifo(book, movement.quantity)
                        # Un traspaso de valores sale a coste: usar otro importe
                        # crearía una ganancia o pérdida ficticia.
                        result.external_flows.append((movement.date, -removed_base))
                if movement.instrument_id is None:
                    result.external_flows.append((movement.date, _flow_base(movement)))
        except LedgerError as exc:
            if collect_errors:
                result.errors.append(f"movimiento {movement.id}: {exc}")
                continue
            raise

    for currency, value in result.cash.items():
        if value < 0 and not allow_negative_cash:
            message = f"efectivo negativo en {currency}: {money(value)}"
            if collect_errors:
                result.warnings.append(message)
            else:
                raise LedgerError(message)
        if value == 0:
            continue
    for book in result.positions.values():
        if book.quantity < 0 and not allow_short:
            message = f"posición corta no permitida en {book.instrument.symbol}"
            if collect_errors:
                result.warnings.append(message)
            else:
                raise LedgerError(message)
    return result


@dataclass
class PositionValuation:
    instrument: InstrumentInfo
    quantity: Decimal
    cost_local: Decimal
    cost_base: Decimal
    price: Optional[Decimal]
    quote_as_of: Optional[date]
    quote_source: str
    market_value_local: Optional[Decimal]
    market_value_base: Optional[Decimal]
    unrealized_base: Optional[Decimal]
    price_effect_base: Optional[Decimal]
    fx_effect_base: Optional[Decimal]
    realized_base: Decimal
    dividend_base: Decimal
    weight: Optional[Decimal] = None


@dataclass
class PortfolioValuation:
    as_of: date
    base_currency: str
    cost_method: str
    cash: Dict[str, Decimal]
    cash_base: Decimal
    cash_complete: bool
    positions: List[PositionValuation]
    realized_base: Decimal
    unrealized_base: Decimal
    dividends_base: Decimal
    other_fees_base: Decimal
    other_taxes_base: Decimal
    market_value_base: Decimal
    total_value_base: Optional[Decimal]
    net_contributions_base: Decimal
    net_gain_base: Optional[Decimal]
    net_return_pct: Optional[Decimal]
    complete: bool
    missing_prices: List[str]
    missing_fx: List[str]
    warnings: List[str]

    def as_dict(self) -> Dict[str, Any]:
        def text(value: Optional[Decimal]) -> Optional[str]:
            return None if value is None else str(value.quantize(CENT, ROUND_HALF_UP))

        return {
            "as_of": self.as_of.isoformat(),
            "base_currency": self.base_currency,
            "cost_method": self.cost_method,
            "cash": {key: text(value) for key, value in sorted(self.cash.items())},
            "cash_base": text(self.cash_base),
            "cash_complete": self.cash_complete,
            "market_value_base": text(self.market_value_base),
            "total_value_base": text(self.total_value_base),
            "net_contributions_base": text(self.net_contributions_base),
            "net_gain_base": text(self.net_gain_base),
            "net_return_pct": (
                None
                if self.net_return_pct is None
                else str((self.net_return_pct * 100).quantize(CENT, ROUND_HALF_UP))
            ),
            "realized_base": text(self.realized_base),
            "unrealized_base": text(self.unrealized_base),
            "dividends_base": text(self.dividends_base),
            "other_fees_base": text(self.other_fees_base),
            "other_taxes_base": text(self.other_taxes_base),
            "complete": self.complete,
            "missing_prices": self.missing_prices,
            "missing_fx": self.missing_fx,
            "warnings": self.warnings,
            "positions": [
                {
                    "instrument_uid": item.instrument.uid,
                    "symbol": item.instrument.symbol,
                    "name": item.instrument.name,
                    "market": item.instrument.market_code,
                    "country_code": item.instrument.country_code,
                    "instrument_type": item.instrument.instrument_type,
                    "currency": item.instrument.currency,
                    "quantity": str(item.quantity.quantize(UNIT, ROUND_HALF_UP)),
                    "cost_local": text(item.cost_local),
                    "cost_base": text(item.cost_base),
                    "price": None if item.price is None else str(item.price),
                    "quote_as_of": item.quote_as_of.isoformat() if item.quote_as_of else None,
                    "quote_source": item.quote_source,
                    "market_value_local": text(item.market_value_local),
                    "market_value_base": text(item.market_value_base),
                    "unrealized_base": text(item.unrealized_base),
                    "price_effect_base": text(item.price_effect_base),
                    "fx_effect_base": text(item.fx_effect_base),
                    "realized_base": text(item.realized_base),
                    "dividends_base": text(item.dividend_base),
                    "weight": None if item.weight is None else str(item.weight),
                }
                for item in self.positions
            ],
        }


def value_portfolio(
    result: ReplayResult,
    *,
    as_of: date,
    quotes: Dict[int, QuotePoint],
    fx_rates: Dict[str, QuotePoint],
    warnings: Optional[Iterable[str]] = None,
) -> PortfolioValuation:
    """Valora una cuenta con las cotizaciones y tipos de cambio disponibles.

    `fx_rates` mapea una moneda a su tipo de cambio hacia la moneda base de la
    cuenta. La ausencia de una cotización no se sustituye por el coste: se marca
    como dato faltante y el total se devuelve como parcial.
    """

    base = result.base_currency
    cash_base = ZERO
    cash_complete = True
    missing_prices: List[str] = []
    missing_fx: List[str] = []
    for currency, amount in result.cash.items():
        if amount == 0:
            continue
        if currency == base:
            cash_base += amount
            continue
        point = fx_rates.get(currency)
        if point is None or point.price <= 0:
            cash_complete = False
            missing_fx.append(currency)
            continue
        cash_base += amount * point.price

    positions: List[PositionValuation] = []
    market_value = ZERO
    unrealized = ZERO
    realized = ZERO
    dividends = ZERO
    complete = cash_complete
    for book in result.positions.values():
        if book.quantity <= 0:
            realized += book.realized_base
            dividends += book.dividend_base - book.dividend_tax_base
            continue
        price_point = quotes.get(book.instrument.id)
        cost_local = (
            book.average_cost_local if result.cost_method == "average" else book.fifo_cost_local
        )
        cost_base = (
            book.average_cost_base if result.cost_method == "average" else book.fifo_cost_base
        )
        if price_point is None or price_point.price <= 0:
            missing_prices.append(book.instrument.uid)
            complete = False
            positions.append(
                PositionValuation(
                    instrument=book.instrument,
                    quantity=book.quantity,
                    cost_local=cost_local,
                    cost_base=cost_base,
                    price=None,
                    quote_as_of=None,
                    quote_source="",
                    market_value_local=None,
                    market_value_base=None,
                    unrealized_base=None,
                    price_effect_base=None,
                    fx_effect_base=None,
                    realized_base=book.realized_base,
                    dividend_base=book.dividend_base - book.dividend_tax_base,
                )
            )
            realized += book.realized_base
            dividends += book.dividend_base - book.dividend_tax_base
            continue
        fx_point = (
            QuotePoint(ONE, as_of, "identity", "close")
            if book.instrument.currency == base
            else fx_rates.get(book.instrument.currency)
        )
        if fx_point is None or fx_point.price <= 0:
            missing_fx.append(book.instrument.currency)
            complete = False
            positions.append(
                PositionValuation(
                    instrument=book.instrument,
                    quantity=book.quantity,
                    cost_local=cost_local,
                    cost_base=cost_base,
                    price=price_point.price,
                    quote_as_of=price_point.as_of,
                    quote_source=price_point.source,
                    market_value_local=None,
                    market_value_base=None,
                    unrealized_base=None,
                    price_effect_base=None,
                    fx_effect_base=None,
                    realized_base=book.realized_base,
                    dividend_base=book.dividend_base - book.dividend_tax_base,
                )
            )
            realized += book.realized_base
            dividends += book.dividend_base - book.dividend_tax_base
            continue
        local_value = book.quantity * price_point.price
        base_value = local_value * fx_point.price
        position_unrealized = base_value - cost_base
        local_gain = local_value - cost_local
        price_effect = local_gain * fx_point.price
        # Efecto cambiario sobre el coste: coste_local * (cambio actual - cambio de compra).
        fx_effect = cost_local * fx_point.price - cost_base
        market_value += base_value
        unrealized += position_unrealized
        realized += book.realized_base
        dividends += book.dividend_base - book.dividend_tax_base
        positions.append(
            PositionValuation(
                instrument=book.instrument,
                quantity=book.quantity,
                cost_local=cost_local,
                cost_base=cost_base,
                price=price_point.price,
                quote_as_of=price_point.as_of,
                quote_source=price_point.source,
                market_value_local=local_value,
                market_value_base=base_value,
                unrealized_base=position_unrealized,
                price_effect_base=price_effect,
                fx_effect_base=fx_effect,
                realized_base=book.realized_base,
                dividend_base=book.dividend_base - book.dividend_tax_base,
            )
        )
    total_value = cash_base + market_value if complete else None
    for position in positions:
        if total_value and total_value > 0 and position.market_value_base is not None:
            position.weight = position.market_value_base / total_value
    net_contributions = sum((flow for _, flow in result.external_flows), ZERO)
    net_gain = total_value - net_contributions if total_value is not None else None
    net_return = (
        net_gain / net_contributions
        if net_gain is not None and net_contributions > 0
        else None
    )
    extra = list(warnings or [])
    if missing_prices or missing_fx or result.errors:
        extra.append(
            "Valoración incompleta: hay posiciones o divisas sin dato de mercado. "
            "No se ha inventado ningún precio."
        )
    return PortfolioValuation(
        as_of=as_of,
        base_currency=base,
        cost_method=result.cost_method,
        cash=dict(result.cash),
        cash_base=cash_base,
        cash_complete=cash_complete,
        positions=positions,
        realized_base=realized,
        unrealized_base=unrealized,
        dividends_base=dividends,
        other_fees_base=result.other_fees_base,
        other_taxes_base=result.other_taxes_base,
        market_value_base=market_value,
        total_value_base=total_value,
        net_contributions_base=net_contributions,
        net_gain_base=net_gain,
        net_return_pct=net_return,
        complete=complete,
        missing_prices=missing_prices,
        missing_fx=missing_fx,
        warnings=extra,
    )


def consolidate_external_flows(flows: Sequence[Tuple[date, Decimal]]) -> List[Tuple[date, Decimal]]:
    """Agrupa flujos del mismo día; los traspasos internos ya vienen compensados."""
    grouped: Dict[date, Decimal] = {}
    for day, amount in flows:
        grouped[day] = grouped.get(day, ZERO) + amount
    return sorted(grouped.items())


def xirr(flows: Sequence[Tuple[date, Decimal]]) -> Optional[Decimal]:
    """TIR anualizada con capitalización diaria (base 365).

    Los aportes son negativos y los retiros o el valor final, positivos. Se usa
    `float` solo dentro de la búsqueda numérica; el resultado se devuelve en
    `Decimal`. Sin al menos un flujo de cada signo no hay solución única.
    """

    grouped = consolidate_external_flows(flows)
    if not grouped or not any(amount < 0 for _, amount in grouped):
        return None
    if not any(amount > 0 for _, amount in grouped):
        return None
    start = grouped[0][0]
    values = [(float((day - start).days), float(amount)) for day, amount in grouped]

    def npv(rate: float) -> float:
        total = 0.0
        for days, amount in values:
            total += amount / ((1.0 + rate) ** (days / 365.0))
        return total

    low, high = -0.9999, 10.0
    try:
        if npv(low) * npv(high) > 0:
            return None
    except (OverflowError, ZeroDivisionError):
        return None
    for _ in range(200):
        mid = (low + high) / 2
        value = npv(mid)
        if abs(value) < 1e-9:
            break
        if npv(low) * value <= 0:
            high = mid
        else:
            low = mid
    rate = (low + high) / 2
    if rate <= -0.9999:
        return None
    return Decimal(str(rate)).quantize(Decimal("0.000001"), ROUND_HALF_UP)


def twr(
    flows: Sequence[Tuple[date, Decimal]],
    value_on: Callable[[date], Optional[Decimal]],
    *,
    as_of: date,
) -> Optional[Decimal]:
    """Rentabilidad ponderada por tiempo a partir de valoraciones por fecha.

    `flows` son aportes positivos y retiros negativos. `value_on` debe devolver
    el valor de la cartera *después* de los flujos de ese día, o `None` si falta
    algún precio. Sin una valoración completa no se publica TWR.
    """

    grouped = consolidate_external_flows(flows)
    if not grouped:
        return None
    dates = sorted(set(day for day, _ in grouped) | {as_of})
    if len(dates) < 2:
        return None
    flows_by_day = dict(grouped)
    start_value = value_on(dates[0])
    if start_value is None or start_value <= 0:
        return None
    previous = start_value
    growth = ONE
    for day in dates[1:]:
        value = value_on(day)
        if value is None:
            return None
        flow = flows_by_day.get(day, ZERO)
        before = value - flow
        if previous <= 0 or before <= 0:
            return None
        growth *= before / previous
        previous = value
    return growth - ONE


def build_flows(
    result: ReplayResult,
    *,
    final_value: Optional[Decimal],
    as_of: date,
) -> List[Tuple[date, Decimal]]:
    """Flujos para XIRR: aportes negativos, retiros y valor final positivos."""
    flows: List[Tuple[date, Decimal]] = []
    for day, amount in result.external_flows:
        if amount == 0:
            continue
        flows.append((day, -amount))
    if final_value is not None and final_value > 0:
        flows.append((as_of, final_value))
    return sorted(flows)


def xirr_for(
    result: ReplayResult, *, final_value: Optional[Decimal], as_of: date
) -> Optional[Decimal]:
    return xirr(build_flows(result, final_value=final_value, as_of=as_of))
