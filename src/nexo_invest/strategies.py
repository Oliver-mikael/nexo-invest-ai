"""Dos estrategias de inversión, evaluadas por separado y sin promesas.

Estrategia A — valor e inversión contraria
    Se apoya en lo que los estados financieros presentados permiten comprobar:
    calidad del negocio (rentabilidad sobre capital, margen), generación de caja,
    endeudamiento y dilución. Los criterios son explícitos, con umbral y requisito de
    datos. Un criterio **no evaluable** (falta de dato) no cuenta como criterio
    incumplido: son cosas distintas y así se registran.

Estrategia B — táctica
    Requiere precios, volatilidad, liquidez y eventos. Este sistema **no tiene una
    fuente de precios verificada conectada**, así que no emite señales: declara qué
    datos necesita y queda en estado «no lista». Inventar una señal táctica sin series
    de precios sería fabricar el resultado.

Regla común: ninguna de las dos puede recomendar una compra mientras no exista un
precio de mercado verificado con el que calcular margen de seguridad. Por eso
`can_recommend` es siempre False y el informe final de cada empresa lo dice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from nexo_invest.core.metrics import FinancialMetrics

# Umbrales explícitos de la estrategia de valor. Documentados y configurables; no son
# óptimos calculados, son criterios de sentido común revisables.
VALUE_THRESHOLDS: Dict[str, float] = {
    "min_roic_nopat": 0.10,
    "min_gross_margin": 0.25,
    "min_revenue_growth": 0.00,
    "min_fcf_conversion_net_income": 0.70,
    "max_net_debt_to_ebitda": 2.5,
    "max_dilution_rate": 0.02,
}

# Datos que la estrategia táctica necesitaría y de los que el sistema carece hoy.
TACTICAL_REQUIRED_DATA = (
    "serie histórica de precios de cierre ajustados (dividendos y splits)",
    "volumen negociado y liquidez por sesión",
    "volatilidad realizada y rango de negociación",
    "calendario de eventos corporativos (resultados, dividendos, ampliaciones)",
    "reglas de entrada, salida y tamaño de posición con costes y deslizamiento",
)


@dataclass
class CriterionResult:
    key: str
    label: str
    requirement: str
    value: Optional[float]
    passed: Optional[bool]
    detail: str


@dataclass
class ValueScreenResult:
    company: str
    currency: str
    criteria: List[CriterionResult] = field(default_factory=list)
    excluded: List[str] = field(default_factory=list)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.criteria if c.passed is True)

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.criteria if c.passed is False)

    @property
    def not_evaluable_count(self) -> int:
        return sum(1 for c in self.criteria if c.passed is None)

    @property
    def status(self) -> str:
        """Estado de la candidatura, con criterios objetivos.

        - `descartado`: al menos dos criterios se incumplen con datos disponibles.
        - `insuficiente_datos`: falta información para evaluar parte de la tesis y no
          hay dos incumplimientos. No es una señal negativa.
        - `candidato_parcial`: se incumple exactamente un criterio.
        - `candidato_calidad`: todos los criterios se cumplen con datos disponibles.
        """
        if self.failed_count >= 2:
            return "descartado"
        if self.not_evaluable_count > 0:
            return "insuficiente_datos"
        if self.failed_count == 1:
            return "candidato_parcial"
        return "candidato_calidad"

    @property
    def can_recommend(self) -> bool:
        """Nunca True hoy: falta un precio de mercado verificado y una segunda fuente."""
        return False

    def markdown(self) -> str:
        lines: List[str] = []
        lines.append(f"### {self.company} — {self.status}")
        lines.append("")
        lines.append("| Criterio | Valor | Umbral | Resultado |")
        lines.append("| --- | --- | --- | --- |")
        for c in self.criteria:
            value = "no disponible" if c.value is None else self._format(c)
            outcome = (
                "cumple" if c.passed is True
                else "no cumple" if c.passed is False
                else "no evaluable"
            )
            lines.append(f"| {c.label} | {value} | {c.requirement} | {outcome} |")
        lines.append("")
        lines.append(
            f"Criterios cumplidos: {self.passed_count}; incumplidos: {self.failed_count}; "
            f"no evaluables por falta de datos: {self.not_evaluable_count}."
        )
        if self.excluded:
            lines.append("")
            lines.append("Motivos de descarte:")
            for reason in self.excluded:
                lines.append(f"- {reason}")
        lines.append("")
        if self.status == "insuficiente_datos":
            lines.append(
                "La falta de datos impide evaluar la tesis. Esto no es evidencia "
                "negativa sobre la empresa: es una limitación del análisis."
            )
        elif self.status == "descartado":
            lines.append(
                "No cumple los criterios objetivos de la estrategia de valor. Queda "
                "descartada como candidata de esta estrategia, no como empresa."
            )
        elif self.status == "candidato_parcial":
            lines.append(
                "Cumple casi todos los criterios: se incumple uno, que está listado "
                "arriba. No se recomienda su compra: falta el precio verificado."
            )
        else:
            lines.append(
                "Cumple todos los criterios evaluables, pero **no se recomienda su "
                "compra**: sin precio de mercado verificado no existe margen de "
                "seguridad calculable, y las cifras provienen de una sola fuente."
            )
        return "\n".join(lines)

    @staticmethod
    def _format(criterion: CriterionResult) -> str:
        value = criterion.value
        if value is None:
            return "no disponible"
        lowered = criterion.requirement.lower()
        if "x" in lowered and "%" not in lowered:
            return f"{value:.2f}x"
        return f"{value * 100:.1f} %" if abs(value) <= 5 else f"{value:,.0f}"


@dataclass
class TacticalReadiness:
    """Estado de la estrategia táctica: no lista, con la lista de lo que falta."""

    missing_data: Sequence[str] = TACTICAL_REQUIRED_DATA
    verified_price_source: bool = False

    @property
    def is_ready(self) -> bool:
        return self.verified_price_source

    def markdown(self) -> str:
        lines: List[str] = ["### Estrategia táctica — no lista", ""]
        lines.append(
            "No se emite ninguna señal táctica. Este sistema no tiene conectada una "
            "fuente de precios verificada y gratuita, así que no puede medir tendencia, "
            "volatilidad ni liquidez, ni fijar reglas de entrada y salida sobre datos reales."
        )
        lines.append("")
        lines.append("Datos necesarios para activarla:")
        for item in self.missing_data:
            lines.append(f"- {item}")
        lines.append("")
        lines.append(
            "Hasta entonces no se publican candidatos tácticos ni se afirma que una "
            "estrategia sea rentable: no hay serie de precios con la que comprobarlo."
        )
        return "\n".join(lines)


def _criterion(
    key: str,
    label: str,
    requirement: str,
    value: Optional[float],
    ok: Optional[Callable[[float], bool]],
) -> CriterionResult:
    if value is None:
        return CriterionResult(
            key=key,
            label=label,
            requirement=requirement,
            value=None,
            passed=None,
            detail="dato no disponible; no se evalúa y no cuenta como incumplimiento",
        )
    passed = ok(value) if ok is not None else None
    return CriterionResult(
        key=key,
        label=label,
        requirement=requirement,
        value=value,
        passed=passed,
        detail=("cumple" if passed else "no cumple") if passed is not None else "no evaluable",
    )


def screen_value_contrarian(
    metrics: FinancialMetrics,
    thresholds: Optional[Dict[str, float]] = None,
) -> ValueScreenResult:
    """Aplica los criterios de la estrategia de valor a unas métricas ya calculadas."""

    t = dict(VALUE_THRESHOLDS)
    if thresholds:
        t.update(thresholds)

    result = ValueScreenResult(company=metrics.company, currency=metrics.currency)
    result.criteria = [
        _criterion(
            "roic_nopat",
            "Rentabilidad sobre capital (NOPAT)",
            f"> {t['min_roic_nopat']:.0%}",
            metrics.roic_nopat,
            lambda v: v > t["min_roic_nopat"],
        ),
        _criterion(
            "gross_margin",
            "Márgen bruto",
            f"> {t['min_gross_margin']:.0%}",
            metrics.gross_margin,
            lambda v: v > t["min_gross_margin"],
        ),
        _criterion(
            "revenue_growth",
            "Crecimiento interanual de ingresos",
            f"> {t['min_revenue_growth']:.0%}",
            metrics.revenue_growth,
            lambda v: v > t["min_revenue_growth"],
        ),
        _criterion(
            "fcf_conversion_net_income",
            "Conversión de caja sobre beneficio",
            f"> {t['min_fcf_conversion_net_income']:.0%}",
            metrics.fcf_conversion_net_income,
            lambda v: v > t["min_fcf_conversion_net_income"],
        ),
        _criterion(
            "net_debt_to_ebitda",
            "Deuda neta / EBITDA",
            f"< {t['max_net_debt_to_ebitda']:.1f}x",
            metrics.net_debt_to_ebitda,
            lambda v: v < t["max_net_debt_to_ebitda"],
        ),
        _criterion(
            "dilution_rate",
            "Dilución de acciones",
            f"< {t['max_dilution_rate']:.0%}",
            metrics.dilution_rate,
            lambda v: v < t["max_dilution_rate"],
        ),
    ]

    result.excluded = [
        f"{c.label}: {c.detail} (valor {c.value if c.value is not None else 'no disponible'})"
        for c in result.criteria
        if c.passed is False
    ]
    if metrics.free_cash_flow is None:
        result.excluded.append("Sin flujo de caja libre utilizable: no hay base de valoración.")
    if metrics.free_cash_flow_estimated:
        result.excluded.append(
            "El flujo de caja libre usado es una estimación (flujo operativo - inversiones), "
            "no una cifra reportada por la empresa."
        )
    return result


def strategies_markdown(
    results: Sequence[ValueScreenResult],
    tactical: Optional[TacticalReadiness] = None,
    *,
    generated_at: str = "",
    notes: Optional[Sequence[str]] = None,
) -> str:
    """Informe de las dos estrategias, con su metodología y sin recomendaciones."""

    tactical = tactical or TacticalReadiness()
    lines: List[str] = []
    lines.append("# Nexo Invest AI — Estrategias de inversión")
    lines.append("")
    if generated_at:
        lines.append(f"**Generado:** {generated_at}")
        lines.append("")
    lines.append(
        "**Aviso:** este documento describe criterios y su resultado sobre datos "
        "financieros presentados. No contiene recomendaciones de compra o venta."
    )
    lines.append("")
    lines.append("## Estrategia A — valor e inversión contraria")
    lines.append("")
    lines.append("### Metodología de clasificación")
    lines.append("")
    lines.append(
        "Se aplican seis criterios objetivos a cada empresa. El orden de clasificación es: "
        "1) cumplen todos los criterios evaluables; 2) incumplen exactamente uno; 3) no se "
        "pueden evaluar por falta de datos; 4) descartadas por dos o más incumplimientos. "
        "Dentro de cada grupo se ordena por rentabilidad sobre capital (NOPAT) de mayor a "
        "menor. Los criterios incumplidos y los no evaluables se listan por separado, "
        "porque una cosa es que un dato contradiga la tesis y otra que simplemente falte."
    )
    lines.append("")
    order = {
        "candidato_calidad": 0,
        "candidato_parcial": 1,
        "insuficiente_datos": 2,
        "descartado": 3,
    }
    ordered = sorted(
        results,
        key=lambda r: (
            order.get(r.status, 3),
            -(r.criteria[0].value if r.criteria and r.criteria[0].value else 0.0),
        ),
    )
    for result in ordered:
        lines.append(result.markdown())
        lines.append("")
    lines.append("### Candidatos prioritarios")
    lines.append("")
    candidates = [r for r in ordered if r.status == "candidato_calidad"]
    partial = [r for r in ordered if r.status == "candidato_parcial"]
    if not candidates and not partial:
        lines.append(
            "Ninguno. Ninguna empresa cumple los criterios evaluables, así que no se "
            "propone ninguna candidata. Cuando no hay oportunidades suficientemente "
            "sustentadas, la respuesta correcta es no recomendar ninguna."
        )
    else:
        if candidates:
            lines.append(
                f"Cumplen todos los criterios evaluables ({len(candidates)}): "
                + ", ".join(r.company for r in candidates)
                + "."
            )
        if partial:
            lines.append("")
            lines.append(
                f"Incumplen un único criterio ({len(partial)}): "
                + ", ".join(
                    f"{r.company} ({r.excluded[0] if r.excluded else 'motivo no registrado'})"
                    for r in partial
                )
                + "."
            )
        lines.append("")
        lines.append(
            "**No se recomienda su compra.** Los criterios anteriores miden calidad y "
            "endeudamiento; no miden precio. Sin un precio de mercado verificado no existe "
            "margen de seguridad calculable, y una empresa de calidad comprada cara deja de "
            "ser una buena inversión. El máximo de dos candidatos del proyecto no se alcanza "
            "mientras falte esa comparación."
        )
    lines.append("")
    lines.append("## Estrategia B — táctica")
    lines.append("")
    lines.append(tactical.markdown())
    lines.append("")
    lines.append("## Limitaciones comunes")
    lines.append("")
    for note in (
        "Una sola fuente de datos (SEC EDGAR), con corroboración interna y sin segunda "
        "fuente independiente.",
        "Sin precios de mercado, sin comparables reales y sin series históricas: no hay "
        "margen de seguridad ni pruebas de rentabilidad.",
        "No se ha medido el rendimiento de ninguna de las dos estrategias. Ninguna "
        "afirmación sobre resultados futuros está respaldada.",
    ):
        lines.append(f"- {note}")
    for note in notes or ():
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)
