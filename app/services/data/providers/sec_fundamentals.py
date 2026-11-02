"""Adaptador SEC EDGAR companyfacts — fundamentales reportados por el emisor.

Fuente verificada en vivo (2026-10-31): `company_facts(CIK 320193)` respondió
503 conceptos XBRL usando `NEXO_SEC_CONTACT` (la SEC exige User-Agent con
contacto; sin él no se emite ninguna petición).

Reglas de honestidad del dato:

- Solo se almacenan magnitudes **publicadas por el emisor** en XBRL:
  ingresos, beneficio neto, EPS diluido, efectivo, deuda a largo plazo y
  acciones en circulación.
- EBITDA y flujo de caja libre NO se calculan aquí: la SEC no los publica como
  concepto. Prefiero `null` a presentar un cálculo como si fuese reportado.
- Los periodos anual y trimestral se guardan con `period_type` explícito y
  jamás se mezclan.
- Moneda: la de la unidad XBRL (USD en la práctica para filas 10-K/10-Q).

Límites: solo emisores con CIK (EE. UU.). El resto de mercados queda sin
fundamentales y se informa como «no disponible»; no se rellena con nada.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from app.services.data.base import (
    FundamentalObservation,
    ProviderDataError,
    ProviderNotConfigured,
    Provenance,
)
from nexo_invest.data.sec_edgar import COMPANY_FACTS_URL, SecEdgarClient
from nexo_invest.data.sec_edgar import ContactNotConfiguredError

# Prioridad por métrica: se usa la primera etiqueta con datos recientes. Si una
# métrica cambia de etiqueta entre ejercicios se conserva la más reciente; no se
# combinan etiquetas de periodos distintos.
METRIC_TAGS: Dict[str, List[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "total_debt": ["LongTermDebt"],
}
SHARES_TAG = "EntityCommonStockSharesOutstanding"
ANNUAL_DAYS = (340, 400)
QUARTER_DAYS = (80, 100)


def _days(entry: Dict[str, Any]) -> Optional[int]:
    start = entry.get("start")
    end = entry.get("end")
    if not start or not end:
        return None
    try:
        start_date = date.fromisoformat(str(start)[:10])
        end_date = date.fromisoformat(str(end)[:10])
    except ValueError:
        return None
    return (end_date - start_date).days


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None
    return result if result.is_finite() else None


def _pick_entry(
    entries: List[Dict[str, Any]], window: Tuple[int, int]
) -> Optional[Dict[str, Any]]:
    valid = []
    for entry in entries:
        span = _days(entry)
        if span is None or not (window[0] <= span <= window[1]):
            continue
        if not entry.get("end"):
            continue
        valid.append(entry)
    if not valid:
        return None
    return max(valid, key=lambda item: (str(item.get("end")), str(item.get("filed") or "")))


class SecFundamentalsProvider:
    name = "sec"
    category = "fundamentals"
    website = "https://www.sec.gov/edgar"
    license_url = "https://www.sec.gov/about/website-policies"
    terms_url = "https://www.sec.gov/os/accessing-edgar-data"
    limits = "Gratis con User-Agent de contacto (NEXO_SEC_CONTACT); ≤10 req/s y sin redistribución masiva."
    supports_history = True

    def __init__(self, contact: str, cache_dir: str = "") -> None:
        self.contact = contact
        self.cache_dir = cache_dir or None
        self._client: Optional[SecEdgarClient] = None
        self.last_request_count = 0

    def _require_client(self) -> SecEdgarClient:
        if self._client is None:
            self._client = SecEdgarClient(contact=self.contact, cache_dir=self.cache_dir)
        try:
            self._client.require_contact("fundamentales financieros")
        except ContactNotConfiguredError as exc:
            raise ProviderNotConfigured(str(exc)) from exc
        return self._client

    def _latest(
        self,
        payload: Dict[str, Any],
        tag: str,
        window: Tuple[int, int],
        unit_preference: List[str],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
        facts = payload.get("facts", {})
        node = facts.get("us-gaap", {}).get(tag) or facts.get("dei", {}).get(tag)
        if not isinstance(node, dict):
            return None, None, None
        units = node.get("units")
        if not isinstance(units, dict):
            return None, None, None
        chosen_unit = next((u for u in unit_preference if u in units), None)
        if chosen_unit is None:
            chosen_unit = next(iter(units), None)
        if chosen_unit is None:
            return None, None, None
        entries = units.get(chosen_unit)
        if not isinstance(entries, list):
            return None, None, None
        entry = _pick_entry(entries, window)
        return entry, chosen_unit, tag

    def fetch(
        self,
        *,
        instrument_id: int,
        cik: int,
        currency: str = "USD",
    ) -> List[FundamentalObservation]:
        client = self._require_client()
        before = len(client.fetches)
        payload, record = client.company_facts(int(cik))
        self.last_request_count = len(client.fetches) - before
        if not isinstance(payload, dict) or "facts" not in payload:
            raise ProviderDataError("SEC devolvió companyfacts sin facts")

        source_url = COMPANY_FACTS_URL.format(cik=int(cik))
        retrieved_at = record.retrieved_at or datetime.now(timezone.utc)
        observations: List[FundamentalObservation] = []

        shares_by_end: Dict[str, Decimal] = {}
        # Las acciones en circulación son instantáneas (sin start): se indexan por fecha.
        dei_node = payload.get("facts", {}).get("dei", {}).get(SHARES_TAG) or {}
        for unit_values in (dei_node.get("units") or {}).values():
            if isinstance(unit_values, list):
                for entry in unit_values:
                    end = entry.get("end")
                    value = _to_decimal(entry.get("val"))
                    if end and value is not None:
                        shares_by_end[str(end)[:10]] = value

        for period_type, window in (("annual", ANNUAL_DAYS), ("quarter", QUARTER_DAYS)):
            metrics: Dict[str, Optional[Decimal]] = {}
            fiscal_end: Optional[date] = None
            fiscal_start: Optional[date] = None
            reported_at: Optional[date] = None
            used_unit = currency

            for metric, tags in METRIC_TAGS.items():
                best: Optional[Dict[str, Any]] = None
                best_unit: Optional[str] = None
                for tag in tags:
                    entry, unit, _ = self._latest(payload, tag, window, ["USD", "USD/shares", "shares"])
                    if entry is None:
                        continue
                    if best is None or str(entry.get("end")) >= str(best.get("end")):
                        best, best_unit = entry, unit
                if best is None:
                    metrics[metric] = None
                    continue
                metrics[metric] = _to_decimal(best.get("val"))
                end = str(best.get("end") or "")[:10]
                start = best.get("start")
                filed = str(best.get("filed") or "")[:10]
                if end:
                    candidate = date.fromisoformat(end)
                    if fiscal_end is None or candidate > fiscal_end:
                        fiscal_end = candidate
                if start:
                    fiscal_start = date.fromisoformat(str(start)[:10])
                if filed:
                    filed_date = date.fromisoformat(filed)
                    reported_at = filed_date if reported_at is None else max(reported_at, filed_date)
                if best_unit and best_unit not in {"USD", "USD/shares"}:
                    used_unit = best_unit

            if fiscal_end is None or not any(v is not None for v in metrics.values()):
                continue
            shares = shares_by_end.get(fiscal_end.isoformat())
            metrics["shares_outstanding"] = shares
            observations.append(
                FundamentalObservation(
                    instrument_id=instrument_id,
                    period_type=period_type,
                    fiscal_end=fiscal_end,
                    fiscal_start=fiscal_start,
                    reported_at=reported_at,
                    currency=used_unit if used_unit.isalpha() and len(used_unit) == 3 else currency,
                    source=self.name,
                    provenance=Provenance(
                        provider=self.name,
                        category="fundamentals",
                        source_url=source_url,
                        data_as_of=fiscal_end,
                        retrieved_at=retrieved_at,
                        quality="reported",
                        kind="",
                        notes="XBRL reportado por el emisor; EBITDA y FCF no se calculan",
                    ),
                    metrics=metrics,
                )
            )
        if not observations:
            raise ProviderDataError(
                f"SEC no devolvió periodos anuales ni trimestrales para CIK {cik}"
            )
        return observations
