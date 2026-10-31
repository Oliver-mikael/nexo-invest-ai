"""Servicio de cartera real: carga, valoración y métricas explicables.

La cartera real vive en tablas propias (`real_accounts`, `real_movements`). No
comparte saldos, operaciones ni resultados con la cartera simulada (`portfolios`,
`trades`). Cualquier suma consolidada se calcula por moneda base y nunca mezcla
monedas sin un tipo de cambio explícito.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import FxRate, Instrument, Market, Quote, RealAccount, RealMovement
from app.services.accounting import (
    LedgerMovement,
    QuotePoint,
    ReplayResult,
    ZERO,
    InstrumentInfo,
    build_flows,
    dec,
    money,
    replay,
    twr,
    value_portfolio,
    xirr,
)

QUALITY_RANK = {
    "realtime": 5,
    "delayed": 4,
    "close": 3,
    "historical": 2,
    "estimated": 1,
}


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def instrument_map(session: Session, ids: Iterable[int]) -> Dict[int, InstrumentInfo]:
    wanted = sorted({int(value) for value in ids})
    if not wanted:
        return {}
    rows = session.execute(
        select(Instrument, Market.code)
        .join(Market, Market.id == Instrument.market_id)
        .where(Instrument.id.in_(wanted))
    ).all()
    result: Dict[int, InstrumentInfo] = {}
    for instrument, market_code in rows:
        result[instrument.id] = InstrumentInfo(
            id=instrument.id,
            uid=instrument.uid,
            symbol=instrument.symbol,
            name=instrument.name,
            currency=instrument.currency.upper(),
            country_code=instrument.country_code,
            market_code=market_code,
            instrument_type=instrument.instrument_type,
        )
    return result


def ledger_movements(session: Session, account_id: int) -> List[LedgerMovement]:
    rows = (
        session.execute(
            select(RealMovement)
            .where(RealMovement.account_id == account_id)
            .order_by(RealMovement.movement_date, RealMovement.id)
        )
        .scalars()
        .all()
    )
    return [
        LedgerMovement(
            id=row.id,
            kind=row.movement_type,
            date=row.movement_date,
            instrument_id=row.instrument_id,
            currency=row.currency.upper(),
            quantity=dec(row.quantity),
            price=dec(row.price),
            amount=dec(row.amount),
            fee=dec(row.fee),
            tax=dec(row.tax),
            fx_rate=dec(row.fx_rate),
            transfer_group=row.transfer_group,
            transfer_cost_basis=(
                None if row.transfer_cost_basis is None else dec(row.transfer_cost_basis)
            ),
            note=row.notes or "",
        )
        for row in rows
    ]


def latest_quotes(
    session: Session,
    instrument_ids: Iterable[int],
    as_of: date,
    user_id: Optional[int] = None,
) -> Dict[int, QuotePoint]:
    wanted = sorted({int(value) for value in instrument_ids})
    if not wanted:
        return {}
    visibility = Quote.user_id.is_(None)
    if user_id is not None:
        visibility = or_(visibility, Quote.user_id == user_id)
    rows = (
        session.execute(
            select(Quote)
            .where(
                Quote.instrument_id.in_(wanted),
                Quote.as_of <= as_of,
                visibility,
            )
            .order_by(Quote.as_of.desc(), Quote.retrieved_at.desc())
        )
        .scalars()
        .all()
    )
    chosen: Dict[int, Quote] = {}
    for row in rows:
        current = chosen.get(row.instrument_id)
        if current is None:
            chosen[row.instrument_id] = row
            continue
        if row.as_of > current.as_of:
            chosen[row.instrument_id] = row
        elif row.as_of == current.as_of:
            row_rank = QUALITY_RANK.get(row.quality, 0)
            current_rank = QUALITY_RANK.get(current.quality, 0)
            # Ante la misma fecha y calidad, la corrección del propio usuario manda
            # sobre el dato global del proveedor.
            row_rank = row_rank + (1 if row.user_id is not None else 0)
            current_rank = current_rank + (1 if current.user_id is not None else 0)
            if row_rank > current_rank:
                chosen[row.instrument_id] = row
    return {
        instrument_id: QuotePoint(
            price=dec(row.price),
            as_of=row.as_of,
            source=row.source,
            quality=row.quality,
        )
        for instrument_id, row in chosen.items()
    }


def fx_rates_to(
    session: Session,
    base_currency: str,
    currencies: Iterable[str],
    as_of: date,
    user_id: Optional[int] = None,
) -> Dict[str, QuotePoint]:
    base = base_currency.upper()
    wanted = {currency.upper() for currency in currencies if currency.upper() != base}
    rates: Dict[str, QuotePoint] = {}
    visibility = FxRate.user_id.is_(None)
    if user_id is not None:
        visibility = or_(visibility, FxRate.user_id == user_id)
    for currency in wanted:
        direct = (
            session.execute(
                select(FxRate)
                .where(
                    FxRate.base_currency == currency,
                    FxRate.quote_currency == base,
                    FxRate.as_of <= as_of,
                    visibility,
                )
                .order_by(FxRate.as_of.desc(), FxRate.retrieved_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if direct is not None and dec(direct.rate) > 0:
            rates[currency] = QuotePoint(
                price=dec(direct.rate),
                as_of=direct.as_of,
                source=direct.source,
                quality=direct.quality,
            )
            continue
        inverse = (
            session.execute(
                select(FxRate)
                .where(
                    FxRate.base_currency == base,
                    FxRate.quote_currency == currency,
                    FxRate.as_of <= as_of,
                    visibility,
                )
                .order_by(FxRate.as_of.desc(), FxRate.retrieved_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if inverse is not None and dec(inverse.rate) > 0:
            rates[currency] = QuotePoint(
                price=Decimal(1) / dec(inverse.rate),
                as_of=inverse.as_of,
                source=inverse.source,
                quality=inverse.quality,
            )
    return rates


def _valuation_for(
    session: Session,
    account: RealAccount,
    movements: Sequence[LedgerMovement],
    instruments: Dict[int, InstrumentInfo],
    as_of: date,
) -> Tuple[ReplayResult, Any]:
    result = replay(
        base_currency=account.base_currency,
        cost_method=account.cost_method,
        instruments=instruments,
        movements=movements,
        allow_negative_cash=account.allow_negative_cash,
        allow_short=account.allow_short,
        collect_errors=True,
    )
    positions = [book for book in result.positions.values() if book.quantity > 0]
    quotes = latest_quotes(
        session, [book.instrument.id for book in positions], as_of, account.user_id
    )
    currencies = {account.base_currency}
    currencies.update(result.cash.keys())
    currencies.update(book.instrument.currency for book in positions)
    rates = fx_rates_to(
        session, account.base_currency, currencies, as_of, account.user_id
    )
    valuation = value_portfolio(
        result,
        as_of=as_of,
        quotes=quotes,
        fx_rates=rates,
        warnings=result.warnings,
    )
    return result, valuation


def account_summary(
    session: Session,
    account: RealAccount,
    *,
    as_of: Optional[date] = None,
    include_twr: bool = True,
    max_twr_movements: int = 600,
) -> Dict[str, Any]:
    moment = as_of or utc_today()
    movements = [
        movement for movement in ledger_movements(session, account.id) if movement.date <= moment
    ]
    instruments = instrument_map(
        session, {movement.instrument_id for movement in movements if movement.instrument_id}
    )
    result, valuation = _valuation_for(session, account, movements, instruments, moment)
    flows = result.external_flows
    final_value = valuation.total_value_base
    irr = xirr(build_flows(result, final_value=final_value, as_of=moment))
    twr_value: Optional[Decimal] = None
    twr_reason = ""
    if not include_twr:
        twr_reason = "no solicitado"
    elif final_value is None:
        twr_reason = "faltan cotizaciones o tipos de cambio para valorar la cartera"
    elif len(flows) < 1:
        twr_reason = "no hay aportes ni retiros registrados"
    elif len(movements) > max_twr_movements:
        twr_reason = "demasiados movimientos para calcular TWR diario en esta petición"
    else:

        def value_on(day: date) -> Optional[Decimal]:
            subset = [movement for movement in movements if movement.date <= day]
            replay_result = replay(
                base_currency=account.base_currency,
                cost_method=account.cost_method,
                instruments=instruments,
                movements=subset,
                allow_negative_cash=account.allow_negative_cash,
                allow_short=account.allow_short,
                collect_errors=True,
            )
            open_books = [book for book in replay_result.positions.values() if book.quantity > 0]
            quotes = latest_quotes(
                session,
                [book.instrument.id for book in open_books],
                day,
                account.user_id,
            )
            currencies = {account.base_currency}
            currencies.update(replay_result.cash.keys())
            currencies.update(book.instrument.currency for book in open_books)
            rates = fx_rates_to(
                session, account.base_currency, currencies, day, account.user_id
            )
            partial = value_portfolio(
                replay_result, as_of=day, quotes=quotes, fx_rates=rates
            )
            return partial.total_value_base

        twr_value = twr(flows, value_on, as_of=moment)
        if twr_value is None:
            twr_reason = "el histórico de precios o divisas no cubre todas las fechas de aportes"

    payload = valuation.as_dict()
    payload.update(
        {
            "account": {
                "id": account.id,
                "name": account.name,
                "broker_name": account.broker_name,
                "broker_country": account.broker_country,
                "account_type": account.account_type,
                "base_currency": account.base_currency,
                "cost_method": account.cost_method,
                "status": account.status,
            },
            "movements": len(movements),
            "xirr_pct": (
                None
                if irr is None
                else str((irr * 100).quantize(Decimal("0.01")))
            ),
            "xirr_available": irr is not None,
            "twr_pct": (
                None
                if twr_value is None
                else str((twr_value * 100).quantize(Decimal("0.01")))
            ),
            "twr_available": twr_value is not None,
            "twr_reason": twr_reason,
            "data_errors": result.errors,
        }
    )
    return payload


def overview(
    session: Session,
    user_id: int,
    *,
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    """Consolidado por moneda base, sin sumar monedas distintas a ciegas."""

    moment = as_of or utc_today()
    accounts = (
        session.execute(
            select(RealAccount)
            .where(RealAccount.user_id == user_id, RealAccount.status != "archived")
            .order_by(RealAccount.created_at, RealAccount.id)
        )
        .scalars()
        .all()
    )
    groups: Dict[str, Dict[str, Any]] = {}
    items: List[Dict[str, Any]] = []
    for account in accounts:
        summary = account_summary(session, account, as_of=moment, include_twr=False)
        items.append(
            {
                "id": account.id,
                "name": account.name,
                "broker_name": account.broker_name,
                "broker_country": account.broker_country,
                "account_type": account.account_type,
                "base_currency": account.base_currency,
                "cost_method": account.cost_method,
                "status": account.status,
                "total_value_base": summary["total_value_base"],
                "net_contributions_base": summary["net_contributions_base"],
                "net_gain_base": summary["net_gain_base"],
                "net_return_pct": summary["net_return_pct"],
                "xirr_pct": summary["xirr_pct"],
                "realized_base": summary["realized_base"],
                "unrealized_base": summary["unrealized_base"],
                "dividends_base": summary["dividends_base"],
                "complete": summary["complete"],
                "positions": len(summary["positions"]),
            }
        )
        group = groups.setdefault(
            account.base_currency,
            {
                "currency": account.base_currency,
                "accounts": 0,
                "market_value": ZERO,
                "cash": ZERO,
                "total_value": ZERO,
                "net_contributions": ZERO,
                "net_gain": ZERO,
                "realized": ZERO,
                "unrealized": ZERO,
                "dividends": ZERO,
                "other_fees": ZERO,
                "other_taxes": ZERO,
                "complete": True,
                "flows": [],
                "final_value": ZERO,
                "by_market": defaultdict(lambda: ZERO),
                "by_country": defaultdict(lambda: ZERO),
                "by_type": defaultdict(lambda: ZERO),
                "by_currency": defaultdict(lambda: ZERO),
            },
        )
        group["accounts"] += 1
        group["complete"] = group["complete"] and summary["complete"]
        group["market_value"] += dec(summary["market_value_base"])
        group["cash"] += dec(summary["cash_base"])
        group["net_contributions"] += dec(summary["net_contributions_base"])
        group["realized"] += dec(summary["realized_base"])
        group["unrealized"] += dec(summary["unrealized_base"])
        group["dividends"] += dec(summary["dividends_base"])
        group["other_fees"] += dec(summary["other_fees_base"])
        group["other_taxes"] += dec(summary["other_taxes_base"])
        if summary["total_value_base"] is not None:
            group["total_value"] += dec(summary["total_value_base"])
            group["final_value"] += dec(summary["total_value_base"])
        if summary["net_gain_base"] is not None:
            group["net_gain"] += dec(summary["net_gain_base"])
        for position in summary["positions"]:
            value = dec(position["market_value_base"])
            group["by_market"][position["market"] or "—"] += value
            group["by_country"][position["country_code"] or "—"] += value
            group["by_type"][position["instrument_type"] or "—"] += value
            group["by_currency"][position["currency"]] += value
        # Flujos por cuenta en su moneda base; solo se consolidan dentro del grupo.
        raw = [
            movement
            for movement in ledger_movements(session, account.id)
            if movement.date <= moment
        ]
        instruments = instrument_map(
            session, {m.instrument_id for m in raw if m.instrument_id}
        )
        replay_result = replay(
            base_currency=account.base_currency,
            cost_method=account.cost_method,
            instruments=instruments,
            movements=raw,
            allow_negative_cash=account.allow_negative_cash,
            allow_short=account.allow_short,
            collect_errors=True,
        )
        group["flows"].extend(replay_result.external_flows)

    rendered_groups = []
    for currency, group in sorted(groups.items()):
        total_value = group["total_value"] if group["complete"] else None
        net_gain = total_value - group["net_contributions"] if total_value is not None else None
        rate = xirr(
            [(day, -flow) for day, flow in group["flows"]]
            + ([(moment, total_value)] if total_value is not None else [])
        )
        rendered_groups.append(
            {
                "currency": currency,
                "accounts": group["accounts"],
                "market_value": str(money(group["market_value"])),
                "cash": str(money(group["cash"])),
                "total_value": None if total_value is None else str(money(total_value)),
                "net_contributions": str(money(group["net_contributions"])),
                "net_gain": None if net_gain is None else str(money(net_gain)),
                "net_return_pct": (
                    None
                    if net_gain is None or group["net_contributions"] <= 0
                    else str(
                        (net_gain / group["net_contributions"] * 100).quantize(
                            Decimal("0.01")
                        )
                    )
                ),
                "realized": str(money(group["realized"])),
                "unrealized": str(money(group["unrealized"])),
                "dividends": str(money(group["dividends"])),
                "other_fees": str(money(group["other_fees"])),
                "other_taxes": str(money(group["other_taxes"])),
                "xirr_pct": None if rate is None else str((rate * 100).quantize(Decimal("0.01"))),
                "complete": group["complete"],
                "by_market": {
                    key: str(money(value)) for key, value in sorted(group["by_market"].items())
                },
                "by_country": {
                    key: str(money(value))
                    for key, value in sorted(group["by_country"].items())
                },
                "by_type": {
                    key: str(money(value)) for key, value in sorted(group["by_type"].items())
                },
                "by_currency": {
                    key: str(money(value))
                    for key, value in sorted(group["by_currency"].items())
                },
            }
        )
    return {
        "as_of": moment.isoformat(),
        "accounts": items,
        "groups": rendered_groups,
        "currencies": [group["currency"] for group in rendered_groups],
        "note": (
            "Los totales se agrupan por moneda base. No se suman monedas distintas "
            "sin un tipo de cambio explícito."
        ),
    }
