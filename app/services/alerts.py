"""Alertas declarativas sobre los datos ya almacenados (Fase 6).

Principios:

- El motor **solo** usa datos persistidos por canales verificables (cotizaciones
  con procedencia, fundamentales reportados, cartera real contabilizada). No
  consulta proveedores ni genera tráfico externo: la condición se evalúa sobre
  lo que ya hay, y si falta el dato la regla no dispara.
- Reglas por `kind`:
  - `price_above` / `price_below`: la última cotización del proveedor cruza un
    precio.
  - `target_entry` / `target_exit`: objetivo de entrada/salida definido por el
    usuario sobre el mismo precio.
  - `price_change_pct`: variación total dentro de una ventana de días.
  - `fundamentals_change`: cambio del último reporte anual frente al anterior
    (beneficio neto; si alguna falta, ingresos). Solo métricas reportadas.
  - `data_stale`: la cotización del instrumento (uno concreto o los de las
    posiciones del usuario) envejeció más que el umbral de días.
  - `concentration_risk`: el peso de una posición en la cartera real supera
    el umbral porcentual, valorado en la moneda base de cada cuenta.
- Anti-duplicación en la base: `dedupe_key` único. Un estado persistente
  (objetivo alcanzado, dato desactualizado, concentración) alerta como máximo
  una vez por semana; un evento nuevo (variación, nuevo reporte) por dato.
- Fallos de evaluación no detienen el resto de reglas y quedan registrados en
  el log del servidor, nunca como alerta inventada.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, load_settings
from app.models import (
    AlertEvent,
    AlertRule,
    FundamentalFact,
    Instrument,
    Quote,
    RealAccount,
    RealMovement,
    utcnow,
)

logger = logging.getLogger("nexo.alerts")

KINDS_REQUIRING_INSTRUMENT = frozenset({
    "price_above",
    "price_below",
    "price_change_pct",
    "target_entry",
    "target_exit",
    "fundamentals_change",
})
KINDS = frozenset(KINDS_REQUIRING_INSTRUMENT | {"data_stale", "concentration_risk"})

_KIND_META: Dict[str, Dict[str, Any]] = {
    "price_above": {
        "label": "Precio por encima de",
        "unit": "precio",
        "requires_instrument": True,
        "requires_threshold": True,
        "severity": "info",
    },
    "price_below": {
        "label": "Precio por debajo de",
        "unit": "precio",
        "requires_instrument": True,
        "requires_threshold": True,
        "severity": "info",
    },
    "target_entry": {
        "label": "Objetivo de entrada",
        "unit": "precio",
        "requires_instrument": True,
        "requires_threshold": True,
        "severity": "info",
    },
    "target_exit": {
        "label": "Objetivo de salida",
        "unit": "precio",
        "requires_instrument": True,
        "requires_threshold": True,
        "severity": "info",
    },
    "price_change_pct": {
        "label": "Variación de precio (% en ventana)",
        "unit": "porcentaje",
        "requires_instrument": True,
        "requires_threshold": True,
        "severity": "warning",
    },
    "fundamentals_change": {
        "label": "Cambio fundamental (reporte anual vs anterior)",
        "unit": "porcentaje",
        "requires_instrument": True,
        "requires_threshold": True,
        "severity": "warning",
    },
    "data_stale": {
        "label": "Cotización desactualizada",
        "unit": "días",
        "requires_instrument": False,
        "requires_threshold": False,
        "severity": "warning",
    },
    "concentration_risk": {
        "label": "Riesgo de concentración (% de la cartera real)",
        "unit": "porcentaje",
        "requires_instrument": False,
        "requires_threshold": False,
        "severity": "warning",
    },
}

DEFAULT_WINDOW_DAYS = 7


def rule_catalog() -> List[Dict[str, Any]]:
    """Catálogo de reglas disponibles para la interfaz."""
    return [
        {"kind": kind, **meta}
        for kind, meta in _KIND_META.items()
    ]


class AlertRuleError(ValueError):
    """Regla no válida; la API la traduce a 400."""


def week_bucket(moment: datetime) -> str:
    """Semana ISO de un instante, para no repetir alertas de estado permanente."""
    return f"{moment.isocalendar().year}-W{moment.isocalendar().week:02d}"


def _as_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001 — un valor no numérico no dispara nada
        return None


def _fmt(value: Optional[Decimal], places: str = "0.01") -> str:
    if value is None:
        return "—"
    return str(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))


class AlertEngine:
    """Evaluador de reglas sobre los datos persistidos."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or load_settings()

    # -- validación ------------------------------------------------------------

    def validate(
        self,
        *,
        kind: str,
        instrument: Optional[Instrument],
        threshold: Optional[Decimal],
        window_days: Optional[int],
    ) -> Dict[str, Dict[str, Any]]:
        meta = _KIND_META.get(kind)
        if meta is None:
            raise AlertRuleError(f"Regla desconocida: {kind!r}")
        if meta["requires_instrument"] and instrument is None:
            raise AlertRuleError(f"La regla {kind} exige un instrumento.")
        if meta["requires_threshold"]:
            if threshold is None or threshold <= 0:
                unit = meta["unit"]
                raise AlertRuleError(f"La regla {kind} necesita un umbral de {unit} mayor que 0.")
        config: Dict[str, Any] = {}
        if kind == "price_change_pct":
            config["window_days"] = max(
                1,
                min(365, window_days or DEFAULT_WINDOW_DAYS),
            )
        if kind == "concentration_risk":
            if threshold is None:
                config_warn = None
            else:
                config_warn = (
                    None
                    if not (Decimal("1") <= threshold <= Decimal("100"))
                    else "umbral"
                )
            if config_warn != "umbral":
                raise AlertRuleError("El umbral de concentración se expresa en % entre 1 y 100.")
        if kind == "fundamentals_change" and threshold is not None and not (
            Decimal("0.01") <= threshold <= Decimal("1000")
        ):
            raise AlertRuleError("El umbral de cambio fundamental se expresa en % (0.01–1000).")
        if kind == "price_change_pct" and threshold is not None and not (
            Decimal("0.01") <= threshold <= Decimal("100")
        ):
            raise AlertRuleError("El umbral de variación se expresa en % entre 0.01 y 100.")
        return config

    # -- reglas ----------------------------------------------------------------

    def rule_view(self, rule: AlertRule, instrument: Optional[Instrument] = None) -> Dict[str, Any]:
        return {
            "id": rule.id,
            "kind": rule.kind,
            "label": _KIND_META.get(rule.kind, {}).get("label", rule.kind),
            "instrument_uid": instrument.uid if instrument else None,
            "instrument_symbol": instrument.symbol if instrument else None,
            "threshold": None if rule.threshold is None else str(rule.threshold),
            "config": dict(rule.config or {}),
            "active": rule.active,
            "created_at": rule.created_at.isoformat(),
        }

    # -- evaluación ------------------------------------------------------------

    def evaluate_all(self, session: Session, *, now: Optional[datetime] = None) -> List[AlertEvent]:
        moment = now or utcnow()
        rules = (
            session.execute(select(AlertRule).where(AlertRule.active.is_(True)))
            .scalars()
            .all()
        )
        if not rules:
            return []
        quotes: Dict[int, List[Quote]] = {}
        fresh: List[AlertEvent] = []
        for rule in rules:
            handler = getattr(self, f"_eval_{rule.kind}", None)
            if handler is None:
                continue
            try:
                fresh.extend(handler(session, rule, moment, quotes))
            except Exception as exc:  # noqa: BLE001 — una regla rota no para las demás
                logger.warning("Regla %s (%s) falló al evaluarse: %s", rule.id, rule.kind, exc)
        return fresh

    # -- cotizaciones -----------------------------------------------------------

    def _quotes_for(
        self,
        session: Session,
        instrument_id: int,
        cache: Dict[int, List[Quote]],
    ) -> List[Quote]:
        if instrument_id not in cache:
            rows = (
                session.execute(
                    select(Quote)
                    .where(
                        Quote.instrument_id == instrument_id,
                        Quote.user_id.is_(None),
                        Quote.adjusted.is_(False),
                    )
                    .order_by(Quote.as_of.desc(), Quote.id.desc())
                    .limit(900)
                )
                .scalars()
                .all()
            )
            cache[instrument_id] = rows
        return cache[instrument_id]

    @staticmethod
    def _latest(sorted_quotes: List[Quote]) -> Optional[Quote]:
        return sorted_quotes[0] if sorted_quotes else None

    # -- evaluación por regla ----------------------------------------------------

    def _eval_price_above(
        self, session: Session, rule: AlertRule, now: datetime, quotes: Dict[int, List[Quote]]
    ) -> List[AlertEvent]:
        return self._eval_price_comparison(session, rule, now, quotes, direction="above")

    def _eval_price_below(
        self, session: Session, rule: AlertRule, now: datetime, quotes: Dict[int, List[Quote]]
    ) -> List[AlertEvent]:
        return self._eval_price_comparison(session, rule, now, quotes, direction="below")

    def _eval_target_exit(
        self, session: Session, rule: AlertRule, now: datetime, quotes: Dict[int, List[Quote]]
    ) -> List[AlertEvent]:
        return self._eval_price_comparison(session, rule, now, quotes, direction="above", target=True)

    def _eval_target_entry(
        self, session: Session, rule: AlertRule, now: datetime, quotes: Dict[int, List[Quote]]
    ) -> List[AlertEvent]:
        return self._eval_price_comparison(session, rule, now, quotes, direction="below", target=True)

    def _eval_price_comparison(
        self,
        session: Session,
        rule: AlertRule,
        now: datetime,
        quotes: Dict[int, List[Quote]],
        *,
        direction: str,
        target: bool = False,
    ) -> List[AlertEvent]:
        if rule.instrument_id is None:
            return []
        history = self._quotes_for(session, rule.instrument_id, quotes)
        latest = self._latest(history)
        threshold = _as_decimal(rule.threshold)
        price = _as_decimal(latest.price) if latest else None
        if threshold is None or price is None or latest is None:
            return []
        hit = price >= threshold if direction == "above" else price <= threshold
        if not hit:
            return []
        label = "Objetivo de salida alcanzado" if target and direction == "above" else (
            "Objetivo de entrada alcanzado" if target else
            ("Precio por encima del objetivo" if direction == "above" else "Precio por debajo del objetivo")
        )
        return self._fire(
            session,
            rule,
            instrument_id=rule.instrument_id,
            kind=rule.kind,
            severity=_KIND_META[rule.kind]["severity"],
            title=f"{label}: {_fmt(price)} vs {_fmt(threshold)}",
            detail={
                "price": str(price),
                "threshold": str(threshold),
                "as_of": latest.as_of.isoformat(),
                "source": latest.source,
                "quality": latest.quality,
                "currency": latest.currency,
                "note": "Precio de cierre con fuente y calidad declaradas; no es tiempo real.",
            },
            dedupe=f"rule:{rule.id}:{latest.as_of}",
        )

    def _eval_price_change_pct(
        self, session: Session, rule: AlertRule, now: datetime, quotes: Dict[int, List[Quote]]
    ) -> List[AlertEvent]:
        if rule.instrument_id is None:
            return []
        history = self._quotes_for(session, rule.instrument_id, quotes)
        latest = self._latest(history)
        if latest is None:
            return []
        threshold = _as_decimal(rule.threshold) if rule.threshold is not None else None
        if threshold is None:
            return []
        window = int((rule.config or {}).get("window_days", DEFAULT_WINDOW_DAYS))
        cutoff = latest.as_of - timedelta(days=window)
        prior = [q for q in history if q.id != latest.id and cutoff <= q.as_of < latest.as_of]
        if not prior:
            return []
        first = prior[-1]  # la lista viene descendente: prior[-1] es la más antigua de la ventana
        start = _as_decimal(first.price)
        end = _as_decimal(latest.price)
        if start is None or end is None or start == 0:
            return []
        change_pct = (end - start) / start * Decimal(100)
        if abs(change_pct) < threshold:
            return []
        return self._fire(
            session,
            rule,
            instrument_id=rule.instrument_id,
            kind=rule.kind,
            severity="warning",
            title=(
                f"Variación de {_fmt(change_pct)} % en {window} días "
                f"({first.as_of:%Y-%m-%d} → {latest.as_of:%Y-%m-%d})"
            ),
            detail={
                "change_pct": str(change_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "start_price": _fmt(start, "0.0001"),
                "start_as_of": first.as_of.isoformat(),
                "end_price": _fmt(end, "0.0001"),
                "end_as_of": latest.as_of.isoformat(),
                "window_days": window,
                "source": latest.source,
                "quality": latest.quality,
            },
            dedupe=f"rule:{rule.id}:{latest.as_of}",
        )

    def _eval_fundamentals_change(
        self, session: Session, rule: AlertRule, now: datetime, quotes: Dict[int, List[Quote]]
    ) -> List[AlertEvent]:
        if rule.instrument_id is None:
            return []
        threshold = _as_decimal(rule.threshold) if rule.threshold is not None else None
        if threshold is None:
            return []
        facts = (
            session.execute(
                select(FundamentalFact)
                .where(
                    FundamentalFact.instrument_id == rule.instrument_id,
                    FundamentalFact.period_type == "annual",
                )
                .order_by(FundamentalFact.fiscal_end.desc())
                .limit(2)
            )
            .scalars()
            .all()
        )
        if len(facts) < 2:
            return []
        current, previous = facts[0], facts[1]
        metric = "net_income"
        current_value = _as_decimal(getattr(current, metric))
        previous_value = _as_decimal(getattr(previous, metric))
        if current_value is None or previous_value is None or previous_value == 0:
            metric = "revenue"
            current_value = _as_decimal(getattr(current, metric))
            previous_value = _as_decimal(getattr(previous, metric))
        if current_value is None or previous_value is None or previous_value == 0:
            return []
        change_pct = (current_value - previous_value) / abs(previous_value) * Decimal(100)
        if abs(change_pct) < threshold:
            return []
        sources = sorted({current.source, previous.source})
        return self._fire(
            session,
            rule,
            instrument_id=rule.instrument_id,
            kind=rule.kind,
            severity="warning",
            title=(
                f"{'Beneficio' if metric == 'net_income' else 'Ingresos'} reportados cambian "
                f"{_fmt(change_pct)} % ({previous.fiscal_end:%Y-%m-%d} → {current.fiscal_end:%Y-%m-%d})"
            ),
            detail={
                "metric": metric,
                "change_pct": str(change_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "previous_period": previous.fiscal_end.isoformat(),
                "previous_value": str(previous_value),
                "current_period": current.fiscal_end.isoformat(),
                "current_value": str(current_value),
                "sources": sources,
                "period_type": "annual",
                "note": "Métrica reportada por el emisor; no estimada.",
            },
            dedupe=f"rule:{rule.id}:{current.fiscal_end}",
        )

    def _eval_data_stale(
        self, session: Session, rule: AlertRule, now: datetime, quotes: Dict[int, List[Quote]]
    ) -> List[AlertEvent]:
        threshold_days = _as_decimal(rule.threshold)
        if threshold_days is None:
            threshold_days = Decimal(max(1, self.settings.data_stale_after_days))
        instrument_ids: List[int]
        if rule.instrument_id is not None:
            instrument_ids = [rule.instrument_id]
        else:
            instrument_ids = (
                session.execute(
                    select(RealMovement.instrument_id)
                    .join(RealAccount, RealMovement.account_id == RealAccount.id)
                    .where(
                        RealAccount.user_id == rule.user_id,
                        RealMovement.instrument_id.isnot(None),
                        RealMovement.validation_status == "confirmed",
                    )
                    .distinct()
                )
                .scalars()
                .all()
            )
        today = now.astimezone(timezone.utc).date()
        week = week_bucket(now)
        fired: List[AlertEvent] = []
        for instrument_id in instrument_ids:
            history = self._quotes_for(session, instrument_id, quotes)
            latest = self._latest(history)
            if latest is None:
                continue
            age_days = Decimal((today - latest.as_of).days)
            if age_days <= threshold_days:
                continue
            fired.extend(
                self._fire(
                    session,
                    rule,
                    instrument_id=instrument_id,
                    kind=rule.kind,
                    severity="warning",
                    title=(
                        f"Cotización desactualizada: {int(age_days)} días sin datos "
                        f"(última {latest.as_of:%Y-%m-%d}, fuente {latest.source})"
                    ),
                    detail={
                        "age_days": int(age_days),
                        "threshold_days": int(threshold_days),
                        "last_as_of": latest.as_of.isoformat(),
                        "source": latest.source,
                        "quality": latest.quality,
                    },
                    dedupe=f"rule:{rule.id}:stale:{instrument_id}:{week}",
                )
            )
        return fired

    def _eval_concentration_risk(
        self, session: Session, rule: AlertRule, now: datetime, quotes: Dict[int, List[Quote]]
    ) -> List[AlertEvent]:
        from app.services.real_portfolio import account_summary  # import tardío: evita ciclos

        threshold = _as_decimal(rule.threshold)
        if threshold is None:
            threshold = Decimal("40")
        accounts = (
            session.execute(
                select(RealAccount)
                .where(RealAccount.user_id == rule.user_id, RealAccount.status != "archived")
                .order_by(RealAccount.id)
            )
            .scalars()
            .all()
        )
        week = week_bucket(now)
        fired: List[AlertEvent] = []
        for account in accounts:
            if rule.config.get("account_id") is not None and int(rule.config["account_id"]) != account.id:
                continue
            summary = account_summary(session, account)
            total = _as_decimal(summary.get("total_value_base"))
            if total is None or total <= 0:
                # Sin valoración completa no hay peso medible: no se dispara.
                continue
            for position in summary.get("positions") or []:
                value = _as_decimal(position.get("market_value_base"))
                if value is None:
                    continue
                share = value / total * Decimal(100)
                if share < threshold:
                    continue
                fired.extend(
                    self._fire(
                        session,
                        rule,
                        instrument_id=None,
                        kind=rule.kind,
                        severity="warning",
                        title=(
                            f"Concentración en {position.get('symbol') or 'posición'} "
                            f"{_fmt(share)} % de {account.name}"
                        ),
                        detail={
                            "account_id": account.id,
                            "account_name": account.name,
                            "base_currency": account.base_currency,
                            "instrument_uid": position.get("instrument_uid"),
                            "symbol": position.get("symbol"),
                            "weight_pct": str(share.quantize(Decimal("0.10"), rounding=ROUND_HALF_UP)),
                            "threshold_pct": str(threshold),
                            "market_value_base": str(value),
                            "as_of": summary.get("as_of"),
                            "note": "Peso sobre la valoración total en la moneda base de la cuenta.",
                        },
                        dedupe=f"rule:{rule.id}:conc:{account.id}:{position.get('instrument_uid')}:{week}",
                    )
                )
        return fired

    # -- persistencia ----------------------------------------------------------

    def _fire(
        self,
        session: Session,
        rule: AlertRule,
        *,
        instrument_id: Optional[int],
        kind: str,
        severity: str,
        title: str,
        detail: Dict[str, Any],
        dedupe: str,
    ) -> List[AlertEvent]:
        """Guarda el evento si su `dedupe_key` no existe ya (restricción única en la base).

        Si otra tarea insertó exactamente la misma alerta entre la comprobación y
        el flush, la restricción única hace fallar el flush; se trata como ceniza
        repetida y se devuelve la lista vacía en lugar de una segunda fila.
        """
        key = dedupe[:191]
        exists = session.execute(
            select(AlertEvent.id).where(AlertEvent.dedupe_key == key).limit(1)
        ).scalar_one_or_none()
        if exists is not None:
            return []
        event = AlertEvent(
            user_id=rule.user_id,
            rule_id=rule.id,
            instrument_id=instrument_id,
            kind=kind,
            severity=severity,
            title=title[:160],
            detail=detail,
            dedupe_key=key,
        )
        session.add(event)
        session.flush()
        return [event]


def evaluate_now(
    session: Session,
    settings: Optional[Settings] = None,
    *,
    now: Optional[datetime] = None,
) -> List[AlertEvent]:
    """Atajo API: evalúa todas las reglas activas y devuelve los eventos nuevos."""
    engine = AlertEngine(settings)
    return engine.evaluate_all(session, now=now)
