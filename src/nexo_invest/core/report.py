from __future__ import annotations

from datetime import datetime, date

from dataclasses import dataclass, field
from typing import List, Optional

from nexo_invest.core.dcf import DCFRun
from nexo_invest.core.metrics import FinancialMetrics
from nexo_invest.core.periods import FiscalCalendar
from nexo_invest.core.sources import ProvenanceRegistry


@dataclass
class ReportSection:
    title: str
    body: str


@dataclass
class AnalysisReport:
    company: str
    analysis_date: datetime
    metrics: FinancialMetrics
    valuation: Optional[DCFRun] = None
    thesis: str = ""
    evidence_for: List[str] = field(default_factory=list)
    evidence_against: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    key_assumptions: List[str] = field(default_factory=list)
    invalidation_conditions: List[str] = field(default_factory=list)
    data_quality: str = "unknown"
    conclusion: str = ""
    sources: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    sections: List[ReportSection] = field(default_factory=list)
    registry: Optional[ProvenanceRegistry] = None
    verified_facts: List[str] = field(default_factory=list)
    unverified_data: List[str] = field(default_factory=list)
    simulated_data: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    estimates: List[str] = field(default_factory=list)
    insufficient_data_notes: List[str] = field(default_factory=list)

    @classmethod
    def from_registry(
        cls,
        registry: ProvenanceRegistry,
        company: str,
        analysis_date: datetime,
        metrics: Optional[FinancialMetrics] = None,
        valuation: Optional[DCFRun] = None,
        fiscal_calendar: Optional[FiscalCalendar] = None,
        latest_end: Optional[date] = None,
    ) -> "AnalysisReport":
        if metrics is None:
            state = registry.to_financial_state()
            latest = registry.observations_for_metric("revenue")
            if latest:
                latest_end = max(obs.period.end for obs in latest)
            metrics = FinancialMetrics.from_state(state, latest_end or date.today(), fiscal_calendar=fiscal_calendar)
        data_quality = "unknown"
        if registry is not None:
            ql = registry.data_quality_label()
            if ql == "completa_verificada":
                data_quality = "completa (todos los datos verificados)"
            elif ql == "parcial":
                data_quality = "parcial (algunos datos no verificados)"
            elif ql == "no_verificada":
                data_quality = "no verificada"
            elif ql == "sin_datos":
                data_quality = "sin datos"
        return cls(
            company=company,
            analysis_date=analysis_date,
            metrics=metrics,
            valuation=valuation,
            registry=registry,
            data_quality=data_quality,
        )


    def markdown(self) -> str:
        lines: List[str] = []
        lines.append(f"# Informe de análisis: {self.company}")
        lines.append("")
        lines.append(f"**Fecha del análisis:** {self.analysis_date.isoformat()}")
        lines.append("")
        lines.append("## 1. Resumen de la empresa")
        lines.append("")
        lines.append(self.thesis or "_Sin tesis definida._")
        lines.append("")
        lines.append("## 2. Calidad y cobertura de los datos")
        lines.append("")
        lines.append(f"Cobertura: {self.data_quality}")
        lines.append("")
        if self.registry is not None:
            lines.append(self._provenance_block())
        elif self.metrics.notes:
            for k, v in self.metrics.notes.items():
                lines.append(f"- **{k}**: {v}")
        if self.insufficient_data_notes:
            lines.append("")
            lines.append("Datos insuficientes para evaluar:")
            for n in self.insufficient_data_notes:
                lines.append(f"- {n}")
        lines.append("")
        lines.append("## 3. Indicadores fundamentales")
        lines.append("")
        lines.append(self._metrics_block())
        lines.append("")
        if self.simulated_data:
            lines.append("## Datos simulados (no verificados)")
            lines.append("")
            for u in self.simulated_data:
                lines.append(f"- {u}")
            lines.append("")
        if self.unverified_data:
            lines.append("## Datos no verificados")
            lines.append("")
            for u in self.unverified_data:
                lines.append(f"- {u}")
            lines.append("")
        if self.verified_facts:
            lines.append("## Hechos verificados")
            lines.append("")
            for v in self.verified_facts:
                lines.append(f"- {v}")
            lines.append("")
        lines.append("## 4. Valoración y escenarios")
        lines.append("")
        lines.append(self._valuation_block())
        lines.append("")
        lines.append("## 5. Riesgos y argumentos contrarios")
        lines.append("")
        for r in self.risks:
            lines.append(f"- {r}")
        if self.evidence_for:
            lines.append("")
            lines.append("Evidencia a favor:")
            for e in self.evidence_for:
                lines.append(f"- {e}")
        if self.evidence_against:
            lines.append("Evidencia en contra:")
            for e in self.evidence_against:
                lines.append(f"- {e}")
            lines.append("")
        lines.append("## 6. Supuestos que más influyen")
        lines.append("")
        for a in self.key_assumptions:
            lines.append(f"- {a}")
        lines.append("")
        lines.append("## 7. Condiciones para reconsiderar la tesis")
        lines.append("")
        for c in self.invalidation_conditions:
            lines.append(f"- {c}")
        lines.append("")
        lines.append("## 8. Fuentes y limitaciones")
        lines.append("")
        lines.append("Fuentes:")
        for s in self.sources:
            lines.append(f"- {s}")
        lines.append("")
        lines.append("Limitaciones:")
        for limitation in self.limitations:
            lines.append(f"- {limitation}")
        lines.append("")
        lines.append("## 9. Conclusión")
        lines.append("")
        lines.append(self.conclusion)
        lines.append("")
        lines.append("---")
        lines.append("_ Este informe es una herramienta de análisis. No constituye")
        lines.append("  asesoramiento financiero personalizado ni garantía de rentabilidad.")
        return "\n".join(lines)

    def _metrics_block(self) -> str:
        m = self.metrics
        lines: List[str] = []
        lines.append(f"- Empresa: {m.company}")
        lines.append(f"- Moneda: {m.currency}")
        if m.latest_period:
            lines.append(
                f"- Periodo: {m.latest_period.start} a {m.latest_period.end} "
                f"({m.latest_period.frequency.value})"
            )
        if m.revenue:
            lines.append(f"- Ingresos: {m.revenue.value} {m.currency}")
        if m.revenue_ttm:
            lines.append(f"- Ingresos TTM: {m.revenue_ttm.value} {m.currency} ({m.revenue_ttm.scale.value})")
        else:
            lines.append("- Ingresos TTM: no disponibles (menos de 4 trimestres consecutivos o datos ausentes)")
        if m.revenue_growth is not None:
            lines.append(f"- Crecimiento interanual: {m.revenue_growth:.2%}")
        if m.gross_margin is not None:
            lines.append(f"- Márgen bruto: {m.gross_margin:.2%}")
        if m.operating_margin is not None:
            lines.append(f"- Márgen operativo: {m.operating_margin:.2%}")
        if m.net_margin is not None:
            lines.append(f"- Márgen neto: {m.net_margin:.2%}")
        if m.ebitda_margin is not None:
            lines.append(f"- Márgen EBITDA: {m.ebitda_margin:.2%}")
        if m.free_cash_flow:
            lines.append(f"- FCF: {m.free_cash_flow.value} {m.currency}")
        if m.net_debt:
            lines.append(f"- Deuda neta: {m.net_debt.value} {m.currency}")
        if m.return_on_invested_capital is not None:
            lines.append(f"- ROIC: {m.return_on_invested_capital:.2%}")
        if not lines:
            lines.append("- Sin datos suficientes para calcular indicadores.")
        if m.revenue is None and m.revenue_growth is None and not m.gross_margin and not m.operating_margin and not m.net_margin and not m.ebitda_margin:
            lines.append("- Datos insuficientes para evaluar: necesitan ingresos al menos durante 4 trimestres consecutivos.")
        if m.latest_period is None and m.revenue is None:
            lines.append("- Sin periodo fiscal de ingresos disponible; no se puede determinar la fecha del último reporte.")
        return "\n".join(lines)

    def _provenance_block(self) -> str:
        if self.registry is None:
            return "_Sin registro de procedencia._"
        lines: List[str] = []
        lines.append(self.registry.quality_report())
        if self.verified_facts:
            lines.append("Hechos verificados:")
            for f in self.verified_facts:
                lines.append(f"- {f}")
        if self.simulated_data:
            lines.append("Datos simulados:")
            for s in self.simulated_data:
                lines.append(f"- {s}")
        if self.unverified_data:
            lines.append("Datos no verificados:")
            for u in self.unverified_data:
                lines.append(f"- {u}")
        if self.assumptions:
            lines.append("Supuestos:")
            for a in self.assumptions:
                lines.append(f"- {a}")
        if self.estimates:
            lines.append("Estimaciones:")
            for e in self.estimates:
                lines.append(f"- {e}")
        if self.insufficient_data_notes:
            lines.append("Datos insuficientes para evaluar:")
            for n in self.insufficient_data_notes:
                lines.append(f"- {n}")
        return "\n".join(lines)

    def _valuation_block(self) -> str:
        if self.valuation is None:
            return "_Sin valoración calculada._"
        v = self.valuation
        lines: List[str] = []
        lines.append(f"- Horizonte: {v.assumptions.forecast_years} años")
        lines.append(f"- Tasa de descuento: {v.assumptions.discount_rate:.2%}")
        lines.append(f"- Crecimiento terminal: {v.assumptions.terminal_growth:.2%}")
        lines.append(f"- Valor terminal: {v.terminal_value:,.2f} {v.assumptions.currency}" if v.terminal_value is not None else "- Valor terminal: no calculado")
        lines.append(f"- Valor terminal (VP): {v.terminal_value_pv:,.2f} {v.assumptions.currency}" if v.terminal_value_pv is not None else "- Valor terminal (VP): no calculado")
        lines.append(f"- Valor de empresa: {v.enterprise_value:,.2f} {v.assumptions.currency}" if v.enterprise_value is not None else "- Valor de empresa: no calculado")
        lines.append(f"- Valor de equity: {v.equity_value:,.2f} {v.assumptions.currency}" if v.equity_value is not None else "- Valor de equity: no calculado")
        if v.per_share_value is not None:
            lines.append(f"- Valor por acción: {v.per_share_value:,.4f} {v.assumptions.currency}")
            if v.upside() is not None and v.assumptions.share_price:
                lines.append(f"- Upside vs precio actual: {v.upside():.2%}")
        else:
            lines.append("- Valor por acción: no calculable")
        if v.notes:
            lines.append("Notas de valoración:")
            for k, val in v.notes.items():
                lines.append(f"  - {k}: {val}")
        return "\n".join(lines)
