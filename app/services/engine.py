"""Servicio del motor financiero: única puerta de entrada a los cálculos.

El frontend nunca recalcula nada: recibe cifras ya calculadas aquí. Este módulo
envuelve `nexo_invest` (SEC EDGAR, métricas, DCF, escenarios y sensibilidad) y
serializa el resultado a JSON estable para la API.

La descarga de SEC EDGAR exige un contacto identificable (condición de acceso de la
SEC). Sin `NEXO_SEC_CONTACT` el servicio no inventa datos: devuelve un error
explícito con la instrucción de configuración.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from nexo_invest.analysis import HEADLINE_METRICS, RealCompanyReport, build_real_report
from nexo_invest.core.dcf import DCFAssumptions, Scenario, build_valuation, sensitivity_table
from nexo_invest.core.metrics import FinancialMetrics
from nexo_invest.core.sources import Observation
from nexo_invest.core.units import Frequency, Money, Scale
from nexo_invest.data.sec_edgar import SecEdgarClient, SecEdgarResult, analyze_company

from app.config import Settings, load_settings


class EngineUnavailable(RuntimeError):
    """El motor no puede obtener datos (configuración o red)."""


class InvalidAssumption(ValueError):
    """Un supuesto de valoración está fuera del rango admitido."""


# Indicadores que la API expone con su procedencia. `kind` decide el formato:
# money -> valor en unidades de la moneda; percent -> fracción 0-1; ratio -> múltiplo.
METRIC_SPECS: Tuple[Tuple[str, str, str], ...] = (
    ("revenue", "Ingresos", "money"),
    ("revenue_growth", "Crecimiento de ingresos", "percent"),
    ("revenue_growth_fiscal", "Crecimiento fiscal de ingresos", "percent"),
    ("gross_margin", "Margen bruto", "percent"),
    ("operating_margin", "Margen operativo", "percent"),
    ("net_margin", "Margen neto", "percent"),
    ("ebitda_margin", "Margen EBITDA", "percent"),
    ("operating_income", "Resultado operativo", "money"),
    ("net_income", "Resultado neto", "money"),
    ("ebitda", "EBITDA", "money"),
    ("free_cash_flow", "Flujo de caja libre", "money"),
    ("operating_cash_flow", "Flujo de caja operativo", "money"),
    ("capital_expenditures", "Inversiones (capex)", "money"),
    ("total_debt", "Deuda total", "money"),
    ("cash_and_equivalents", "Caja y equivalentes", "money"),
    ("net_debt", "Deuda neta", "money"),
    ("invested_capital", "Capital invertido", "money"),
    ("return_on_invested_capital", "ROIC", "percent"),
    ("roic_nopat", "ROIC (NOPAT)", "percent"),
    ("current_ratio", "Ratio corriente", "ratio"),
    ("quick_ratio", "Prueba ácida", "ratio"),
    ("interest_coverage", "Cobertura de intereses", "ratio"),
    ("net_debt_to_ebitda", "Deuda neta / EBITDA", "ratio"),
    ("effective_tax_rate", "Tasa fiscal efectiva", "percent"),
    ("fcf_conversion_ocf", "Conversión de FCF sobre flujo operativo", "percent"),
    ("fcf_conversion_net_income", "Conversión de FCF sobre beneficio neto", "percent"),
    ("capex_to_revenue", "Capex sobre ingresos", "percent"),
    ("dilution_rate", "Dilución", "percent"),
    ("revenue_ttm", "Ingresos TTM", "money"),
)

SERIES_METRICS: Tuple[Tuple[str, str], ...] = (
    ("revenue", "Ingresos"),
    ("gross_profit", "Beneficio bruto"),
    ("operating_income", "Resultado operativo"),
    ("net_income", "Resultado neto"),
    ("operating_cash_flow", "Flujo de caja operativo"),
    ("total_debt", "Deuda total"),
    ("cash_and_equivalents", "Caja y equivalentes"),
    ("shareholders_equity", "Patrimonio neto"),
)


@dataclass
class AnalysisBundle:
    ticker: str
    payload: Dict[str, Any]
    report: RealCompanyReport
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _money_to_units(money: Optional[Money]) -> Optional[float]:
    if money is None or money.is_missing:
        return None
    try:
        return money.to_scale(Scale.UNITS).value
    except (ValueError, TypeError):
        return money.value


def _metric_value(metrics: FinancialMetrics, key: str) -> Optional[float]:
    raw = getattr(metrics, key, None)
    if raw is None:
        return None
    if isinstance(raw, Money):
        return _money_to_units(raw)
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _observation_for(report: RealCompanyReport, key: str) -> Optional[Observation]:
    try:
        return report.latest_observation(key)
    except Exception:  # pragma: no cover - una métrica inexistente no debe tumbar la API
        return None


def _metric_payload(report: RealCompanyReport) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for key, label, kind in METRIC_SPECS:
        value = _metric_value(report.metrics, key)
        observation = _observation_for(report, key)
        entries.append(
            {
                "key": key,
                "label": label,
                "kind": kind,
                "value": value,
                "currency": report.metrics.currency if kind == "money" else None,
                "period_end": (
                    observation.period.end.isoformat() if observation is not None else None
                ),
                "provenance": (
                    observation.effective_provenance_level.value
                    if observation is not None
                    else None
                ),
                "source_url": (
                    observation.source.url if observation is not None else None
                ),
                "unit": (
                    "currency"
                    if kind == "money"
                    else "fraction"
                    if kind == "percent"
                    else "multiple"
                ),
            }
        )
    return entries


def _series_payload(report: RealCompanyReport) -> Dict[str, Any]:
    series: Dict[str, Any] = {}
    labels: Dict[str, str] = {}
    for key, label in SERIES_METRICS:
        points: List[Dict[str, Any]] = []
        for obs in report.result.registry.observations_for_metric(key):
            if obs.period.frequency is not Frequency.ANNUAL:
                continue
            if obs.period.end > report.latest_end:
                continue
            value = _money_to_units(obs.value)
            if value is None:
                continue
            points.append(
                {
                    "period_end": obs.period.end.isoformat(),
                    "value": value,
                    "provenance": obs.effective_provenance_level.value,
                }
            )
        points.sort(key=lambda item: item["period_end"])
        series[key] = points
        labels[key] = label
    series["_labels"] = labels  # type: ignore[assignment]
    return series


def _scenario_payload(report: RealCompanyReport) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for result in report.scenarios:
        scenario = result.scenario
        output.append(
            {
                "name": scenario.name,
                "label": scenario.label,
                "growth_rates": list(scenario.revenue_growth_rates),
                "terminal_growth": scenario.terminal_growth,
                "discount_rate": scenario.discount_rate,
                "fcf_adjustment": scenario.base_fcf_scale_adjustment,
                "per_share_value": result.per_share_value,
                "enterprise_value": result.dcf.enterprise_value,
                "equity_value": result.dcf.equity_value,
                "terminal_value_pv": result.dcf.terminal_value_pv,
                "projected_years": [
                    {
                        "year": year.year_label,
                        "free_cash_flow": year.free_cash_flow,
                        "discount_factor": year.discount_factor,
                        "present_value": year.present_value,
                    }
                    for year in result.dcf.projected_years
                ],
                "notes": result.notes,
                "share_price": result.share_price,
                "upside": result.upside,
            }
        )
    return output


def _sensitivity_payload(
    report: RealCompanyReport, *, steps: int = 2
) -> Dict[str, Any]:
    base = next(
        (s for s in report.scenarios if "base" in s.scenario.name.lower()),
        report.scenarios[1] if len(report.scenarios) > 1 else None,
    )
    if base is None:
        return {"available": False, "reason": "sin escenario base"}
    assumptions: DCFAssumptions = base.dcf.assumptions
    growth_rates = list(base.scenario.revenue_growth_rates)
    if not growth_rates:
        return {"available": False, "reason": "sin tasas de crecimiento"}
    years = assumptions.forecast_years
    if len(growth_rates) < years:
        growth_rates = growth_rates + [growth_rates[-1]] * (years - len(growth_rates))
    rates = sorted({round(assumptions.discount_rate + 0.01 * i, 6) for i in range(-steps, steps + 1)})
    terminals = sorted(
        {
            round(assumptions.terminal_growth + 0.005 * i, 6)
            for i in range(-steps, steps + 1)
            if -1 < assumptions.terminal_growth + 0.005 * i < assumptions.discount_rate
        }
    )
    table = sensitivity_table(
        base.base_fcf,
        growth_rates[:years],
        assumptions,
        rates,
        terminals,
    )
    return {
        "available": True,
        "discount_rates": rates,
        "terminal_growths": terminals,
        "cells": [
            {
                "discount_rate": rate,
                "terminal_growth": terminal,
                "per_share_value": value,
            }
            for (rate, terminal), value in sorted(table.items())
        ],
        "base": {
            "discount_rate": assumptions.discount_rate,
            "terminal_growth": assumptions.terminal_growth,
            "per_share_value": base.per_share_value,
        },
    }


def _ledger_payload(report: RealCompanyReport) -> List[Dict[str, Any]]:
    """Cifras verificables que la IA puede citar, con su procedencia."""
    ledger: List[Dict[str, Any]] = []
    for key, label, kind in METRIC_SPECS:
        value = _metric_value(report.metrics, key)
        if value is None:
            continue
        observation = _observation_for(report, key)
        ledger.append(
            {
                "id": f"metric:{key}",
                "label": label,
                "value": value,
                "unit": "fraction" if kind == "percent" else kind,
                "period_end": (
                    observation.period.end.isoformat() if observation is not None else None
                ),
                "provenance": (
                    observation.effective_provenance_level.value
                    if observation is not None
                    else "calculated"
                ),
                "source_url": observation.source.url if observation is not None else None,
            }
        )
    for scenario in report.scenarios:
        if scenario.per_share_value is not None:
            ledger.append(
                {
                    "id": f"valuation:{scenario.scenario.name}",
                    "label": f"Valor por acción ({scenario.scenario.name})",
                    "value": scenario.per_share_value,
                    "unit": "currency",
                    "period_end": report.latest_end.isoformat(),
                    "provenance": "assumption_driven",
                    "source_url": None,
                }
            )
    return ledger


def serialize_bundle(report: RealCompanyReport, ticker: str) -> Dict[str, Any]:
    quality = report.quality_summary()
    shares = report.shares_outstanding
    return {
        "identity": {
            "ticker": ticker.upper(),
            "name": report.result.entity_name,
            "cik": report.result.cik,
            "currency": report.metrics.currency,
            "latest_period_end": report.latest_end.isoformat(),
            "fiscal_close_month": report.calendar.close_month,
            "generated_at": report.generated_at.isoformat(),
            "shares_outstanding": shares,
        },
        "provenance": {
            "source_url": report.result.source_url(),
            "content_sha256": report.result.content_sha256(),
            "quality_label": quality["label"],
            "counts": {
                "total": quality["total"],
                "validated": quality["validated"],
                "corroborated": quality["corroborated"],
                "downloaded_only": quality["downloaded_only"],
                "simulated": quality["simulated"],
            },
            "share_validated": quality["share_validated"],
            "statement": report.confidence_statement(),
            "missing_metrics": [
                {"key": key, "label": label} for key, label in report.missing_headline_metrics()
            ],
        },
        "metrics": _metric_payload(report),
        "series": _series_payload(report),
        "valuation": {
            "scenarios": _scenario_payload(report),
            "sensitivity": _sensitivity_payload(report),
            "notes": list(report.valuation_notes),
            "base_fcf": _money_to_units(report.metrics.free_cash_flow),
            "fcf_estimated": report.metrics.free_cash_flow_estimated,
        },
        "risks": {
            "invalidation_conditions": list(report.invalidation_conditions),
            "already_invalidated": list(report.invalidated),
        },
        "limitations": report.confidence_statement(),
        "ledger": _ledger_payload(report),
    }


def _default_loader(settings: Settings) -> Callable[[str], SecEdgarResult]:
    def load(ticker: str) -> SecEdgarResult:
        contact = settings.sec_contact
        if not contact:
            raise EngineUnavailable(
                "Falta NEXO_SEC_CONTACT: la SEC exige un contacto identificable en el "
                "User-Agent. Configúralo en el entorno del servidor para descargar datos."
            )
        client = SecEdgarClient(contact=contact, cache_dir=settings.sec_cache_dir)
        return analyze_company(client, ticker=ticker.upper(), max_annual_periods=8)

    return load


class EngineService:
    """Fachada con caché en memoria del último análisis por ticker."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        loader: Optional[Callable[[str], SecEdgarResult]] = None,
        *,
        cache_ttl: float = 900.0,
    ) -> None:
        self.settings = settings or load_settings()
        self.loader = loader or _default_loader(self.settings)
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, Tuple[float, AnalysisBundle]] = {}
        self._lock = threading.Lock()

    # -- acceso a datos ---------------------------------------------------------

    def analysis(
        self,
        ticker: str,
        *,
        refresh: bool = False,
        forecast_years: int = 5,
        share_price: Optional[float] = None,
    ) -> AnalysisBundle:
        key = f"{ticker.upper()}:{forecast_years}:{share_price}"
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached and not refresh and now - cached[0] < self.cache_ttl:
                return cached[1]
        result = self.loader(ticker)
        report = build_real_report(
            result,
            forecast_years=forecast_years,
            share_price=share_price,
        )
        bundle = AnalysisBundle(
            ticker=ticker.upper(),
            payload=serialize_bundle(report, ticker),
            report=report,
        )
        with self._lock:
            self._cache[key] = (time.monotonic(), bundle)
        return bundle

    def payload(self, ticker: str, *, refresh: bool = False) -> Dict[str, Any]:
        return self.analysis(ticker, refresh=refresh).payload

    def report_markdown(self, ticker: str) -> str:
        return self.analysis(ticker).report.markdown()

    def invalidate(self, ticker: Optional[str] = None) -> None:
        with self._lock:
            if ticker is None:
                self._cache.clear()
            else:
                for key in [k for k in self._cache if k.startswith(ticker.upper() + ":")]:
                    self._cache.pop(key, None)

    # -- valoración con supuestos propios ---------------------------------------

    def custom_valuation(
        self,
        ticker: str,
        *,
        forecast_years: int = 5,
        discount_rate: float = 0.085,
        terminal_growth: float = 0.025,
        growth_rate: float = 0.04,
        fcf_adjustment: float = 0.0,
        share_price: Optional[float] = None,
        sensitivity_steps: int = 2,
    ) -> Dict[str, Any]:
        if not 1 <= forecast_years <= 15:
            raise InvalidAssumption("forecast_years debe estar entre 1 y 15")
        if not 0.0 < discount_rate <= 0.40:
            raise InvalidAssumption("discount_rate debe estar entre 0 y 0.40")
        if not -0.05 <= terminal_growth < discount_rate:
            raise InvalidAssumption(
                "terminal_growth debe estar entre -0.05 y la tasa de descuento"
            )
        if not -0.50 <= growth_rate <= 0.50:
            raise InvalidAssumption("growth_rate debe estar entre -0.50 y 0.50")
        if not -0.90 <= fcf_adjustment <= 1.00:
            raise InvalidAssumption("fcf_adjustment debe estar entre -0.90 y 1.00")
        if share_price is not None and share_price <= 0:
            raise InvalidAssumption("share_price debe ser positivo")

        bundle = self.analysis(ticker, forecast_years=forecast_years)
        report = bundle.report
        base_fcf = report.metrics.free_cash_flow
        if base_fcf is None or base_fcf.is_missing:
            raise EngineUnavailable(
                "La empresa no reporta flujo de caja libre utilizable: no se puede valorar."
            )
        scenario = Scenario(
            name="usuario",
            label="supuestos proporcionados por el usuario",
            revenue_growth_rates=[growth_rate] * forecast_years,
            terminal_growth=terminal_growth,
            discount_rate=discount_rate,
            base_fcf_scale_adjustment=fcf_adjustment or None,
            notes={
                "crecimiento": "supuesto del usuario, no observado",
                "margen": (
                    f"ajuste explícito al FCF base: {fcf_adjustment:+.0%}"
                    if fcf_adjustment
                    else "sin ajuste de margen"
                ),
            },
        )
        results = build_valuation(
            company=report.metrics.company,
            base_fcf=base_fcf,
            forecast_years=forecast_years,
            share_price=share_price,
            shares_outstanding=report.shares_outstanding,
            scenarios=[scenario],
            comparables=None,
            net_debt=report.metrics.net_debt,
        )
        result = results[0]
        adjusted_fcf = result.base_fcf
        rates = sorted(
            {round(discount_rate + 0.01 * i, 6) for i in range(-sensitivity_steps, sensitivity_steps + 1)}
        )
        terminals = sorted(
            {
                round(terminal_growth + 0.005 * i, 6)
                for i in range(-sensitivity_steps, sensitivity_steps + 1)
                if -1 < terminal_growth + 0.005 * i < discount_rate
            }
        )
        table = sensitivity_table(
            result.base_fcf,
            [growth_rate] * forecast_years,
            result.dcf.assumptions,
            rates,
            terminals,
        )
        return {
            "ticker": ticker.upper(),
            "base_fcf": _money_to_units(adjusted_fcf),
            "fcf_estimated": report.metrics.free_cash_flow_estimated,
            "currency": base_fcf.currency,
            "shares_outstanding": report.shares_outstanding,
            "net_debt_included": report.metrics.net_debt is not None,
            "assumptions": {
                "forecast_years": forecast_years,
                "discount_rate": discount_rate,
                "terminal_growth": terminal_growth,
                "growth_rate": growth_rate,
                "fcf_adjustment": fcf_adjustment,
                "share_price": share_price,
            },
            "result": {
                "per_share_value": result.per_share_value,
                "enterprise_value": result.dcf.enterprise_value,
                "equity_value": result.dcf.equity_value,
                "terminal_value_pv": result.dcf.terminal_value_pv,
                "upside": result.upside,
                "projected_years": [
                    {
                        "year": year.year_label,
                        "free_cash_flow": year.free_cash_flow,
                        "discount_factor": year.discount_factor,
                        "present_value": year.present_value,
                    }
                    for year in result.dcf.projected_years
                ],
            },
            "sensitivity": {
                "discount_rates": rates,
                "terminal_growths": terminals,
                "cells": [
                    {
                        "discount_rate": rate,
                        "terminal_growth": terminal,
                        "per_share_value": value,
                    }
                    for (rate, terminal), value in sorted(table.items())
                ],
            },
            "notes": result.notes,
            "warning": (
                "Estimación matemática con supuestos declarados. No es precio objetivo ni "
                "recomendación de inversión."
            ),
        }

    # -- evidencias para el auditor ---------------------------------------------

    def evidence_ledger(self, ticker: str) -> List[Dict[str, Any]]:
        """Cifras verificables que la IA puede citar, con su procedencia."""
        return list(self.analysis(ticker).payload.get("ledger", []))


def metric_labels() -> Dict[str, str]:
    return {key: label for key, label, _ in HEADLINE_METRICS}


_default_service: Optional[EngineService] = None


def get_engine_service() -> EngineService:
    global _default_service
    if _default_service is None:
        _default_service = EngineService()
    return _default_service


def reset_engine_service() -> None:
    global _default_service
    _default_service = None


def ledger_dates(ledger: Sequence[Dict[str, Any]]) -> List[date]:
    dates: List[date] = []
    for entry in ledger:
        raw = entry.get("period_end")
        if raw:
            try:
                dates.append(datetime.fromisoformat(str(raw)).date())
            except ValueError:
                continue
    return dates
