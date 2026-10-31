from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Dict, List, Optional

from nexo_invest.core.units import Money, Period, Scale

if TYPE_CHECKING:  # importación diferida: core.metrics importa este módulo en tiempo de ejecución
    from nexo_invest.core.metrics import FinancialState


class DataType(Enum):
    INCOME_STATEMENT = "income_statement"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    SHARE_COUNT = "share_count"
    SHARE_PRICE = "share_price"
    METRIC = "metric"


class DataOrigin(Enum):
    SIMULATED = "simulated"
    MANUAL = "manual"
    EXTERNAL_VERIFIED = "external_verified"
    EXTERNAL_UNVERIFIED = "external_unverified"


class VerificationState(Enum):
    UNVERIFIED = "unverified"
    PENDING = "pending"
    PARTIALLY_VERIFIED = "partially_verified"
    VERIFIED = "verified"


class ProvenanceLevel(Enum):
    """Nivel de respaldo real de un dato.

    Distingue explícitamente:
    - LOCAL_FIXTURE: dato de prueba usado en los tests. Nunca es un dato real.
    - SYNTHETIC: dato simulado para demostraciones.
    - MANUAL_INPUT: dato introducido a mano por una persona.
    - EXTERNAL_DOWNLOADED: descargado de una fuente externa y todavía no comprobado.
    - EXTERNAL_VALIDATED: descargado y con comprobaciones internas superadas
      (unidades, periodo fiscal, coherencia aritmética dentro de la misma fuente).
    - EXTERNAL_CORROBORATED: contrastado contra una segunda fuente independiente
      o contra el documento original.

    Una respuesta HTTP correcta solo autoriza EXTERNAL_DOWNLOADED. Subir de nivel
    exige evidencia registrada, no la mera existencia del dato.
    """

    LOCAL_FIXTURE = "local_fixture"
    SYNTHETIC = "synthetic"
    MANUAL_INPUT = "manual_input"
    EXTERNAL_DOWNLOADED = "external_downloaded"
    EXTERNAL_VALIDATED = "external_validated"
    EXTERNAL_CORROBORATED = "external_corroborated"

    @property
    def usable_as_real_data(self) -> bool:
        """True solo si el nivel procede de una fuente externa."""
        return self in {
            ProvenanceLevel.EXTERNAL_DOWNLOADED,
            ProvenanceLevel.EXTERNAL_VALIDATED,
            ProvenanceLevel.EXTERNAL_CORROBORATED,
        }


@dataclass
class DataSource:
    id: str
    name: str
    entity: str
    url: Optional[str] = None
    reference: Optional[str] = None
    data_type: DataType = DataType.INCOME_STATEMENT
    publication_date: Optional[date] = None
    retrieval_date: Optional[date] = None
    currency: Optional[str] = None
    scale: Optional[Scale] = None
    extraction_method: Optional[str] = None
    verification_state: VerificationState = VerificationState.UNVERIFIED
    origin: DataOrigin = DataOrigin.MANUAL
    notes: Optional[str] = None
    limitations: List[str] = field(default_factory=list)
    hash: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("DataSource.id requerido")
        if not self.entity:
            raise ValueError("DataSource.entity requerido")
        if not self.name:
            raise ValueError("DataSource.name requerido")

    @property
    def is_verified(self) -> bool:
        return self.verification_state is VerificationState.VERIFIED

    @property
    def is_external(self) -> bool:
        return self.origin is DataOrigin.EXTERNAL_VERIFIED or self.origin is DataOrigin.EXTERNAL_UNVERIFIED

    @property
    def is_simulated(self) -> bool:
        return self.origin is DataOrigin.SIMULATED

    @property
    def is_manual(self) -> bool:
        return self.origin is DataOrigin.MANUAL


@dataclass
class Observation:
    source: DataSource
    period: Period
    metric: str
    value: Optional[Money] = None
    value_origin: DataOrigin = DataOrigin.MANUAL
    verified: bool = False
    raw_value: Optional[str] = None
    notes: Optional[str] = None
    limitations: List[str] = field(default_factory=list)
    provenance_level: Optional[ProvenanceLevel] = None

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("Observation.source requerido")
        if not self.metric:
            raise ValueError("Observation.metric requerido")

    @property
    def effective_provenance_level(self) -> ProvenanceLevel:
        """Nivel de procedencia efectivo.

        Si no se declara explícitamente, se deriva del origen del valor sin
        sobrevalorarlo: un dato simulado nunca sube de SYNTHETIC, y un dato
        manual nunca se presenta como externo.
        """
        if self.provenance_level is not None:
            return self.provenance_level
        if self.value_origin is DataOrigin.SIMULATED:
            return ProvenanceLevel.SYNTHETIC
        if self.value_origin is DataOrigin.MANUAL:
            return ProvenanceLevel.MANUAL_INPUT
        if self.value_origin is DataOrigin.EXTERNAL_VERIFIED:
            return ProvenanceLevel.EXTERNAL_VALIDATED
        return ProvenanceLevel.EXTERNAL_DOWNLOADED

    @property
    def is_verified(self) -> bool:
        if self.verified is False:
            return False
        if self.source is None or self.source.verification_state is not VerificationState.VERIFIED:
            return False
        if self.value is None or self.value.is_missing:
            return False
        return True

    @property
    def is_simulated(self) -> bool:
        return self.value_origin is DataOrigin.SIMULATED

    @property
    def is_external(self) -> bool:
        return self.value_origin is DataOrigin.EXTERNAL_VERIFIED or self.value_origin is DataOrigin.EXTERNAL_UNVERIFIED or self.value_origin is DataOrigin.EXTERNAL_UNVERIFIED

    @property
    def is_manual(self) -> bool:
        return self.value_origin is DataOrigin.MANUAL

    @property
    def is_missing(self) -> bool:
        if self.value is None:
            return True
        if self.value.is_missing:
            return True
        return False


@dataclass
class ProvenanceRegistry:
    sources: Dict[str, DataSource] = field(default_factory=dict)
    observations: Dict[str, Observation] = field(default_factory=dict)

    def register_source(self, source: DataSource) -> None:
        if source.id in self.sources:
            raise ValueError(f"Fuente duplicada: {source.id}")
        self.sources[source.id] = source

    def register_observation(self, obs: Observation) -> None:
        """Registra una observación.

        La clave incluye fuente, métrica, inicio, fin y frecuencia. Incluir inicio y
        frecuencia es necesario porque un periodo anual y otro trimestral pueden
        terminar el mismo día (por ejemplo, un cierre fiscal de septiembre con su
        cuarto trimestre). Sin esto, datos reales distintos colisionaban.
        """

        key = (
            f"{obs.source.id}::{obs.metric}::"
            f"{obs.period.start.isoformat()}::{obs.period.end.isoformat()}::"
            f"{obs.period.frequency.value}"
        )
        if key in self.observations:
            raise ValueError(f"Observación duplicada: {key}")
        self.observations[key] = obs

    def observation(
        self,
        source_id: str,
        metric: str,
        period: Period,
        value: Optional[Money] = None,
        value_origin: DataOrigin = DataOrigin.MANUAL,
        verified: bool = False,
        notes: Optional[str] = None,
        limitations: Optional[List[str]] = None,
        provenance_level: Optional[ProvenanceLevel] = None,
    ) -> Observation:
        source = self.sources.get(source_id)
        if source is None:
            raise KeyError(f"Fuente no registrada: {source_id}")
        obs = Observation(
            source=source,
            period=period,
            metric=metric,
            value=value,
            value_origin=value_origin,
            verified=verified,
            notes=notes,
            limitations=limitations or [],
            provenance_level=provenance_level,
        )
        self.register_observation(obs)
        return obs

    def observation_for_metric_period(self, metric: str, period_end: date) -> Optional[Observation]:
        for obs in self.observations.values():
            if obs.metric == metric and obs.period.end == period_end:
                return obs
        return None


    def observations_for_metric(self, metric: str) -> List[Observation]:
        result: List[Observation] = []
        for obs in self.observations.values():
            if obs.metric == metric:
                result.append(obs)
        return result

    _BALANCE_FIELDS: ClassVar[set[str]] = {
        "total_debt", "cash_and_equivalents", "invested_capital", "total_assets",
        "total_liabilities", "total_equity", "shareholders_equity", "working_capital",
        "current_assets", "current_liabilities", "inventory", "short_term_investments",
        "long_term_debt_current", "long_term_debt_noncurrent", "short_term_borrowings",
    }
    _CASHFLOW_FIELDS: ClassVar[set[str]] = {
        "free_cash_flow", "operating_cash_flow", "capital_expenditures",
        "dividends_paid", "share_repurchases",
    }
    _INCOME_FIELDS: ClassVar[set[str]] = {
        "revenue", "gross_profit", "operating_income", "net_income", "ebitda",
        "interest_expense", "income_tax_expense", "income_before_tax",
        "depreciation_amortization", "shares_diluted",
    }
    # Mapeo métrica -> campo de IncomeStatement cuando el nombre no coincide.
    _INCOME_ALIASES: ClassVar[Dict[str, str]] = {"income_tax_expense": "tax_provision"}

    def to_financial_state(
        self,
        metrics: Optional[List[str]] = None,
        metric: Optional[str] = None,
    ) -> "FinancialState":
        """Construye un FinancialState desde las observaciones registradas.

        Incluye ingresos, balance y flujo de caja. Los campos ausentes quedan en
        None (no se inventan). El parámetro `metric` se mantiene por compatibilidad
        con llamadas anteriores y equivale a `metrics=[metric]`.
        """
        if metric is not None:
            metrics = [metric]
        # metrics is None significa: incluir todas las métricas registradas.
        from nexo_invest.core.metrics import FinancialState, IncomeStatement, BalanceSheet, CashFlow
        if not self.sources:
            return FinancialState(company="", currency="USD")
        entity = next(iter(self.sources.values())).entity
        currency = next(iter(self.sources.values())).currency or "USD"
        state = FinancialState(company=entity, currency=currency)
        # income statements
        def _included(name: str) -> bool:
            return metrics is None or name in metrics

        income_map: Dict[Period, Dict[str, Optional[Money]]] = {}
        for obs in self.observations.values():
            if _included(obs.metric) and obs.metric in self._INCOME_FIELDS:
                income_map.setdefault(obs.period, {})[obs.metric] = obs.value
        for period, fields in income_map.items():
            stmt = IncomeStatement(period=period, revenue=fields.get("revenue"))
            for field_name, value in fields.items():
                attribute = self._INCOME_ALIASES.get(field_name, field_name)
                if hasattr(stmt, attribute):
                    setattr(stmt, attribute, value)
            state.add_income_statement(stmt)
        # balance sheet aggregation por periodo
        balance_map: Dict[date, Dict[str, Optional[Money]]] = {}
        for obs in self.observations.values():
            if _included(obs.metric) and obs.metric in self._BALANCE_FIELDS:
                per = obs.period
                if per not in balance_map:
                    balance_map[per] = {}
                balance_map[per][obs.metric] = obs.value
        for per, fields in balance_map.items():
            bs = BalanceSheet(period=per)
            if "total_debt" in fields:
                bs.total_debt = fields["total_debt"]
            if "cash_and_equivalents" in fields:
                bs.cash_and_equivalents = fields["cash_and_equivalents"]
            if "invested_capital" in fields:
                bs.invested_capital = fields["invested_capital"]
            if "total_assets" in fields:
                bs.total_assets = fields["total_assets"]
            if "total_liabilities" in fields:
                bs.total_liabilities = fields["total_liabilities"]
            if "total_equity" in fields:
                bs.total_equity = fields["total_equity"]
            if "shareholders_equity" in fields:
                bs.shareholders_equity = fields["shareholders_equity"]
            if "working_capital" in fields:
                bs.working_capital = fields["working_capital"]
            if "current_assets" in fields:
                bs.current_assets = fields["current_assets"]
            if "current_liabilities" in fields:
                bs.current_liabilities = fields["current_liabilities"]
            if "inventory" in fields:
                bs.inventory = fields["inventory"]
            # Componentes de deuda y activos líquidos: se copian tal como se
            # observaron. La suma a deuda total la hace FinancialMetrics, que además
            # deja constancia de si faltaba algún componente.
            for name in (
                "short_term_investments",
                "long_term_debt_current",
                "long_term_debt_noncurrent",
                "short_term_borrowings",
            ):
                if name in fields:
                    setattr(bs, name, fields[name])
            state.add_balance_sheet(bs)
        # cash flow aggregation por periodo
        cf_map: Dict[date, Dict[str, Optional[Money]]] = {}
        for obs in self.observations.values():
            if _included(obs.metric) and obs.metric in self._CASHFLOW_FIELDS:
                per = obs.period
                if per not in cf_map:
                    cf_map[per] = {}
                cf_map[per][obs.metric] = obs.value
        for per, fields in cf_map.items():
            cf = CashFlow(period=per)
            if "free_cash_flow" in fields:
                cf.free_cash_flow = fields["free_cash_flow"]
            if "operating_cash_flow" in fields:
                cf.operating_cash_flow = fields["operating_cash_flow"]
            if "capital_expenditures" in fields:
                cf.capital_expenditures = fields["capital_expenditures"]
            if "dividends_paid" in fields:
                cf.dividends_paid = fields["dividends_paid"]
            if "share_repurchases" in fields:
                cf.share_repurchases = fields["share_repurchases"]
            state.add_cash_flow(cf)
        return state

    def quality_report(self) -> str:
        lines: List[str] = []
        n_obs = len(self.observations)
        n_sources = len(self.sources)

        n_verified = 0
        n_simulated = 0
        n_manual = 0
        n_external = 0
        n_unverified = 0
        n_missing = 0

        for obs in self.observations.values():
            if obs.is_verified:
                n_verified += 1
            elif obs.is_simulated:
                n_simulated += 1
            elif obs.is_manual:
                n_manual += 1
            elif obs.is_external:
                n_external += 1
            else:
                n_unverified += 1
            if obs.is_missing:
                n_missing += 1

        lines.append("Estado de procedencia:")
        lines.append(f"  Observaciones totales: {n_obs}")
        lines.append(f"  Observaciones verificadas: {n_verified}")
        lines.append(f"  Observaciones simuladas: {n_simulated}")
        lines.append(f"  Observaciones manuales: {n_manual}")
        lines.append(f"  Observaciones externas: {n_external}")
        lines.append(f"  Observaciones sin clasificar: {n_unverified}")
        lines.append(f"  Datos ausentes: {n_missing}")
        lines.append(f"  Fuentes totales: {n_sources}")
        lines.append("  Nivel de procedencia (efectivo):")
        for level in ProvenanceLevel:
            n = sum(
                1 for o in self.observations.values()
                if o.effective_provenance_level is level
            )
            if n:
                lines.append(f"    {level.value}: {n}")
        if n_obs == 0:
            lines.append("  Sin datos registrados.")
        return "\n".join(lines)

    def data_quality_label(self) -> str:
        n_obs = len(self.observations)
        if n_obs == 0:
            return "sin_datos"
        verified = sum(1 for obs in self.observations.values() if obs.is_verified)
        if verified == n_obs:
            return "completa_verificada"
        if verified == 0:
            return "no_verificada"
        return "parcial"

    def level_counts(self) -> Dict[str, int]:
        """Recuento de observaciones por nivel de procedencia efectivo."""
        counts: Dict[str, int] = {level.value: 0 for level in ProvenanceLevel}
        for obs in self.observations.values():
            counts[obs.effective_provenance_level.value] += 1
        return counts

    def real_data_observations(self) -> List[Observation]:
        """Observaciones cuyo nivel procede de una fuente externa."""
        return [
            obs
            for obs in self.observations.values()
            if obs.effective_provenance_level.usable_as_real_data
        ]



