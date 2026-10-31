from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from nexo_invest.core.units import Money
from nexo_invest.core.sources import DataOrigin, VerificationState


@dataclass
class DCFAssumptions:
    currency: str
    forecast_years: int
    discount_rate: float
    terminal_growth: float
    shares_outstanding: Optional[float] = None
    share_price: Optional[float] = None
    net_debt: Optional[Money] = None
    notes: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.discount_rate <= 0:
            raise ValueError("discount_rate debe ser positivo")
        if self.terminal_growth < -1 or self.terminal_growth >= self.discount_rate:
            raise ValueError(
                "terminal_growth debe estar entre -1 y discount_rate (excluido)"
            )
        if self.forecast_years < 1:
            raise ValueError("forecast_years debe ser al menos 1")


@dataclass
class ProjectedYear:
    year_index: int
    year_label: str
    revenue: Optional[float] = None
    free_cash_flow: Optional[float] = None
    discount_factor: Optional[float] = None
    present_value: Optional[float] = None


@dataclass
class DCFRun:
    assumptions: DCFAssumptions
    projected_years: List[ProjectedYear] = field(default_factory=list)
    terminal_value: Optional[float] = None
    terminal_value_pv: Optional[float] = None
    enterprise_value: Optional[float] = None
    equity_value: Optional[float] = None
    per_share_value: Optional[float] = None
    notes: Dict[str, str] = field(default_factory=dict)

    def value_per_share(self) -> Optional[float]:
        return self.per_share_value

    def upside(self) -> Optional[float]:
        if self.per_share_value is None or self.assumptions.share_price in (None, 0.0):
            return None
        return self.per_share_value / self.assumptions.share_price - 1.0


def discount_factor(rate: float, year: int) -> float:
    """Factor de descuento para el año n (año 1 == primer año forecast)."""
    return 1.0 / (1.0 + rate) ** year


def run_dcf(
    base_fcf: Money,
    growth_rates: List[float],
    assumptions: DCFAssumptions,
) -> DCFRun:
    """Ejecuta un DCF reproducible.

    base_fcf: flujo de caja libre base sobre el que proyectar (Money).
    growth_rates: tasa de crecimiento para cada año del horizonte; si hay menos
        tasas que años, se usa la última para los restantes.
    """
    if base_fcf.is_missing or base_fcf.value is None:
        raise ValueError("FCF base necesaria para ejecutar el DCF")

    projected: List[ProjectedYear] = []
    remaining_fcf = base_fcf.value

    for i in range(assumptions.forecast_years):
        rate = growth_rates[i] if i < len(growth_rates) else growth_rates[-1]
        remaining_fcf = remaining_fcf * (1.0 + rate)
        df = discount_factor(assumptions.discount_rate, i + 1)
        pv = remaining_fcf * df
        projected.append(
            ProjectedYear(
                year_index=i,
                year_label=f"Year {i+1}",
                revenue=None,
                free_cash_flow=remaining_fcf,
                discount_factor=df,
                present_value=pv,
            )
        )

    # Valor terminal (Gordon growth) sobre el último FCF proyectado
    last_fcf = projected[-1].free_cash_flow
    if assumptions.terminal_growth >= 0:
        terminal_value = last_fcf * (1.0 + assumptions.terminal_growth) / (
            assumptions.discount_rate - assumptions.terminal_growth
        )
    else:
        terminal_value = last_fcf * (1.0 + assumptions.terminal_growth) / (
            assumptions.discount_rate - assumptions.terminal_growth
        )

    last_df = projected[-1].discount_factor
    terminal_value_pv = terminal_value * last_df

    enterprise_value = sum(p.present_value for p in projected) + terminal_value_pv
    net_debt_value = (
        assumptions.net_debt.value if assumptions.net_debt is not None else 0.0
    )
    equity_value = enterprise_value - net_debt_value

    per_share_value = None
    if assumptions.shares_outstanding and assumptions.shares_outstanding != 0:
        per_share_value = equity_value / assumptions.shares_outstanding

    run = DCFRun(
        assumptions=assumptions,
        projected_years=projected,
        terminal_value=terminal_value,
        terminal_value_pv=terminal_value_pv,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        per_share_value=per_share_value,
        notes={
            "base_fcf_scale": base_fcf.scale,
            "base_fcf_currency": base_fcf.currency,
            "net_debt_included": assumptions.net_debt is not None,
        },
    )
    return run



@dataclass
class Scenario:
    name: str
    label: str
    revenue_growth_rates: List[float]
    terminal_growth: float
    discount_rate: float
    base_fcf_scale_adjustment: Optional[float] = None
    notes: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.discount_rate <= self.terminal_growth:
            raise ValueError(
                f"[{self.name}] discount_rate ({self.discount_rate:.4f}) debe ser"
                f" superior a terminal_growth ({self.terminal_growth:.4f})"
            )
        if self.terminal_growth < -1:
            raise ValueError(
                f"[{self.name}] terminal_growth debe ser >= -1, recibido {self.terminal_growth}"
            )


@dataclass
class Comparable:
    company: str
    data_origin: DataOrigin
    verification_state: VerificationState
    price: Optional[Money] = None
    market_cap: Optional[Money] = None
    enterprise_value: Optional[Money] = None
    revenue: Optional[Money] = None
    ebitda: Optional[Money] = None
    net_income: Optional[Money] = None
    net_debt: Optional[Money] = None
    metrics: Dict[str, Optional[Money]] = field(default_factory=dict)
    notes: Dict[str, str] = field(default_factory=dict)
    provenance: Optional[str] = None

    def revenue_multiple(self) -> Optional[float]:
        if self.price is None or self.revenue is None or self.revenue.value == 0.0:
            return None
        if not same_scale(self.price, self.revenue):
            return None
        return self.price.value / self.revenue.value

    def ebitda_multiple(self) -> Optional[float]:
        if self.enterprise_value is None or self.ebitda is None or self.ebitda.value == 0.0:
            return None
        if not same_scale(self.enterprise_value, self.ebitda):
            return None
        return self.enterprise_value.value / self.ebitda.value

    def p_e(self) -> Optional[float]:
        if self.price is None or self.net_income is None or self.net_income.value == 0.0:
            return None
        if not same_scale(self.price, self.net_income):
            return None
        return self.price.value / self.net_income.value


def same_scale(a: Money, b: Money) -> bool:
    return a.scale is not None and b.scale is not None and a.scale is b.scale


def multiples_from_comparables(comps: List[Comparable]) -> Dict[str, Optional[float]]:
    rev = [c.revenue_multiple() for c in comps if c.revenue_multiple() is not None]
    ebitda = [c.ebitda_multiple() for c in comps if c.ebitda_multiple() is not None]
    pe = [c.p_e() for c in comps if c.p_e() is not None]
    def median(vals: List[float]) -> Optional[float]:
        if not vals:
            return None
        s = sorted(vals)
        n = len(s)
        if n % 2 == 1:
            return s[n // 2]
        mid = n // 2
        return (s[mid - 1] + s[mid]) / 2.0
    return {
        "revenue_multiple": median(rev),
        "ebitda_multiple": median(ebitda),
        "pe_multiple": median(pe),
    }


@dataclass
class ValuationResult:
    scenario: Scenario
    base_fcf: Money
    dcf: DCFRun
    comparable_multiples: Dict[str, Optional[float]]
    company: str
    currency: str
    share_price: Optional[float]
    shares_outstanding: Optional[float]
    per_share_value: Optional[float]
    upside: Optional[float]
    notes: Dict[str, str] = field(default_factory=dict)

    def markdown(self) -> str:
        lines: List[str] = []
        lines.append(f"### Escenario: {self.scenario.name} — {self.scenario.label}")
        lines.append("")
        lines.append(
            f"- **Crecimiento aplicado al flujo de caja libre:** {self._growth_summary()} "
            f"(durante {self.dcf.assumptions.forecast_years} años). El motor proyecta el "
            "flujo, no los ingresos: este porcentaje no es un crecimiento de ventas medido."
        )
        lines.append(f"- **Tasa de descuento:** {self.scenario.discount_rate:.2%}")
        lines.append(f"- **Crecimiento terminal:** {self.scenario.terminal_growth:.2%}")
        lines.append(f"- **Valor terminal (VP):** {self.dcf.terminal_value_pv:,.2f} {self.currency}" if self.dcf.terminal_value_pv is not None else "- **Valor terminal (VP):** no calculado")
        lines.append(f"- **Valor de empresa:** {self.dcf.enterprise_value:,.2f} {self.currency}" if self.dcf.enterprise_value is not None else "- **Valor de empresa:** no calculado")
        lines.append(f"- **Valor de equity:** {self.dcf.equity_value:,.2f} {self.currency}" if self.dcf.equity_value is not None else "- **Valor de equity:** no calculado")
        if self.per_share_value is not None:
            lines.append(f"- **Valor estimado por acción:** {self.per_share_value:,.4f} {self.currency}")
        else:
            lines.append("- **Valor estimado por acción:** no calculable (acciones pendientes o deuda neta desconocida)")
        if self.share_price is not None and self.per_share_value is not None:
            lines.append(f"- **Precio actual (verificado):** {self.share_price:,.2f} {self.currency}" if self.share_price is not None else "")
            if self.upside is not None:
                lines.append(f"- **Margen de subida/bajada:** {self.upside:+.2%}")
            else:
                lines.append("- **Margen de subida/bajada:** no calculable")
        if self.comparable_multiples:
            lines.append("")
            lines.append("**Múltiplos de comparables (mediana, simulados):**")
            for k, v in self.comparable_multiples.items():
                if v is not None:
                    lines.append(f"  - {k}: {v:.2f}x")
                else:
                    lines.append(f"  - {k}: no disponible")
        if self.notes:
            lines.append("")
            lines.append("Notas:")
            for k, v in self.notes.items():
                lines.append(f"  - {k}: {v}")
        return "\n".join(lines)

    def _growth_summary(self) -> str:
        if not self.scenario.revenue_growth_rates:
            return "ninguno"
        s = ", ".join(f"{g:.2%}" for g in self.scenario.revenue_growth_rates)
        return s


def build_valuation(
    company: str,
    base_fcf: Money,
    forecast_years: int,
    share_price: Optional[float],
    shares_outstanding: Optional[float],
    scenarios: List[Scenario],
    comparables: Optional[List[Comparable]] = None,
    net_debt: Optional[Money] = None,
) -> List[ValuationResult]:
    """Valora la empresa en cada escenario.

    `net_debt` es la deuda neta observada (deuda total - activos líquidos). Si no se
    conoce, el valor del patrimonio se presenta como igual al valor de empresa y la
    limitación queda registrada en las notas: no se asume deuda neta cero en silencio.
    """
    if base_fcf.is_missing or base_fcf.value is None:
        raise ValueError("FCF base necesaria para construir las valoraciones")
    results: List[ValuationResult] = []
    for scenario in scenarios:
        growth_rates = scenario.revenue_growth_rates
        if len(growth_rates) < forecast_years:
            growth_rates = growth_rates + [growth_rates[-1]] * (forecast_years - len(growth_rates))
        adj_fcf = base_fcf
        if scenario.base_fcf_scale_adjustment is not None:
            # ajuste documentado sobre el FCF base, no sobre la tasa de descuento
            adj_fcf = Money(
                base_fcf.value * (1.0 + scenario.base_fcf_scale_adjustment),
                base_fcf.currency,
                base_fcf.scale,
                label=f"fcf_ajustado_{scenario.name}",
            )
        assumptions = DCFAssumptions(
            currency=base_fcf.currency,
            forecast_years=forecast_years,
            discount_rate=scenario.discount_rate,
            terminal_growth=scenario.terminal_growth,
            shares_outstanding=shares_outstanding,
            share_price=share_price,
            net_debt=net_debt,
            notes={k: v for k, v in scenario.notes.items()},
        )
        dcf_run = run_dcf(adj_fcf, growth_rates[:forecast_years], assumptions)
        multiples = multiples_from_comparables(comparables or [])
        shares = dcf_run.assumptions.shares_outstanding
        per_share = dcf_run.per_share_value
        upside = None
        if per_share is not None and share_price is not None and share_price != 0.0:
            upside = per_share / share_price - 1.0
        r = ValuationResult(
            scenario=scenario,
            base_fcf=base_fcf,
            dcf=dcf_run,
            comparable_multiples=multiples,
            company=company,
            currency=base_fcf.currency,
            share_price=share_price,
            shares_outstanding=shares,
            per_share_value=per_share,
            upside=upside,
            notes={
                "base_fcf_scale": base_fcf.scale.value if base_fcf.scale else "desconocido",
                "base_fcf_currency": base_fcf.currency,
                "comparables_origen": (
                    "simulados" if (comparables and all(c.data_origin is DataOrigin.SIMULATED for c in comparables)) else
                    "desconocido" if not comparables else "mixto"
                ),
                "net_debt": (
                    "incluida en el calculo del valor de patrimonio"
                    if net_debt is not None
                    else "desconocida: valor de patrimonio = valor de empresa (no se asume cero)"
                ),
            },
        )
        results.append(r)
    return results




def sensitivity_table(
    base_fcf: Money,
    growth_rates: List[float],
    assumptions: DCFAssumptions,
    rate_range: List[float],
    terminal_range: List[float],
) -> Dict[Tuple[float, float], Optional[float]]:
    """Tabla de sensibilidad: par (tasa descuento, crecimiento terminal) -> valor por acción."""
    result: Dict[Tuple[float, float], Optional[float]] = {}
    for rate in rate_range:
        for tg in terminal_range:
            try:
                a = DCFAssumptions(
                    currency=assumptions.currency,
                    forecast_years=assumptions.forecast_years,
                    discount_rate=rate,
                    terminal_growth=tg,
                    shares_outstanding=assumptions.shares_outstanding,
                    share_price=assumptions.share_price,
                    net_debt=assumptions.net_debt,
                    notes=dict(assumptions.notes),
                )
                run = run_dcf(base_fcf, growth_rates, a)
                result[(rate, tg)] = run.per_share_value
            except ValueError:
                result[(rate, tg)] = None
    return result
