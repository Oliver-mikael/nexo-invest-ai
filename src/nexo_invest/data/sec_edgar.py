"""Adaptador de SEC EDGAR (fuente oficial, gratuita y pública).

Condiciones de acceso respetadas por este módulo:

- `User-Agent` identificable y declarado en todas las peticiones, tal como exige
  la política de acceso de la SEC (<https://www.sec.gov/os/webmaster-faq#developers>).
  El contacto se toma de la variable de entorno `NEXO_SEC_CONTACT`; si no está
  definida se usa un marcador y se registra como limitación.
- Límite de peticiones: como máximo 10 por segundo según la SEC. Aquí se aplica un
  intervalo mínimo configurable (por defecto 0.15 s ≈ 6.6 peticiones/s) y un bloqueo
  entre hilos para no superarlo nunca.
- Caché en disco opcional, para no repetir descargas y para poder reproducir el
  análisis sin volver a consultar la fuente.
- Se guarda SHA-256 del contenido crudo descargado, de modo que una observación
  puede ligarse al byte exacto de la respuesta.

Distinción de procedencia (importante):

- `EXTERNAL_DOWNLOADED`: la descarga fue correcta. NO dice que la cifra sea cierta.
- `EXTERNAL_VALIDATED`: además pasó comprobaciones internas (unidades homogéneas,
  fechas coherentes, identidad contable Activo = Pasivo + Patrimonio).
- `EXTERNAL_CORROBORATED`: dos rutas de concepto independientes dentro de la misma
  presentación coinciden en la misma cifra. Es corroboración dentro de la fuente,
  no una segunda fuente independiente; la limitación queda registrada.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from nexo_invest.core.periods import FiscalCalendar
from nexo_invest.core.sources import (
    DataOrigin,
    DataSource,
    DataType,
    ProvenanceLevel,
    ProvenanceRegistry,
    VerificationState,
)
from nexo_invest.core.units import Frequency, Money, Period, Scale
from nexo_invest.data.inline_xbrl import (
    REVENUE_CONCEPT,
    InlineXbrlDocument,
    InlineXbrlError,
    ResolvedFact,
    document_sha256,
    extract_annual_revenue,
    parse_document,
)

SEC_BASE = "https://data.sec.gov"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = SEC_BASE + "/submissions/CIK{cik:0>10}.json"
COMPANY_FACTS_URL = SEC_BASE + "/api/xbrl/companyfacts/CIK{cik:0>10}.json"

# La SEC exige un User-Agent con nombre y correo de contacto. Sin un correo con
# formato válido responde HTTP 403 (comprobado el 2026-10-27). El valor por defecto es
# un marcador: el usuario debe definir NEXO_SEC_CONTACT con su dirección real.
DEFAULT_CONTACT_PLACEHOLDER = "nexo-invest-ai-research@example.com"

# Cabeceras Accept según el tipo de contenido que se pide. Las llamadas JSON siguen
# recibiendo el Accept de siempre; el documento primario (HTML) se pide con el suyo.
ACCEPT_JSON = "application/json"
ACCEPT_HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


# --------------------------------------------------------------------------------------
# Mapa de conceptos XBRL -> métrica interna
# --------------------------------------------------------------------------------------
# Cada métrica lista conceptos en orden de preferencia. El primero disponible gana y
# los alternativos se usan para corroboración. No se inventa ningún valor: si ningún
# concepto existe, la métrica queda ausente (None) y se registra la limitación.
CONCEPT_MAP: Dict[str, List[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
    ],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capital_expenditures": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "short_term_investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent"],
    "inventory": ["InventoryNet"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "shareholders_equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "long_term_debt_current": ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "long_term_debt_noncurrent": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"],
    "short_term_borrowings": ["ShortTermBorrowings", "CommercialPaper"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating"],
    "income_tax_expense": ["IncomeTaxExpenseBenefit"],
    "income_before_tax": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "shares_outstanding": ["CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"],
    "dividends_paid": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    "share_repurchases": ["PaymentsForRepurchaseOfCommonStock"],
}

# Métricas que solo tienen sentido en un balance (valor instantáneo, sin `start`).
INSTANT_METRICS = {
    "cash_and_equivalents",
    "short_term_investments",
    "inventory",
    "current_assets",
    "current_liabilities",
    "total_assets",
    "total_liabilities",
    "shareholders_equity",
    "long_term_debt_current",
    "long_term_debt_noncurrent",
    "short_term_borrowings",
    "shares_outstanding",
}

# Métricas que se suman para obtener deuda total. Aproximación documentada: no
# incluye arrendamientos operativos ni instrumentos híbridos.
DEBT_COMPONENTS = ("long_term_debt_current", "long_term_debt_noncurrent", "short_term_borrowings")

SEC_FORMS = ("10-K", "10-Q", "20-F", "40-F")


class SecEdgarError(RuntimeError):
    """Error de acceso o de contenido de SEC EDGAR."""


class ContactNotConfiguredError(SecEdgarError):
    """Falta el contacto real que la SEC exige en el User-Agent.

    No se sustituye por una dirección inventada: sin contacto real la petición no se
    emite y el resultado queda como verificación no completada.
    """


class PrimaryDocumentError(SecEdgarError):
    """Los bytes descargados no son el documento primario esperado."""


@dataclass
class FetchRecord:
    """Evidencia de una descarga: qué se pidió, cuándo y con qué resultado."""

    url: str
    retrieved_at: datetime
    status: Optional[int]
    bytes_received: int
    sha256: str
    from_cache: bool
    error: Optional[str] = None
    content_type: Optional[str] = None

    def as_dict(self) -> Dict[str, object]:
        return {
            "url": self.url,
            "retrieved_at": self.retrieved_at.isoformat(),
            "status": self.status,
            "bytes": self.bytes_received,
            "sha256": self.sha256,
            "from_cache": self.from_cache,
            "error": self.error,
            "content_type": self.content_type,
        }


class SecEdgarClient:
    """Cliente HTTP mínimo para SEC EDGAR, con límite de uso y caché."""

    def __init__(
        self,
        contact: Optional[str] = None,
        min_interval_seconds: float = 0.15,
        timeout: float = 20.0,
        cache_dir: Optional[Path] = None,
    ) -> None:
        resolved = contact or os.environ.get("NEXO_SEC_CONTACT") or DEFAULT_CONTACT_PLACEHOLDER
        self.contact = resolved.strip()
        self.contact_is_placeholder = self.contact == DEFAULT_CONTACT_PLACEHOLDER
        self.user_agent = f"Nexo Invest AI research prototype ({self.contact})"
        self.min_interval_seconds = max(min_interval_seconds, 0.11)
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._lock = threading.Lock()
        self._last_request_at = 0.0
        self.fetches: List[FetchRecord] = []

    # -- utilidades internas -----------------------------------------------------------

    def _cache_path(self, url: str) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        name = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24] + ".json"
        return self.cache_dir / name

    def _throttle(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            remaining = self.min_interval_seconds - elapsed
            if remaining > 0:
                time.sleep(remaining)
            self._last_request_at = time.monotonic()

    def get_raw(
        self, url: str, use_cache: bool = True, *, accept: str = ACCEPT_JSON
    ) -> Tuple[bytes, FetchRecord]:
        """Descarga (o recupera de caché) el contenido crudo de una URL de la SEC."""

        cache_path = self._cache_path(url) if use_cache else None
        if cache_path is not None and cache_path.exists():
            raw = cache_path.read_bytes()
            record = FetchRecord(
                url=url,
                retrieved_at=datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc),
                status=200,
                bytes_received=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                from_cache=True,
            )
            self.fetches.append(record)
            return raw, record

        self._throttle()
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": accept,
                "Accept-Encoding": "gzip",
                "Host": url.split("/")[2],
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                status = response.status
                if response.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                content_type = response.headers.get("Content-Type") or None
        except urllib.error.HTTPError as exc:  # respuesta HTTP con código de error
            record = FetchRecord(
                url=url,
                retrieved_at=datetime.now(timezone.utc),
                status=exc.code,
                bytes_received=0,
                sha256="",
                from_cache=False,
                error=f"HTTP {exc.code}",
            )
            self.fetches.append(record)
            raise SecEdgarError(f"SEC EDGAR devolvió HTTP {exc.code} para {url}") from exc
        except Exception as exc:  # red, DNS, TLS, timeout
            record = FetchRecord(
                url=url,
                retrieved_at=datetime.now(timezone.utc),
                status=None,
                bytes_received=0,
                sha256="",
                from_cache=False,
                error=f"{type(exc).__name__}: {exc}",
            )
            self.fetches.append(record)
            raise SecEdgarError(f"No se pudo consultar {url}: {type(exc).__name__}: {exc}") from exc

        if content_type is not None and ";" in content_type:
            content_type = content_type.split(";", 1)[0].strip()
        record = FetchRecord(
            url=url,
            retrieved_at=datetime.now(timezone.utc),
            status=status,
            bytes_received=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            from_cache=False,
            content_type=content_type,
        )
        self.fetches.append(record)
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(raw)
        return raw, record

    def get_json(self, url: str, use_cache: bool = True) -> Tuple[dict, FetchRecord]:
        raw, record = self.get_raw(url, use_cache=use_cache)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise SecEdgarError(f"Respuesta no interpretable como JSON desde {url}") from exc
        if not isinstance(payload, dict):
            raise SecEdgarError(f"Se esperaba un objeto JSON en {url}")
        return payload, record

    # -- API pública -------------------------------------------------------------------

    def company_tickers(self) -> Tuple[dict, FetchRecord]:
        return self.get_json(SEC_TICKERS_URL)

    def resolve_cik(self, ticker: str) -> Optional[int]:
        """Resuelve un ticker a CIK usando el fichero oficial de la SEC (sin adivinar)."""

        payload, _ = self.company_tickers()
        wanted = ticker.strip().upper()
        for entry in payload.values():
            if not isinstance(entry, dict):
                continue
            if str(entry.get("ticker", "")).upper() == wanted:
                return int(entry["cik_str"])
        return None

    def submissions(self, cik: int) -> Tuple[dict, FetchRecord]:
        return self.get_json(SUBMISSIONS_URL.format(cik=int(cik)))

    def company_facts(self, cik: int) -> Tuple[dict, FetchRecord]:
        return self.get_json(COMPANY_FACTS_URL.format(cik=int(cik)))

    def require_contact(self, action: str) -> None:
        """Exige un contacto real antes de acciones que la SEC condiciona al User-Agent.

        No se inventa ninguna dirección: si falta o es el marcador, se lanza
        `ContactNotConfiguredError` y no se emite ninguna petición.
        """

        if not self.contact.strip() or self.contact_is_placeholder:
            raise ContactNotConfiguredError(
                f"Se requiere NEXO_SEC_CONTACT real y no vacío para {action}. "
                "La política de acceso de la SEC exige un User-Agent identificable "
                "(sin él responde HTTP 403) y no se usa ninguna dirección inventada."
            )

    def get_document(self, url: str, use_cache: bool = True) -> Tuple[bytes, FetchRecord]:
        """Descarga un documento HTML de la SEC (p. ej. un 10-K) con contacto real."""

        self.require_contact("descargar el documento primario de SEC EDGAR")
        return self.get_raw(url, use_cache=use_cache, accept=ACCEPT_HTML)


# --------------------------------------------------------------------------------------
# Extracción de hechos XBRL
# --------------------------------------------------------------------------------------


@dataclass
class FactRecord:
    """Un hecho XBRL normalizado, todavía sin juicio de valor."""

    metric: str
    concept: str
    taxonomy: str
    start: Optional[date]
    end: date
    value: float
    unit: str
    form: str
    fiscal_year: Optional[int]
    fiscal_period: Optional[str]
    accession: str
    filed: Optional[date]
    frame: Optional[str] = None

    @property
    def days(self) -> Optional[int]:
        if self.start is None:
            return None
        return (self.end - self.start).days


def _parse_date(text: Optional[str]) -> Optional[date]:
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _iter_facts(payload: dict) -> Iterable[Tuple[str, str, str, dict]]:
    """Itera (taxonomía, concepto, unidad, hecho) sobre un documento companyfacts."""

    facts = payload.get("facts")
    if not isinstance(facts, dict):
        return
    for taxonomy, concepts in facts.items():
        if not isinstance(concepts, dict):
            continue
        for concept, body in concepts.items():
            if not isinstance(body, dict):
                continue
            units = body.get("units")
            if not isinstance(units, dict):
                continue
            for unit, entries in units.items():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if isinstance(entry, dict):
                        yield taxonomy, concept, unit, entry


def _is_instance_metric(metric: str) -> bool:
    return metric in INSTANT_METRICS


def extract_observations(
    payload: dict,
    *,
    forms: Sequence[str] = SEC_FORMS,
    prefer_annual: bool = True,
) -> Dict[str, List[FactRecord]]:
    """Agrupa los hechos de companyfacts por métrica interna.

    Reglas explícitas (sin inventar nada):

    - Solo se aceptan hechos de formularios en `forms` (10-K/10-Q/20-F/40-F).
    - Un hecho se acepta solo si tiene fecha de fin y valor numérico.
    - Métricas de balance (instantáneas) se aceptan sin `start`; las de flujo exigen
      `start` para poder calcular la duración del periodo.
    - Si el mismo concepto aparece en varios formularios para el mismo periodo, se
      conserva el de presentación más reciente (filed más alto), que es el dato
      enmendado o definitivo.
    """

    grouped: Dict[str, Dict[Tuple[date, Optional[date], str], FactRecord]] = {}
    accepted_forms = {f.upper() for f in forms}

    for taxonomy, concept, unit, entry in _iter_facts(payload):
        metric = _metric_for_concept(concept)
        if metric is None:
            continue
        form = str(entry.get("form", "")).upper()
        if form not in accepted_forms:
            continue
        raw_value = entry.get("val")
        if not isinstance(raw_value, (int, float)):
            continue
        end = _parse_date(entry.get("end"))
        if end is None:
            continue
        start = _parse_date(entry.get("start"))
        if start is None and not _is_instance_metric(metric):
            # Un flujo sin fecha de inicio no permite saber a qué periodo corresponde.
            continue
        if start is not None and start > end:
            continue
        fact = FactRecord(
            metric=metric,
            concept=concept,
            taxonomy=taxonomy,
            start=start,
            end=end,
            value=float(raw_value),
            unit=unit,
            form=form,
            fiscal_year=entry.get("fy") if isinstance(entry.get("fy"), int) else None,
            fiscal_period=entry.get("fp") if isinstance(entry.get("fp"), str) else None,
            accession=str(entry.get("accn", "")),
            filed=_parse_date(entry.get("filed")),
            frame=entry.get("frame") if isinstance(entry.get("frame"), str) else None,
        )
        key = (end, start, unit)
        bucket = grouped.setdefault(metric, {})
        existing = bucket.get(key)
        if existing is None:
            bucket[key] = fact
        else:
            existing_filed = existing.filed or date.min
            new_filed = fact.filed or date.min
            if new_filed >= existing_filed:
                bucket[key] = fact

    result: Dict[str, List[FactRecord]] = {}
    for metric, bucket in grouped.items():
        records = list(bucket.values())
        records.sort(key=lambda r: (r.end, r.start or date.min))
        result[metric] = records
    return result


def _metric_for_concept(concept: str) -> Optional[str]:
    for metric, concepts in CONCEPT_MAP.items():
        if concept in concepts:
            return metric
    return None


def period_from_fact(fact: FactRecord) -> Period:
    """Traduce un hecho XBRL a un Period del motor financiero.

    Convención documentada: los hechos de duración <= 120 días se marcan como
    trimestrales y el resto como anuales. Las instantáneas (balance) no tienen
    duración y se marcan como anuales, que es la frecuencia con la que se usan.
    """

    start = fact.start or fact.end
    if fact.start is None:
        frequency = Frequency.ANNUAL
    elif (fact.end - fact.start).days <= 120:
        frequency = Frequency.QUARTERLY
    else:
        frequency = Frequency.ANNUAL
    return Period(start=start, end=fact.end, frequency=frequency)


def select_annual_facts(records: Sequence[FactRecord]) -> List[FactRecord]:
    """Selecciona solo los hechos de duración anual (o instantáneas)."""

    selected: List[FactRecord] = []
    for fact in records:
        if fact.start is None:
            selected.append(fact)
            continue
        days = (fact.end - fact.start).days
        if 330 <= days <= 400:
            selected.append(fact)
    return selected


def select_quarterly_facts(records: Sequence[FactRecord]) -> List[FactRecord]:
    selected: List[FactRecord] = []
    for fact in records:
        if fact.start is None:
            continue
        days = (fact.end - fact.start).days
        if 80 <= days <= 100:
            selected.append(fact)
    return selected


# --------------------------------------------------------------------------------------
# Construcción de procedencia
# --------------------------------------------------------------------------------------


@dataclass
class SecEdgarResult:
    """Resultado del análisis de una empresa a partir de SEC EDGAR."""

    cik: int
    entity_name: str
    registry: ProvenanceRegistry
    facts: Dict[str, List[FactRecord]]
    fetch_records: List[FetchRecord]
    validated_metrics: List[str] = field(default_factory=list)
    corroborated_metrics: List[str] = field(default_factory=list)
    validation_notes: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)

    def source_url(self) -> str:
        return COMPANY_FACTS_URL.format(cik=self.cik)

    def content_sha256(self) -> Optional[str]:
        for record in self.fetch_records:
            if "companyfacts" in record.url and record.sha256:
                return record.sha256
        return None


def _scale_for_unit(unit: str) -> Scale:
    """Las cifras XBRL llegan en unidades; se conserva el valor tal cual."""

    if unit.upper() in {"USD", "EUR", "GBP", "BRL", "MXN"}:
        return Scale.UNITS
    return Scale.UNITS


@dataclass
class _BalanceIdentity:
    assets: Optional[float] = None
    liabilities: Optional[float] = None
    equity: Optional[float] = None

    def consistent(self, tolerance: float = 0.01) -> Optional[bool]:
        if None in (self.assets, self.liabilities, self.equity):
            return None
        expected = self.liabilities + self.equity
        if self.assets == 0:
            return None
        return abs(self.assets - expected) / abs(self.assets) <= tolerance


def build_registry_from_companyfacts(
    payload: dict,
    *,
    cik: int,
    fetch_records: Sequence[FetchRecord],
    currency: str = "USD",
    registry: Optional[ProvenanceRegistry] = None,
    max_annual_periods: Optional[int] = None,
) -> SecEdgarResult:
    """Construye un ProvenanceRegistry desde un documento companyfacts.

    - Cada métrica se registra con su fuente XBRL, la URL, el SHA-256 del contenido
      descargado, el formulario, la fecha de presentación y el accession number.
    - Todas las observaciones empiezan en `EXTERNAL_DOWNLOADED`.
    - Solo se promueven a `EXTERNAL_VALIDATED` las métricas que superan las
      comprobaciones internas documentadas en `validation_notes`.
    - La corroboración intra-fuente (dos conceptos alternativos coincidentes) se
      registra explícitamente como tal, sin presentarla como segunda fuente.
    """

    entity = str(payload.get("entityName") or f"CIK {cik}")
    cik_from_payload = payload.get("cik")
    cik_resolved = int(cik_from_payload) if isinstance(cik_from_payload, int) else int(cik)
    facts = extract_observations(payload)

    if registry is None:
        registry = ProvenanceRegistry()

    content_hash = next(
        (r.sha256 for r in fetch_records if "companyfacts" in r.url and r.sha256), None
    )
    retrieval = next(
        (r.retrieved_at.date() for r in fetch_records if "companyfacts" in r.url), date.today()
    )
    url = COMPANY_FACTS_URL.format(cik=cik_resolved)
    limitations: List[str] = [
        "Valores tomados del XBRL presentado por la empresa; no se ha auditado el documento original.",
        "La corroboración implementada es interna a la misma presentación, no una segunda fuente independiente.",
        "Los periodos acumulados YTD (6 y 9 meses) se excluyen para no mezclarlos con trimestres sueltos.",
    ]

    validated: List[str] = []
    corroborated: List[str] = []
    validation_notes: List[str] = []

    # Identidad contable por periodo de balance, para validar Assets/Liabilities/Equity.
    identity_by_end: Dict[date, _BalanceIdentity] = {}
    for metric, key in (
        ("total_assets", "assets"),
        ("total_liabilities", "liabilities"),
        ("shareholders_equity", "equity"),
    ):
        for fact in facts.get(metric, []):
            identity = identity_by_end.setdefault(fact.end, _BalanceIdentity())
            setattr(identity, key, fact.value)

    for metric, records in sorted(facts.items()):
        # Se registran hechos anuales y trimestrales reales. Los periodos intermedios
        # (6 y 9 meses, acumulados YTD) se excluyen a propósito: mezclarlos con
        # trimestres produciría sumas financieramente incorrectas.
        roles: List[Tuple[FactRecord, str]] = []
        for record in records:
            if record.start is None:
                roles.append((record, "instantanea"))
                continue
            days = (record.end - record.start).days
            if days <= 100:
                roles.append((record, "trimestral"))
            elif 330 <= days <= 400:
                roles.append((record, "anual"))
        if not roles:
            continue
        annual_facts = [f for f, role in roles if role == "anual"]
        if max_annual_periods and annual_facts:
            keep_annual = {f.end for f in annual_facts[-max_annual_periods:]}
            roles = [
                (f, role)
                for f, role in roles
                if role != "anual" or f.end in keep_annual
            ]
        annual = annual_facts
        if not roles:
            continue
        concepts_used = {f.concept for f in records}
        source = DataSource(
            id=f"sec-edgar-companyfacts-{cik_resolved}-{metric}",
            name=f"SEC EDGAR companyfacts · {metric}",
            entity=entity,
            url=url,
            reference=f"CIK {cik_resolved} · conceptos: {', '.join(sorted(concepts_used))}",
            data_type=(
                DataType.BALANCE_SHEET
                if metric in INSTANT_METRICS
                else DataType.INCOME_STATEMENT
                if metric
                in {
                    "revenue",
                    "gross_profit",
                    "operating_income",
                    "net_income",
                    "interest_expense",
                    "income_tax_expense",
                    "income_before_tax",
                }
                else DataType.CASH_FLOW
                if metric
                in {
                    "operating_cash_flow",
                    "capital_expenditures",
                    "dividends_paid",
                    "share_repurchases",
                }
                else DataType.METRIC
            ),
            publication_date=max((f.filed for f in records if f.filed), default=None),
            retrieval_date=retrieval,
            currency=currency,
            scale=Scale.UNITS,
            extraction_method="sec-edgar companyfacts JSON (XBRL us-gaap)",
            verification_state=VerificationState.PENDING,
            origin=DataOrigin.EXTERNAL_UNVERIFIED,
            notes=f"Contenido descargado verificado por SHA-256: {content_hash}",
            limitations=list(limitations),
            hash=content_hash,
        )
        if source.id in registry.sources:
            source.id = source.id + "-dup"
        registry.register_source(source)

        # Comprobaciones internas. La promoción a VALIDATED es POR OBSERVACIÓN:
        # un periodo históricamente inconsistente no invalida los demás, pero
        # tampoco se les concede el nivel superior.
        # Las comprobaciones se hacen sobre TODAS las observaciones registradas de la
        # métrica (anuales, trimestrales e instantáneas), no solo sobre las anuales:
        # una métrica con solo datos trimestrales también debe poder validarse.
        registered = [f for f, _ in roles]
        units = {f.unit for f in registered}
        unit_ok = len(units) == 1
        dates_ok = all(f.end and (f.filed is None or f.filed >= f.end) for f in registered)

        identity_state: Dict[date, Optional[bool]] = {}
        if metric in {"total_assets", "total_liabilities", "shareholders_equity"}:
            for end, identity in identity_by_end.items():
                identity_state[end] = identity.consistent()

        # Corroboración: mismo periodo por concepto alternativo o aritmética de flujos.
        corroborating: Dict[date, str] = {}
        for fact in annual:
            evidence = _corroboration_evidence(metric, records, fact)
            if evidence is not None:
                corroborating[fact.end] = evidence

        n_obs_validated = 0
        n_obs_corroborated = 0
        n_obs_withheld = 0
        withheld_periods: List[str] = []

        for fact, role in roles:
            period = period_from_fact(fact)
            reasons: List[str] = []
            if not unit_ok:
                reasons.append("unidades heterogéneas")
            if not dates_ok:
                reasons.append("fechas incoherentes en el conjunto de la métrica")
            identity = identity_state.get(fact.end)
            if identity is False:
                reasons.append(
                    "identidad contable Activo = Pasivo + Patrimonio no se cumple "
                    f"en este periodo ({fact.end.isoformat()})"
                )

            if reasons:
                obs_level = ProvenanceLevel.EXTERNAL_DOWNLOADED
                n_obs_withheld += 1
                withheld_periods.append(fact.end.isoformat())
            else:
                obs_level = ProvenanceLevel.EXTERNAL_VALIDATED
                n_obs_validated += 1
                evidence = corroborating.get(fact.end)
                if evidence:
                    obs_level = ProvenanceLevel.EXTERNAL_CORROBORATED
                    n_obs_corroborated += 1

            registry.observation(
                source_id=source.id,
                metric=metric,
                period=period,
                value=Money(fact.value, currency, Scale.UNITS, label=fact.concept),
                value_origin=DataOrigin.EXTERNAL_UNVERIFIED,
                verified=False,
                notes=(
                    f"rol={role} form={fact.form} fy={fact.fiscal_year} fp={fact.fiscal_period} "
                    f"filed={fact.filed.isoformat() if fact.filed else 'n/d'} "
                    f"accn={fact.accession} concepto={fact.concept}"
                    + (f" | corroboración: {corroborating[fact.end]}" if obs_level is ProvenanceLevel.EXTERNAL_CORROBORATED else "")
                    + (" | " + "; ".join(reasons) if reasons else "")
                ),
                limitations=list(limitations),
                provenance_level=obs_level,
            )

        if n_obs_validated or n_obs_corroborated:
            validated.append(metric)
        if n_obs_corroborated:
            corroborated.append(metric)
        note = (
            f"{metric}: {n_obs_validated} observación(es) validadas, "
            f"{n_obs_corroborated} corroboradas, {n_obs_withheld} sin promover "
            f"(unidades: {', '.join(sorted(units))})"
        )
        if withheld_periods:
            note += "; periodos sin promover: " + ", ".join(sorted(set(withheld_periods)))
        validation_notes.append(note)

    if content_hash:
        limitations.append(f"SHA-256 del contenido descargado: {content_hash}")

    return SecEdgarResult(
        cik=cik_resolved,
        entity_name=entity,
        registry=registry,
        facts=facts,
        fetch_records=list(fetch_records),
        validated_metrics=sorted(set(validated)),
        corroborated_metrics=sorted(set(corroborated)),
        validation_notes=validation_notes,
        limitations=limitations,
    )


def _corroborating_fact(
    metric: str,
    records: Sequence[FactRecord],
    fact: FactRecord,
) -> Optional[FactRecord]:
    """Hecho del mismo periodo y valor desde un concepto alternativo del mapa."""

    primary_concepts = CONCEPT_MAP.get(metric, [])
    if len(primary_concepts) < 2 or fact.value == 0:
        return None
    for candidate in records:
        if candidate.concept == fact.concept:
            continue
        if candidate.concept not in primary_concepts:
            continue
        if candidate.end == fact.end and candidate.start == fact.start:
            if abs(candidate.value - fact.value) / abs(fact.value) <= 0.01:
                return candidate
    return None


def _quarters_summing_to(
    records: Sequence[FactRecord],
    fact: FactRecord,
    tolerance: float = 0.01,
) -> Optional[List[FactRecord]]:
    """Cuatro trimestres consecutivos que cubren el periodo anual y suman su valor.

    Solo se aceptan duraciones trimestrales reales (80-100 días), de modo que nunca
    se suman cifras acumuladas YTD como si fueran trimestres sueltos.
    """

    if fact.start is None or fact.value == 0:
        return None
    quarters = [
        f
        for f in records
        if f.start is not None and 80 <= (f.end - f.start).days <= 100
    ]
    quarters.sort(key=lambda f: f.end)
    sequence: List[FactRecord] = []
    total = 0.0
    for quarter in quarters:
        if sequence:
            gap = (quarter.start - sequence[-1].end).days
            if gap > 5 or gap < -5:
                sequence = []
                total = 0.0
        sequence.append(quarter)
        total += quarter.value
        if len(sequence) == 4:
            break
    if len(sequence) < 4:
        return None
    if abs((sequence[0].start - fact.start).days) > 5:
        return None
    if abs((sequence[-1].end - fact.end).days) > 5:
        return None
    if abs(total - fact.value) / abs(fact.value) <= tolerance:
        return sequence
    return None


def _corroboration_evidence(
    metric: str,
    records: Sequence[FactRecord],
    fact: FactRecord,
) -> Optional[str]:
    """Evidencia de corroboración disponible para un hecho anual.

    Se aceptan dos rutas, ambas intra-fuente y así se declaran:
    - un concepto alternativo del mismo emisor presenta el mismo valor y periodo;
    - cuatro trimestres consecutivos del mismo concepto suman el valor anual.
    """

    alternative = _corroborating_fact(metric, records, fact)
    if alternative is not None:
        return f"concepto alternativo {alternative.concept} (mismo periodo, mismo valor)"
    quarters = _quarters_summing_to(records, fact)
    if quarters:
        ends = ", ".join(q.end.isoformat() for q in quarters)
        return f"suma de 4 trimestres consecutivos ({ends})"
    return None


def analyze_company(
    client: SecEdgarClient,
    *,
    cik: Optional[int] = None,
    ticker: Optional[str] = None,
    currency: str = "USD",
    max_annual_periods: Optional[int] = None,
) -> SecEdgarResult:
    """Descarga y registra una empresa real desde SEC EDGAR.

    Ni la descarga ni el registro implican que las cifras sean correctas: eso se
    decide en las comprobaciones de validación y queda escrito en el resultado.
    """

    if cik is None:
        if ticker is None:
            raise ValueError("Se requiere cik o ticker")
        resolved = client.resolve_cik(ticker)
        if resolved is None:
            raise SecEdgarError(f"Ticker no encontrado en el fichero oficial de la SEC: {ticker}")
        cik = resolved
    payload, record = client.company_facts(int(cik))
    return build_registry_from_companyfacts(
        payload,
        cik=int(cik),
        fetch_records=[record],
        currency=currency,
        max_annual_periods=max_annual_periods,
    )


def fiscal_calendar_for(payload: dict) -> FiscalCalendar:
    """Infiere el mes de cierre fiscal a partir de los cierres ANUALES.

    Solo se consideran hechos de duración anual (330-400 días) y las instantáneas de
    balance presentadas en un 10-K. Contar también los trimestres daba meses de cierre
    incorrectos (con Apple devolvía junio en lugar de septiembre).
    """

    facts = extract_observations(payload)
    counters: Dict[int, int] = {}
    for metric, records in facts.items():
        for fact in records:
            if fact.start is not None:
                days = (fact.end - fact.start).days
                if not (330 <= days <= 400):
                    continue
            elif fact.form not in ("10-K", "20-F", "40-F"):
                continue
            counters[fact.end.month] = counters.get(fact.end.month, 0) + 1
    if not counters:
        return FiscalCalendar(close_month=12)
    close_month = max(counters.items(), key=lambda item: (item[1], -item[0]))[0]
    return FiscalCalendar(close_month=close_month)


# --------------------------------------------------------------------------------------
# Documento primario: el formulario en HTML (Inline XBRL)
# --------------------------------------------------------------------------------------
#
# La API CompanyFacts es un resumen estructurado del mismo contenido que la empresa
# presenta; el HTML es la presentación tal y como se envió. Contrastar ambos comprueba
# que la extracción es correcta, NO que haya una fuente independiente: esa limitación
# se escribe en el informe y en cada contraste.


def _ix_non_numeric_value(html: str, name: str) -> Optional[str]:
    """Lee un hecho `ix:nonNumeric` concreto por su nombre (identidad del documento).

    No es un parser general de `ix:nonNumeric`: solo se usa para comprobar que los
    bytes descargados corresponden al formulario, la entidad y el ejercicio esperados.
    """

    pattern = re.compile(
        r'<ix:nonNumeric\b[^>]*\bname="' + re.escape(name) + r'"[^>]*>(.*?)</ix:nonNumeric>',
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(html)
    if match is None:
        return None
    text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
    return text or None


@dataclass
class PrimaryDocument:
    """Documento primario descargado, validado e identificado."""

    raw: bytes
    fetch: FetchRecord
    document: InlineXbrlDocument
    url: str
    accession: str
    cik: int
    form: Optional[str]
    fiscal_year: Optional[int]
    fiscal_period: Optional[str]
    entity_cik: Optional[str]
    entity_name: Optional[str]

    @property
    def sha256(self) -> str:
        return document_sha256(self.raw)

    @property
    def retrieval_date(self) -> date:
        return self.fetch.retrieved_at.date()

    def annual_revenue(self, *, period_start: date, period_end: date) -> ResolvedFact:
        """Ingreso consolidado del ejercicio indicado, extraído del propio HTML."""

        return extract_annual_revenue(
            self.document, period_start=period_start, period_end=period_end
        )


def parse_primary_document(
    raw: bytes,
    *,
    url: str,
    accession: str,
    cik: int,
    fetch: FetchRecord,
    expected_form: str = "10-K",
    expected_fiscal_year: Optional[int] = None,
) -> PrimaryDocument:
    """Comprueba que los bytes descargados son realmente el documento esperado.

    Nada de esto se salta: un código HTTP correcto no basta. Se comprueba el código,
    el tipo de contenido, que sea HTML, que contenga marcado Inline XBRL, que la URL
    corresponda al accession declarado y que el documento se identifique como el
    formulario/entidad/ejercicio esperados. Cualquier fallo lanza
    `PrimaryDocumentError` (verificación no completada), nunca devuelve un 10-K
    supuesto.
    """

    if fetch.status != 200:
        raise PrimaryDocumentError(
            f"Código HTTP inesperado para el documento primario: {fetch.status}"
        )

    if fetch.content_type and not any(
        token in fetch.content_type for token in ("html", "xml")
    ):
        raise PrimaryDocumentError(
            f"El servidor devolvió {fetch.content_type!r} y no un documento HTML."
        )

    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PrimaryDocumentError("El documento no está en UTF-8: no se interpreta.") from exc

    lowered = html.lower()
    if "<html" not in lowered and "<!doctype html" not in lowered:
        raise PrimaryDocumentError(
            "El contenido recibido no es un documento HTML "
            "(probable página de error o respuesta inesperada)."
        )

    if accession.replace("-", "") not in url:
        raise PrimaryDocumentError(
            f"La URL no corresponde al accession declarado {accession}: {url}"
        )

    try:
        document = parse_document(html)
    except InlineXbrlError as exc:
        raise PrimaryDocumentError(
            f"El HTML no contiene marcado Inline XBRL utilizable: {exc}"
        ) from exc
    if not document.contexts or not document.facts:
        raise PrimaryDocumentError(
            "El HTML no contiene contextos ni hechos Inline XBRL: no es un 10-K "
            "presentado (página de error o contenido no esperado)."
        )

    form = _ix_non_numeric_value(html, "dei:DocumentType")
    if form is None:
        raise PrimaryDocumentError("No se pudo identificar dei:DocumentType en el documento.")
    if form != expected_form:
        raise PrimaryDocumentError(
            f"El documento es un {form} y se esperaba un {expected_form}."
        )

    expected_cik = f"{int(cik):010d}"
    entity_cik = _ix_non_numeric_value(html, "dei:EntityCentralIndexKey")
    if entity_cik is None:
        raise PrimaryDocumentError(
            "No se pudo identificar dei:EntityCentralIndexKey en el documento."
        )
    if entity_cik != expected_cik:
        raise PrimaryDocumentError(
            f"El documento pertenece al CIK {entity_cik} y se esperaba {expected_cik}."
        )

    fiscal_year_text = _ix_non_numeric_value(html, "dei:DocumentFiscalYearFocus")
    try:
        fiscal_year = int(fiscal_year_text) if fiscal_year_text else None
    except ValueError:
        fiscal_year = None
    if fiscal_year is None:
        raise PrimaryDocumentError(
            "No se pudo identificar dei:DocumentFiscalYearFocus en el documento."
        )
    if expected_fiscal_year is not None and fiscal_year != expected_fiscal_year:
        raise PrimaryDocumentError(
            f"El documento corresponde al ejercicio {fiscal_year} y se esperaba "
            f"el {expected_fiscal_year}."
        )

    return PrimaryDocument(
        raw=raw,
        fetch=fetch,
        document=document,
        url=url,
        accession=accession,
        cik=int(cik),
        form=form,
        fiscal_year=fiscal_year,
        fiscal_period=_ix_non_numeric_value(html, "dei:DocumentFiscalPeriodFocus"),
        entity_cik=entity_cik,
        entity_name=_ix_non_numeric_value(html, "dei:EntityRegistrantName"),
    )


def companyfacts_fact_value(
    payload: dict,
    *,
    concept: str = REVENUE_CONCEPT,
    period_start: date,
    period_end: date,
    unit: str = "USD",
    form: Optional[str] = "10-K",
) -> Optional[Decimal]:
    """Valor publicado por CompanyFacts para un periodo exacto, o None si no está.

    Solo se acepta el periodo pedido, sin redondeos ni periodo cercano. Si el mismo
    periodo aparece con valores distintos (reexpresiones) no se elige ninguno: se
    lanza `SecEdgarError` para que el contraste quede como no completado.
    """

    try:
        # CompanyFacts agrupa por taxonomía y nombre de concepto sin prefijo:
        # «us-gaap:Revenue…» y «Revenue…» apuntan al mismo hecho.
        concept_key = concept.split(":", 1)[1] if ":" in concept else concept
        entries = payload["facts"]["us-gaap"][concept_key]["units"][unit]
    except (KeyError, TypeError):
        return None

    matches = [
        entry
        for entry in entries
        if str(entry.get("start")) == period_start.isoformat()
        and str(entry.get("end")) == period_end.isoformat()
        and (form is None or entry.get("form") == form)
    ]
    if not matches:
        return None

    values = {Decimal(str(entry.get("val"))) for entry in matches}
    if len(values) > 1:
        raise SecEdgarError(
            f"CompanyFacts publica {len(values)} valores distintos para {concept} "
            f"{period_start.isoformat()}..{period_end.isoformat()}: no se elige ninguno."
        )
    return next(iter(values))
