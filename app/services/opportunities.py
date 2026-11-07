"""Estudios de oportunidad deterministas (Fase 7).

Lo que NO es: no es una recomendación, no predice el futuro y no fuerza
oportunidades. Con datos insuficientes el instrumento no aparece puntuado;
queda en la lista de motivos y el listado lo declara.

Lo que sí es: un barrido cuantitativo reproducible sobre los datos con
procedencia ya almacenados (fundamentales anuales reportados y cierres
diarios), con bandas explícitas y sin interacciones no documentadas.

Bandas por señal (todas binarias 0/1 salvo margen, escala continua):

- margen neto ≥ 10 % (decil continuo 0–1 según 0–30 %)
- crecimiento de ingresos ≥ 5 % anual reportado
- beneficio neto positivo en el periodo actual y el anterior
- tendencia técnica (SMA20 > SMA50 y precio > SMA200 cuando está disponible)
- retroceso máximo acotado (|DD| < 25 %) dentro del historial analizado

La puntuación 0–100 es la media ponderada transparente de estas señales, con
el horizonte sugerido por la fuerza de las señales, no como promesa de plazo:
corto si el dominio es de precio (momentum/tendencia), largo si el dominio es
fundamental, medio cuando se compensan. Marcado como `kind: "study"`.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models import FundamentalFact, Instrument, Quote
from app.services.technical import PricePoint, analyze


HORIZON_BY_SIGNAL = {
    "fundamental": "long",
    "technical": "short",
}


def _pct(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class OpportunityError(ValueError):
    pass


def opportunity_error():
    return OpportunityError


class OpportunityEngine:
    """Barrido determinista sobre instrumentos con datos suficientes."""

    def __init__(self) -> None:
        self.min_quotes = 23  # price, SMT 20 + margen

    def scan(self, session: Session, *, limit_instruments: int = 200) -> Dict[str, Any]:
        instruments = (
            session.execute(
                select(Instrument)
                .where(Instrument.status == "active")
                .order_by(Instrument.id)
                .limit(limit_instruments)
            )
            .scalars()
            .all()
        )
        quote_counts = dict(
            session.execute(
                select(Quote.instrument_id, func.count())
                .where(
                    Quote.instrument_id.in_([i.id for i in instruments] or [0]),
                    Quote.user_id.is_(None),
                    Quote.adjusted.is_(False),
                )
                .group_by(Quote.instrument_id)
            ).all()
        )
        items: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        for instrument in instruments:
            quote_count = int(quote_counts.get(instrument.id, 0))
            if quote_count < self.min_quotes:
                skipped.append(self._skip(instrument, "menos de 23 cierres almacenados"))
                continue
            study = self._study(session, instrument)
            if study is None:
                factors = self._fundamentals_pair(session, instrument.id)
                if factors is None:
                    skipped.append(
                        self._skip(instrument, "menos de dos reportes anuales (fundamental)")
                    )
                else:
                    skipped.append(self._skip(instrument, "historial de precios insuficiente"))
                continue
            items.append(study)
        # Orden estable: puntuación descendente y, a igualdad, uid interno estable.
        items.sort(key=lambda item: (-item["score"], item["instrument"]["uid"]))
        if not items:
            return {
                "kind": "study",
                "note": (
                    "Sin instrumentos con datos suficientes (≥23 cierres proveedor y "
                    "≥2 reportes anuales). No se fuerza ninguna oportunidad."
                ),
                "items": [],
                "skipped": skipped[:60],
                "counts": {"items": 0, "skipped": len(skipped)},
            }
        return {
            "kind": "study",
            "note": (
                "Estudio cuantitativo reproducible sobre datos con procedencia; "
                "no es una recomendación de inversión ni una predicción."
            ),
            "items": items,
            "skipped": skipped[:60],
            "counts": {"items": len(items), "skipped": len(skipped)},
        }

    def _skip(self, instrument: Instrument, reason: str) -> Dict[str, Any]:
        return {
            "instrument_uid": instrument.uid,
            "symbol": instrument.symbol,
            "reason": reason,
        }

    # -- señales -------------------------------------------------------------

    def _fundamentals_pair(
        self, session: Session, instrument_id: int
    ) -> Optional[Tuple[FundamentalFact, FundamentalFact]]:
        facts = (
            session.execute(
                select(FundamentalFact)
                .where(
                    FundamentalFact.instrument_id == instrument_id,
                    FundamentalFact.period_type == "annual",
                )
                .order_by(FundamentalFact.fiscal_end.desc())
                .limit(2)
            )
            .scalars()
            .all()
        )
        if len(facts) < 2:
            return None
        return facts[0], facts[1]

    def _study(self, session: Session, instrument: Instrument) -> Optional[Dict[str, Any]]:
        pair = self._fundamentals_pair(session, instrument.id)
        if pair is None:
            return None
        current, previous = pair
        quotes = (
            session.execute(
                select(Quote)
                .where(
                    Quote.instrument_id == instrument.id,
                    Quote.user_id.is_(None),
                    Quote.adjusted.is_(False),
                )
                .order_by(Quote.as_of.desc())
                .limit(400)
            )
            .scalars()
            .all()
        )
        if len(quotes) < self.min_quotes:
            return None
        points = [PricePoint(q.as_of, Decimal(str(q.price))) for q in reversed(quotes)]
        technical = analyze(points).as_dict()

        signals: Dict[str, Any] = {}
        score_parts: List[Tuple[str, float]] = []

        revenue = self._dec(current.revenue)
        net_income = self._dec(current.net_income)
        revenue_prev = self._dec(previous.revenue)
        net_income_prev = self._dec(previous.net_income)

        # 1. margen neto (0–1 en escala continua 0–30 %).
        if revenue and net_income is not None:
            margin = (net_income / revenue) if revenue > 0 else None
            continuous = max(Decimal(0), min(Decimal(1), (margin or Decimal(0)) / Decimal("0.30")))
            signals["net_margin_pct"] = str(_pct((margin or Decimal(0)) * 100))
            score_parts.append(("margin", float(continuous)))

        # 2. crecimiento de ingresos reportado.
        if revenue_prev and revenue and revenue_prev > 0:
            growth = (revenue - revenue_prev) / revenue_prev
            signals["revenue_growth_pct"] = str(_pct(growth * 100))
            score_parts.append(("growth", 1.0 if growth >= Decimal("0.05") else 0.0))

        # 3. beneficio persistente.
        if net_income is not None and net_income_prev is not None:
            profitable = net_income > 0 and net_income_prev > 0
            signals["profitable_pair"] = bool(profitable)
            score_parts.append(("profits", 1.0 if profitable else 0.0))

        # 4. tendencia técnica.
        if technical.get("trend") in ("alcista", "lateral", "bajista"):
            tech_score = 1.0 if technical["trend"] == "alcista" else (0.0 if technical["trend"] == "bajista" else 0.5)
            signals["trend"] = technical["trend"]
            score_parts.append(("trend", tech_score))

        # 5. retroceso contenido.
        if technical.get("max_drawdown_pct") is not None:
            dd = abs(Decimal(technical["max_drawdown_pct"]))
            contained = dd < Decimal("25")
            signals["max_drawdown_pct"] = technical["max_drawdown_pct"]
            score_parts.append(("drawdown", 1.0 if contained else 0.0))
            signals["rsi"] = technical.get("rsi")

        if not score_parts:
            return None

        score = round(sum(weight for _, weight in score_parts) / len(score_parts) * 100)
        horizon = self._pick_horizon(signals)
        return {
            "instrument": {
                "uid": instrument.uid,
                "symbol": instrument.symbol,
                "name": instrument.name,
                "market": "",
                "currency": instrument.currency,
            },
            "score": score,
            "signals": signals,
            "horizon": horizon,
            "fiscal_period": current.fiscal_end.isoformat(),
            "sources": sorted({current.source, previous.source, quotes[0].source}),
            "quote_as_of": technical.get("last_day"),
            "kind": "study",
        }

    @staticmethod
    def _pick_horizon(signals: Dict[str, Any]) -> str:
        trend = signals.get("trend") == "alcista"
        profitable = signals.get("profitable_pair") is True
        growth = Decimal(signals.get("revenue_growth_pct") or "0") >= 0
        if trend and not (profitable and growth):
            return "short"
        if profitable and growth and not trend:
            return "long"
        return "medium"

    @staticmethod
    def _dec(value: Any) -> Optional[Decimal]:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except Exception:  # noqa: BLE001
            return None
