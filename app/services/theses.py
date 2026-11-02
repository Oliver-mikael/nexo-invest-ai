"""Tesis de inversión versionadas con seguimiento automático (Fase 7).

Reglas del servicio:

- La tesis abierta es una por (usuario, instrumento); se revisa **añadiendo
  versiones** y sucesos, nunca reescribiendo la historia.
- El motor (`evaluate`) compara las condiciones estructuradas de invalidación
  y los objetivos con la última cotización con procedencia, y compara los
  fundamentales anuales nuevos contra los ya conocidos. Solo registra indicios
  y sugiere `under_review`: pasar a `validated`, `invalidated` o `closed` es
  siempre una decisión del usuario.
- Todo elemento declarado como texto libre (hipótesis, condiciones) se guarda
  tal cual; el motor nunca parsea ni interpreta prosa para decidir.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    FundamentalFact,
    Instrument,
    InvestmentThesis,
    Quote,
    ThesisEvent,
    ThesisVersion,
    utcnow,
)

HORIZONS = ("short", "medium", "long")
UNCERTAINTY = ("low", "medium", "high")
STATUSES = ("open", "under_review", "validated", "invalidated", "closed")
EVENT_KINDS = (
    "fundamental_change",
    "price_signal",
    "thesis_revision",
    "decision",
    "risk_new",
    "invalidated",
    "validated",
)
FUNDAMENTAL_ALERT_PCT = Decimal("20")


class ThesisError(ValueError):
    """Entrada no válida; la API la traduce a 400."""


def _price(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        raise ThesisError("El precio objetivo debe ser un número.")


def _validate_conditions(conditions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Solo condiciones estructuradas evaluables: price_above/price_below + price."""
    clean: List[Dict[str, Any]] = []
    for item in conditions or []:
        if not isinstance(item, dict):
            raise ThesisError("Cada condición de invalidación debe ser un objeto.")
        kind = item.get("type")
        if kind in ("price_above", "price_below"):
            threshold = _price(item.get("price"))
            if threshold is None or threshold <= 0:
                raise ThesisError("La condición de precio exige un precio mayor que 0.")
            clean.append({"type": kind, "price": str(threshold), "note": str(item.get("note") or "")})
        elif kind == "text":
            note = str(item.get("text") or item.get("note") or "").strip()
            if not note:
                raise ThesisError("Una condición declarada como texto exige su contenido.")
            clean.append({"type": "text", "text": note[:400]})
        else:
            raise ThesisError(
                "Tipo de condición no válido; usa price_above, price_below o text."
            )
    return clean


class ThesisService:
    """CRUD + evaluación de tesis versionadas."""

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _basket_quote(session: Session, instrument_id: int) -> Optional[Quote]:
        return session.execute(
            select(Quote)
            .where(
                Quote.instrument_id == instrument_id,
                Quote.user_id.is_(None),
                Quote.adjusted.is_(False),
            )
            .order_by(Quote.as_of.desc(), Quote.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    @staticmethod
    def instrument_view(instrument: Optional[Instrument]) -> Dict[str, Any]:
        if instrument is None:
            return {}
        return {
            "uid": instrument.uid,
            "symbol": instrument.symbol,
            "name": instrument.name,
            "market": instrument.market_id,
            "currency": instrument.currency,
        }

    @staticmethod
    def version_view(version: ThesisVersion) -> Dict[str, Any]:
        return {
            "number": version.number,
            "hypothesis": version.hypothesis,
            "invalidation_conditions": list(version.invalidation_conditions or []),
            "uncertainty_level": version.uncertainty_level,
            "note": version.note,
            "created_at": version.created_at.isoformat(),
        }

    @staticmethod
    def event_view(event: ThesisEvent) -> Dict[str, Any]:
        return {
            "id": event.id,
            "kind": event.kind,
            "payload": dict(event.payload or {}),
            "detected_by": event.detected_by,
            "created_at": event.created_at.isoformat(),
        }

    def thesis_view(
        self,
        session: Session,
        thesis: InvestmentThesis,
        instrument: Optional[Instrument] = None,
        *,
        with_detail: bool = False,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": thesis.id,
            "instrument": self.instrument_view(instrument),
            "instrument_uid": instrument.uid if instrument else None,
            "horizon": thesis.horizon,
            "title": thesis.title,
            "hypothesis": thesis.hypothesis,
            "invalidation_conditions": list(thesis.invalidation_conditions or []),
            "uncertainty_level": thesis.uncertainty_level,
            "missing_info": list(thesis.missing_info or []),
            "status": thesis.status,
            "entry_target": None if thesis.entry_target is None else str(thesis.entry_target),
            "exit_target": None if thesis.exit_target is None else str(thesis.exit_target),
            "version_count": thesis.version_count,
            "created_at": thesis.created_at.isoformat(),
            "updated_at": thesis.updated_at.isoformat(),
        }
        if thesis.status == "closed" and thesis.closed_at:
            payload["closed_at"] = thesis.closed_at.isoformat()
        if with_detail:
            versions = (
                session.execute(
                    select(ThesisVersion)
                    .where(ThesisVersion.thesis_id == thesis.id)
                    .order_by(ThesisVersion.number.desc())
                )
                .scalars()
                .all()
            )
            events = (
                session.execute(
                    select(ThesisEvent)
                    .where(ThesisEvent.thesis_id == thesis.id)
                    .order_by(ThesisEvent.created_at.desc(), ThesisEvent.id.desc())
                    .limit(100)
                )
                .scalars()
                .all()
            )
            payload["versions"] = [self.version_view(version) for version in versions]
            payload["events"] = [self.event_view(event) for event in events]
        return payload

    # -- operaciones ----------------------------------------------------------

    def create(
        self,
        session: Session,
        user_id: int,
        instrument: Instrument,
        *,
        horizon: str,
        title: str,
        hypothesis: str,
        invalidation_conditions: List[Dict[str, Any]],
        uncertainty_level: str = "medium",
        missing_info: Optional[List[str]] = None,
        entry_target: Any = None,
        exit_target: Any = None,
    ) -> InvestmentThesis:
        if horizon not in HORIZONS:
            raise ThesisError("El horizonte debe ser short, medium o long.")
        if uncertainty_level not in UNCERTAINTY:
            raise ThesisError("El nivel de incertidumbre debe ser low, medium o high.")
        if len(title.strip()) < 3:
            raise ThesisError("El título debe describir la tesis (mínimo 3 caracteres).")
        if len(hypothesis.strip()) < 10:
            raise ThesisError("La hipótesis necesita al menos 10 caracteres que la expliquen.")
        open_existing = session.execute(
            select(InvestmentThesis).where(
                InvestmentThesis.user_id == user_id,
                InvestmentThesis.instrument_id == instrument.id,
                InvestmentThesis.status.in_(["open", "under_review"]),
            ).limit(1)
        ).scalar_one_or_none()
        if open_existing is not None:
            raise ThesisError(
                "Ya existe una tesis abierta para este instrumento; revísala o ciérrala."
            )
        conditions = _validate_conditions(invalidation_conditions)
        thesis = InvestmentThesis(
            user_id=user_id,
            instrument_id=instrument.id,
            horizon=horizon,
            title=title.strip()[:160],
            hypothesis=hypothesis.strip(),
            invalidation_conditions=conditions,
            uncertainty_level=uncertainty_level,
            missing_info=[str(item)[:200] for item in (missing_info or [])][:20],
            status="open",
            entry_target=_price(entry_target),
            exit_target=_price(exit_target),
            version_count=1,
        )
        session.add(thesis)
        session.flush()
        session.add(
            ThesisVersion(
                thesis_id=thesis.id,
                number=1,
                hypothesis=thesis.hypothesis,
                invalidation_conditions=conditions,
                uncertainty_level=thesis.uncertainty_level,
                note="Versión inicial (hipótesis declarada al crear).",
            )
        )
        return thesis

    def add_version(
        self,
        session: Session,
        thesis: InvestmentThesis,
        *,
        hypothesis: Optional[str] = None,
        invalidation_conditions: Optional[List[Dict[str, Any]]] = None,
        uncertainty_level: Optional[str] = None,
        note: str = "",
    ) -> ThesisVersion:
        if uncertainty_level is not None and uncertainty_level not in UNCERTAINTY:
            raise ThesisError("Nivel de incertidumbre no válido.")
        new_hypothesis = (hypothesis or thesis.hypothesis).strip()
        if len(new_hypothesis) < 10:
            raise ThesisError("La hipótesis necesita al menos 10 caracteres.")
        conditions = _validate_conditions(
            invalidation_conditions if invalidation_conditions is not None
            else thesis.invalidation_conditions
        )
        level = uncertainty_level or thesis.uncertainty_level
        previous_hypothesis = thesis.hypothesis
        changed = (
            new_hypothesis != thesis.hypothesis
            or conditions != (thesis.invalidation_conditions or [])
            or level != thesis.uncertainty_level
        )
        if not changed and note.strip() == "":
            raise ThesisError("Una versión nueva exige algún cambio o una nota que lo explique.")
        version = ThesisVersion(
            thesis_id=thesis.id,
            number=thesis.version_count + 1,
            hypothesis=new_hypothesis,
            invalidation_conditions=conditions,
            uncertainty_level=level,
            note=note.strip(),
        )
        session.add(version)
        thesis.hypothesis = new_hypothesis
        thesis.invalidation_conditions = conditions
        thesis.uncertainty_level = level
        if hypothesis is not None:
            thesis.version_count += 1
        thesis.status = "under_review" if thesis.status == "open" else thesis.status
        session.add(
            ThesisEvent(
                thesis_id=thesis.id,
                kind="thesis_revision",
                payload={
                    "version": version.number,
                    "note": version.note,
                    "changed_hypothesis": new_hypothesis != previous_hypothesis,
                },
                detected_by="user",
            )
        )
        session.flush()  # completa created_at e id antes de serializar
        return version

    def add_event(
        self,
        session: Session,
        thesis: InvestmentThesis,
        *,
        kind: str,
        payload: Dict[str, Any],
        detected_by: str = "user",
    ) -> ThesisEvent:
        if kind not in EVENT_KINDS:
            raise ThesisError(f"Tipo de suceso no válido; usa uno de {', '.join(EVENT_KINDS)}.")
        if kind in ("invalidated", "validated"):
            raise ThesisError("Los estados validado/invalidado solo cambian con PATCH de estado.")
        event = ThesisEvent(
            thesis_id=thesis.id,
            kind=kind,
            payload=dict(payload or {}),
            detected_by=detected_by,
        )
        session.add(event)
        session.flush()
        return event

    def set_status(
        self,
        session: Session,
        thesis: InvestmentThesis,
        status: str,
        *,
        note: str = "",
    ) -> ThesisEvent:
        if status not in STATUSES:
            raise ThesisError(f"Estado no válido; usa uno de {', '.join(STATUSES)}.")
        allowed: Dict[str, tuple] = {
            "open": ("under_review", "closed"),
            "under_review": ("open", "validated", "invalidated", "closed"),
            "validated": ("closed", "under_review"),
            "invalidated": ("closed", "under_review"),
            "closed": (),
        }
        if status not in allowed.get(thesis.status, ()):  # type: ignore[arg-type]
            raise ThesisError(
                f"Transición no permitida: de {thesis.status} no se pasa a {status}."
            )
        previous = thesis.status
        thesis.status = status
        if status == "closed":
            thesis.closed_at = utcnow()
        if status in ("validated", "invalidated") and previous != status:
            event = ThesisEvent(
                thesis_id=thesis.id,
                kind=status,
                payload={"note": note.strip(), "previous_status": previous},
                detected_by="user",
            )
            session.add(event)
            session.flush()
            return event
        return ThesisEvent(id=0, thesis_id=0, kind="noop")

    # -- evaluación del motor ----------------------------------------------------

    def evaluate(self, session: Session, thesis: InvestmentThesis) -> List[ThesisEvent]:
        """Indicios sobre la tesis abierta; no cambia el estado, solo sugiere."""
        if thesis.status in ("closed", "invalidated"):
            return []
        instrument = session.get(Instrument, thesis.instrument_id)
        if instrument is None:
            return []
        events: List[ThesisEvent] = []
        quote = self._basket_quote(session, thesis.instrument_id)
        price = None if quote is None else Decimal(str(quote.price))

        if price is not None:
            description = []
            hit: Optional[str] = None
            for condition in (thesis.invalidation_conditions or []):
                if not isinstance(condition, dict) or condition.get("type") not in (
                    "price_above",
                    "price_below",
                ):
                    continue
                threshold = Decimal(str(condition.get("price") or 0))
                if threshold <= 0:
                    continue
                triggered = (
                    price >= threshold
                    if condition["type"] == "price_above"
                    else price <= threshold
                )
                if triggered:
                    hit = hit or condition["type"]
                    description.append(
                        f"{'precio ≥' if condition['type'] == 'price_above' else 'precio ≤'} {threshold}"
                    )
            if thesis.exit_target is not None and price >= thesis.exit_target:
                description.append(f"objetivo de salida alcanzado: {thesis.exit_target}")
                hit = hit or "target_exit"
            if thesis.entry_target is not None and price <= thesis.entry_target:
                description.append(f"objetivo de entrada alcanzado: {thesis.entry_target}")
                hit = hit or "target_entry"
            if hit is not None:
                dedupe = f"thesis:{thesis.id}:price:{quote.as_of}"
                if not self._event_exists(session, thesis.id, dedupe):
                    events.append(self._engine_event(
                        session, thesis.id,
                        kind="price_signal",
                        payload={
                            "trigger": hit,
                            "price": str(price),
                            "as_of": quote.as_of.isoformat(),
                            "source": quote.source,
                            "quality": quote.quality,
                            "reasons": description,
                            "suggestion": "under_review",
                            "note": "Señal sobre cierres con procedencia; no es tiempo real.",
                        },
                        dedupe=dedupe,
                    ))
                if thesis.status == "open":
                    thesis.status = "under_review"

        events.extend(self._fundamentals_events(session, thesis))
        return events

    def _fundamentals_events(
        self, session: Session, thesis: InvestmentThesis
    ) -> List[ThesisEvent]:
        facts = (
            session.execute(
                select(FundamentalFact)
                .where(
                    FundamentalFact.instrument_id == thesis.instrument_id,
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
        dedupe = f"thesis:{thesis.id}:fnd:{previous.fiscal_end}:{current.fiscal_end}"
        if self._event_exists(session, thesis.id, dedupe):
            return []
        changes: Dict[str, str] = {}
        for metric in ("revenue", "net_income"):
            raw_previous = getattr(previous, metric)
            raw_current = getattr(current, metric)
            if raw_previous in (None, 0) or raw_current is None:
                continue
            old_value = Decimal(str(raw_previous))
            new_value = Decimal(str(raw_current))
            if old_value == 0:
                continue
            change = (new_value - old_value) / abs(old_value) * Decimal(100)
            if abs(change) >= FUNDAMENTAL_ALERT_PCT:
                changes[metric] = str(change.quantize(Decimal("0.01")))
        if not changes:
            return []
        return [self._engine_event(
            session,
            thesis.id,
            kind="fundamental_change",
            payload={
                "change_pct": changes,
                "previous_period": previous.fiscal_end.isoformat(),
                "current_period": current.fiscal_end.isoformat(),
                "sources": sorted({previous.source, current.source}),
                "threshold_pct": str(FUNDAMENTAL_ALERT_PCT),
                "suggestion": "under_review",
            },
            dedupe=dedupe,
        )]

    @staticmethod
    def _event_exists(session: Session, thesis_id: int, dedupe: str) -> bool:
        # Claves de deduplicación vividas en `payload["dedupe"]` propio del motor.
        related = session.execute(
            select(ThesisEvent.payload)
            .where(ThesisEvent.thesis_id == thesis_id, ThesisEvent.detected_by == "engine")
            .order_by(ThesisEvent.id.desc())
            .limit(50)
        ).all()
        for (payload,) in related:
            if isinstance(payload, dict) and payload.get("dedupe") == dedupe:
                return True
        return False

    def _engine_event(
        self,
        session: Session,
        thesis_id: int,
        *,
        kind: str,
        payload: Dict[str, Any],
        dedupe: str,
    ) -> ThesisEvent:
        payload = dict(payload)
        payload["dedupe"] = dedupe
        event = ThesisEvent(
            thesis_id=thesis_id,
            kind=kind,
            payload=payload,
            detected_by="engine",
        )
        session.add(event)
        return event

    def evaluate_user(self, session: Session, user_id: int) -> int:
        """Evalúa todas las tesis abiertas del usuario; devuelve indicios nuevos."""
        theses = (
            session.execute(
                select(InvestmentThesis)
                .where(
                    InvestmentThesis.user_id == user_id,
                    InvestmentThesis.status.in_(["open", "under_review"]),
                )
            )
            .scalars()
            .all()
        )
        total = 0
        for thesis in theses:
            total += len(self.evaluate(session, thesis))
        return total
