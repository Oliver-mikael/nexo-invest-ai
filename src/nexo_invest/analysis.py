"""Informe reproducible de una empresa real obtenida de SEC EDGAR.

Este módulo es la pieza que une las capas anteriores:

    SEC EDGAR (descarga) -> ProvenanceRegistry (procedencia) -> FinancialState
    -> FinancialMetrics (indicadores) -> escenarios DCF -> informe Markdown

Principio de diseño: el informe nunca mezcla categorías. Cada cifra se presenta en
la sección que le corresponde según su procedencia real:

- hecho con fuente: observación con periodo y documento identificables;
- dato descargado sin validar: la descarga funcionó, la cifra no superó las
  comprobaciones internas (o no se intentó);
- estimación: derivada de hechos observados mediante una fórmula declarada;
- supuesto: valor elegido por el analista para la valoración, sin respaldo empírico;
- dato simulado: fixture de pruebas, nunca presentado como información real;
- información ausente: no se calcula, no se rellena con cero.

Sin precio de mercado verificado no se calcula margen de subida ni se emite
recomendación de compra o venta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple

from nexo_invest.core.dcf import Scenario, build_valuation
from nexo_invest.core.metrics import FinancialMetrics
from nexo_invest.core.periods import FiscalCalendar
from nexo_invest.core.sources import Observation, ProvenanceLevel
from nexo_invest.core.units import Frequency, Money
from nexo_invest.data.sec_edgar import SecEdgarResult, fiscal_calendar_for

# Métricas que el informe muestra con su periodo y su documento de origen.
HEADLINE_METRICS: Tuple[Tuple[str, str], ...] = (
    ("revenue", "Ingresos"),
    ("gross_profit", "Beneficio bruto"),
    ("operating_income", "Resultado operativo"),
    ("net_income", "Resultado neto"),
    ("income_before_tax", "Resultado antes de impuestos"),
    ("income_tax_expense", "Impuesto sobre beneficios"),
    ("interest_expense", "Gasto financiero"),
    ("depreciation_amortization", "Amortizaciones"),
    ("operating_cash_flow", "Flujo de caja operativo"),
    ("capital_expenditures", "Inversiones (capex)"),
    ("dividends_paid", "Dividendos pagados"),
    ("share_repurchases", "Recompras de acciones"),
    ("cash_and_equivalents", "Caja y equivalentes"),
    ("short_term_investments", "Inversiones a corto plazo"),
    ("total_assets", "Activo total"),
    ("total_liabilities", "Pasivo total"),
    ("shareholders_equity", "Patrimonio neto"),
    ("current_assets", "Activo corriente"),
    ("current_liabilities", "Pasivo corriente"),
    ("inventory", "Inventario"),
    ("long_term_debt_current", "Deuda a largo plazo corriente"),
    ("long_term_debt_noncurrent", "Deuda a largo plazo no corriente"),
    ("short_term_borrowings", "Financiación a corto plazo"),
    ("shares_diluted", "Acciones diluidas medias"),
)

# Umbrales explícitos de las condiciones que invalidarían una tesis de calidad.
# No son predicciones: son criterios objetivos y comprobables en el próximo informe.
DEFAULT_INVALIDATION_THRESHOLDS: Dict[str, float] = {
    "min_gross_margin": 0.30,
    "min_fcf_conversion_net_income": 0.70,
    "max_net_debt_to_ebitda": 2.5,
}

SCENARIO_DEFINITIONS: Tuple[Dict[str, object], ...] = (
    {
        "name": "bajista",
        "label": "crecimiento bajo, presion en margenes y descuento alto",
        "growth": 0.01,
        "discount": 0.105,
        "terminal": 0.015,
        "fcf_adjustment": -0.20,
    },
    {
        "name": "base",
        "label": "crecimiento moderado y margenes estables",
        "growth": 0.04,
        "discount": 0.085,
        "terminal": 0.025,
        "fcf_adjustment": 0.0,
    },
    {
        "name": "alcista",
        "label": "crecimiento alto sostenido y mejora de margen",
        "growth": 0.07,
        "discount": 0.075,
        "terminal": 0.030,
        "fcf_adjustment": 0.10,
    },
)


def _fmt_money(money: Optional[Money]) -> str:
    if money is None or money.value is None:
        return "no disponible"
    value = money.value
    if abs(value) >= 1e9:
        return f"{value / 1e9:,.1f} mil millones {money.currency}"
    if abs(value) >= 1e6:
        return f"{value / 1e6:,.1f} millones {money.currency}"
    return f"{value:,.0f} {money.currency}"


def _fmt_pct(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "no calculable"
    return f"{value * 100:.{digits}f} %"


def _fmt_ratio(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "no calculable"
    return f"{value:.{digits}f}"


def _fmt_multiple(value: Optional[float], digits: int = 2) -> str:
    """Múltiplo con sufijo x, o «no calculable» sin sufijo cuando no hay valor."""
    if value is None:
        return "no calculable"
    return f"{value:.{digits}f}x"


@dataclass
class RealCompanyReport:
    """Informe de una empresa real, con su procedencia y sus limitaciones."""

    result: SecEdgarResult
    metrics: FinancialMetrics
    calendar: FiscalCalendar
    generated_at: datetime
    latest_end: date
    invalidated: List[str] = field(default_factory=list)
    invalidation_conditions: List[str] = field(default_factory=list)
    scenarios: List[object] = field(default_factory=list)
    valuation_notes: List[str] = field(default_factory=list)
    shares_outstanding: Optional[float] = None

    # -- selección de observaciones -------------------------------------------------

    def latest_observation(self, metric: str) -> Optional[Observation]:
        """Observación más reciente de la métrica, prefiriendo el cierre anual."""
        observations = [
            obs
            for obs in self.result.registry.observations_for_metric(metric)
            if obs.period.end <= self.latest_end
        ]
        if not observations:
            return None
        annual = [o for o in observations if o.period.frequency is Frequency.ANNUAL]
        pool = annual or observations
        return max(pool, key=lambda o: o.period.end)

    def observations_by_level(self, level: ProvenanceLevel) -> List[Observation]:
        return [
            obs
            for obs in self.result.registry.observations.values()
            if obs.effective_provenance_level is level
        ]

    def missing_headline_metrics(self) -> List[Tuple[str, str]]:
        return [
            (metric, label)
            for metric, label in HEADLINE_METRICS
            if self.latest_observation(metric) is None
        ]

    # -- valoración -----------------------------------------------------------------

    def run_scenarios(
        self, forecast_years: int = 5, share_price: Optional[float] = None
    ) -> List[object]:
        """Construye los escenarios bajista/base/alcista.

        El FCF base es la cifra observada si la empresa la reporta, o la estimación
        declarada (flujo operativo - inversiones). El ajuste por escenario aplica al
        flujo, de modo que el efecto de márgenes es explícito y no queda escondido en
        la tasa de descuento.
        """
        base_fcf = self.metrics.free_cash_flow
        if base_fcf is None or base_fcf.is_missing:
            self.valuation_notes.append(
                "Sin flujo de caja libre (ni reportado ni estimable): no se valora por DCF."
            )
            return []
        if self.metrics.net_debt is None:
            self.valuation_notes.append(
                "Deuda neta desconocida: el valor de patrimonio se presenta igual al valor "
                "de empresa. No se asume deuda cero en silencio."
            )
        scenarios: List[Scenario] = []
        for definition in SCENARIO_DEFINITIONS:
            scenarios.append(
                Scenario(
                    name=str(definition["name"]),
                    label=str(definition["label"]),
                    revenue_growth_rates=[float(definition["growth"])] * forecast_years,
                    terminal_growth=float(definition["terminal"]),
                    discount_rate=float(definition["discount"]),
                    base_fcf_scale_adjustment=float(definition["fcf_adjustment"]),
                    notes={
                        "crecimiento": "supuesto del analista, no observado",
                        "margen": (
                            "efecto de margen aplicado como ajuste explicito al FCF base: "
                            f"{float(definition['fcf_adjustment']):+.0%}"
                        ),
                    },
                )
            )
        results = build_valuation(
            company=self.metrics.company,
            base_fcf=base_fcf,
            forecast_years=forecast_years,
            share_price=share_price,
            shares_outstanding=self.shares_outstanding,
            scenarios=scenarios,
            comparables=None,
            net_debt=self.metrics.net_debt,
        )
        self.scenarios = results
        return results

    # -- condiciones objetivas ------------------------------------------------------

    def build_invalidation_rules(
        self, thresholds: Optional[Dict[str, float]] = None
    ) -> None:
        """Define condiciones objetivas que invalidarían una tesis de calidad.

        Se evalúan aquí y ahora: si ya se cumplen, se registran como incumplidas
        (no como riesgo futuro). Ninguna de estas condiciones es una recomendación.
        """
        t = dict(DEFAULT_INVALIDATION_THRESHOLDS)
        if thresholds:
            t.update(thresholds)
        m = self.metrics
        rules: List[str] = []

        rules.append(
            f"Márgen bruto por debajo de {t['min_gross_margin']:.0%} durante dos "
            f"ejercicios consecutivos (actual: {_fmt_pct(m.gross_margin)})."
        )
        rules.append(
            "Conversión de FCF sobre resultado neto por debajo de "
            f"{t['min_fcf_conversion_net_income']:.0%} en dos ejercicios consecutivos "
            f"(actual: {_fmt_pct(m.fcf_conversion_net_income)})."
        )
        rules.append(
            "Deuda neta / EBITDA por encima de "
            f"{t['max_net_debt_to_ebitda']:.1f}x (actual: "
            f"{_fmt_ratio(m.net_debt_to_ebitda)}x)."
        )
        rules.append(
            "Incumplimiento de la identidad contable Activo = Pasivo + Patrimonio en "
            "el cierre más reciente, o cambio de fuente sin registrar la nueva."
        )
        rules.append(
            "Desaparición o corrección retroactiva del documento de origen "
            "(nuevo accession number para el mismo periodo sin nota de reexpresión)."
        )
        self.invalidation_conditions = rules

        if m.gross_margin is not None and m.gross_margin < t["min_gross_margin"]:
            self.invalidated.append(
                f"margen bruto {_fmt_pct(m.gross_margin)} < {t['min_gross_margin']:.0%}"
            )
        if (
            m.fcf_conversion_net_income is not None
            and m.fcf_conversion_net_income < t["min_fcf_conversion_net_income"]
        ):
            self.invalidated.append(
                "conversión de FCF sobre beneficio neto "
                f"{_fmt_pct(m.fcf_conversion_net_income)} < "
                f"{t['min_fcf_conversion_net_income']:.0%}"
            )
        if (
            m.net_debt_to_ebitda is not None
            and m.net_debt_to_ebitda > t["max_net_debt_to_ebitda"]
        ):
            self.invalidated.append(
                f"deuda neta/EBITDA {_fmt_ratio(m.net_debt_to_ebitda)}x > "
                f"{t['max_net_debt_to_ebitda']:.1f}x"
            )

    # -- calidad de datos -----------------------------------------------------------

    def quality_summary(self) -> Dict[str, object]:
        registry = self.result.registry
        counts = registry.level_counts()
        total = len(registry.observations)
        validated = counts.get(ProvenanceLevel.EXTERNAL_VALIDATED.value, 0)
        corroborated = counts.get(ProvenanceLevel.EXTERNAL_CORROBORATED.value, 0)
        downloaded = counts.get(ProvenanceLevel.EXTERNAL_DOWNLOADED.value, 0)
        simulated = counts.get(ProvenanceLevel.SYNTHETIC.value, 0) + counts.get(
            ProvenanceLevel.LOCAL_FIXTURE.value, 0
        )
        usable = validated + corroborated
        share = (usable / total) if total else 0.0
        return {
            "total": total,
            "validated": validated,
            "corroborated": corroborated,
            "downloaded_only": downloaded,
            "simulated": simulated,
            "share_validated": share,
            "label": (
                "sin datos"
                if total == 0
                else "validada" if share >= 0.95 else "parcial" if share > 0 else "no validada"
            ),
        }

    def confidence_statement(self) -> str:
        """Explica en una frase cómo afecta la calidad del dato a la confianza."""
        q = self.quality_summary()
        share = float(q["share_validated"])
        if share >= 0.95:
            base = (
                "Casi todas las observaciones superaron las comprobaciones internas "
                "(unidades homogéneas, fechas coherentes, identidad contable). "
            )
        elif share > 0:
            base = (
                f"Solo el {share:.1%} de las observaciones superó las comprobaciones "
                "internas; el resto se conserva como dato descargado sin validar. "
            )
        else:
            base = (
                "Ninguna observación superó las comprobaciones internas: las cifras "
                "proceden de una descarga correcta, que no demuestra que sean ciertas. "
            )
        return base + (
            "La corroboración implementada es interna a la misma presentación de la "
            "empresa (concepto alternativo o suma de cuatro trimestres), no una segunda "
            "fuente independiente. La confianza en la valoración es, por tanto, media: "
            "depende de la calidad de la presentación y de supuestos que no se han "
            "contrastado con ninguna otra fuente."
        )

    # -- render ---------------------------------------------------------------------

    def markdown(self) -> str:
        lines: List[str] = []
        q = self.quality_summary()
        lines.append(f"# Nexo Invest AI — Informe de empresa: {self.result.entity_name}")
        lines.append("")
        lines.append(f"**Generado:** {self.generated_at.isoformat()}")
        lines.append("")
        lines.append(f"**Fuente primaria:** {self.result.source_url()}")
        lines.append("")
        lines.append(
            f"**SHA-256 del documento consultado:** {self.result.content_sha256() or 'no registrado'}"
        )
        lines.append("")
        lines.append(f"**Periodo más reciente analizado:** {self.latest_end.isoformat()}")
        lines.append("")
        lines.append(
            f"**Estado de calidad de los datos:** {q['label']} "
            f"({q['validated']} validadas + {q['corroborated']} corroboradas de "
            f"{q['total']} observaciones)"
        )
        lines.append("")
        lines.append(
            "**Naturaleza del documento:** análisis reproducible de estados financieros "
            "presentados. No es asesoramiento financiero ni recomendación de compra o venta."
        )
        lines.append("")
        lines.append(self._how_to_read())
        lines.append("")
        lines.append(self._identity_section())
        lines.append("")
        lines.append(self._quality_section())
        lines.append("")
        lines.append(self._facts_section())
        lines.append("")
        lines.append(self._unvalidated_section())
        lines.append("")
        lines.append(self._missing_section())
        lines.append("")
        lines.append(self._indicators_section())
        lines.append("")
        lines.append(self._valuation_section())
        lines.append("")
        lines.append(self._risks_section())
        lines.append("")
        lines.append(self._simulated_section())
        lines.append("")
        lines.append(self._limitations_section())
        lines.append("")
        lines.append(self._traceability_section())
        lines.append("")
        lines.append(self._conclusion_section())
        lines.append("")
        return "\n".join(lines)

    def _how_to_read(self) -> str:
        return "\n".join(
            [
                "## 0. Cómo leer este informe",
                "",
                "- **Hecho con fuente:** cifra con periodo, formulario y documento "
                "identificables, que además superó comprobaciones internas.",
                "- **Dato descargado sin validar:** la descarga fue correcta, pero la "
                "cifra no superó (o no se le aplicaron) las comprobaciones. Se muestra "
                "separado y no se usa para conclusiones.",
                "- **Estimación:** cifra derivada de hechos observados con una fórmula "
                "declarada (por ejemplo, FCF = flujo operativo - inversiones).",
                "- **Supuesto:** valor elegido para la valoración, sin respaldo empírico. "
                "Se declara y se somete a escenarios.",
                "- **Dato simulado:** fixture de pruebas. Nunca se mezcla con datos reales.",
                "- **Información ausente:** no se calcula y no se rellena con cero.",
            ]
        )

    def _identity_section(self) -> str:
        registry = self.result.registry
        sources = list(registry.sources.values())
        first = sources[0] if sources else None
        lines = ["## 1. Identidad y procedencia de la consulta", ""]
        lines.append("| Campo | Valor |")
        lines.append("| --- | --- |")
        lines.append(f"| Entidad | {self.result.entity_name} |")
        lines.append(f"| CIK | {self.result.cik} |")
        lines.append(f"| URL de la fuente | {self.result.source_url()} |")
        if first is not None:
            lines.append(f"| Fecha de consulta | {first.retrieval_date} |")
            lines.append(f"| Fecha de presentación más reciente | {first.publication_date} |")
            lines.append(f"| Método de extracción | {first.extraction_method} |")
            lines.append(f"| Moneda | {first.currency} |")
            lines.append(f"| Escala | {first.scale.value if first.scale else 'n/d'} |")
            lines.append(f"| SHA-256 del contenido | {first.hash or 'no registrado'} |")
        lines.append(f"| Formularios aceptados | 10-K, 10-Q, 20-F, 40-F |")
        lines.append(f"| Fuentes registradas | {len(registry.sources)} |")
        lines.append(f"| Observaciones registradas | {len(registry.observations)} |")
        lines.append("")
        contacts = [
            f
            for f in self.result.fetch_records
            if getattr(f, "error", None)
        ]
        if contacts:
            lines.append("Incidencias de descarga registradas:")
            for record in contacts:
                lines.append(f"- {record.url}: {record.error}")
        lines.append(
            "Los formularios 10-K son el informe anual auditado; los 10-Q son "
            "trimestrales no auditados. Los periodos acumulados (6 y 9 meses) se "
            "excluyen para no mezclarlos con trimestres sueltos."
        )
        return "\n".join(lines)

    def _quality_section(self) -> str:
        q = self.quality_summary()
        lines = ["## 2. Estado de calidad de los datos", ""]
        lines.append("| Nivel de procedencia | Observaciones |")
        lines.append("| --- | --- |")
        lines.append(f"| Descargadas y validadas | {q['validated']} |")
        lines.append(f"| Corroboradas (intra-fuente) | {q['corroborated']} |")
        lines.append(f"| Descargadas sin validar | {q['downloaded_only']} |")
        lines.append(f"| Simuladas o fixture | {q['simulated']} |")
        lines.append(f"| **Total** | **{q['total']}** |")
        lines.append("")
        lines.append(f"Proporción utilizable como dato real: {float(q['share_validated']):.1%}.")
        lines.append("")
        if self.result.validated_metrics:
            lines.append(
                "Métricas con al menos una observación validada: "
                + ", ".join(self.result.validated_metrics)
                + "."
            )
            lines.append("")
        if self.result.corroborated_metrics:
            lines.append(
                "Métricas con corroboración intra-fuente: "
                + ", ".join(self.result.corroborated_metrics)
                + "."
            )
            lines.append("")
        withheld = [
            line
            for line in self.result.validation_notes
            if "sin promover" in line and "0 sin promover" not in line
        ]
        if withheld:
            lines.append("Observaciones no promovidas y su motivo:")
            for note in withheld:
                lines.append(f"- {note}")
            lines.append("")
        lines.append("**Efecto sobre la confianza en la valoración.** " + self.confidence_statement())
        return "\n".join(lines)

    def _facts_section(self) -> str:
        lines = [
            "## 3. Hechos con fuente y periodo identificables",
            "",
            "| Métrica | Periodo | Valor | Nivel | Documento |",
            "| --- | --- | --- | --- | --- |",
        ]
        shown = 0
        for metric, label in HEADLINE_METRICS:
            obs = self.latest_observation(metric)
            if obs is None:
                continue
            level = obs.effective_provenance_level
            if level not in (
                ProvenanceLevel.EXTERNAL_VALIDATED,
                ProvenanceLevel.EXTERNAL_CORROBORATED,
            ):
                continue
            lines.append(
                f"| {label} | {obs.period.start} → {obs.period.end} | "
                f"{_fmt_money(obs.value)} | {level.value} | {self._document_ref(obs)} |"
            )
            shown += 1
        if not shown:
            lines.append("| — | — | — | — | Sin hechos validados |")
        lines.append("")
        lines.append(
            "Cada fila se puede rastrear con la referencia del documento, que incluye "
            "formulario, fecha de presentación y accession number de la SEC."
        )
        return "\n".join(lines)

    @staticmethod
    def _document_ref(obs: Observation) -> str:
        """Extrae formulario, fecha de presentación y accession number de la nota.

        La nota del adaptador es texto libre con tokens `clave=valor`; aquí se leen
        esos tokens en lugar de asumir un orden o un separador concreto.
        """
        note = obs.notes or ""
        parts = [
            token
            for token in note.replace("|", " ").split()
            if token.startswith(("form=", "filed=", "accn="))
        ]
        return " ".join(parts) if parts else "sin detalle de documento"

    def _unvalidated_section(self) -> str:
        lines = ["## 4. Datos descargados que no se usan en conclusiones", ""]
        unvalidated = self.observations_by_level(ProvenanceLevel.EXTERNAL_DOWNLOADED)
        if not unvalidated:
            lines.append("Ninguna observación quedó sin validar.")
            return "\n".join(lines)
        lines.append(
            f"{len(unvalidated)} observaciones se descargaron correctamente pero no "
            "superaron las comprobaciones internas. No se usan para calcular "
            "conclusiones; se conservan para no perder información."
        )
        lines.append("")
        lines.append("| Métrica | Periodo | Valor | Motivo registrado |")
        lines.append("| --- | --- | --- | --- |")
        for obs in unvalidated[:25]:
            reason = ""
            for piece in (obs.notes or "").split("|"):
                piece = piece.strip()
                if "identidad contable" in piece or "unidades" in piece or "fechas" in piece:
                    reason = piece
            lines.append(
                f"| {obs.metric} | {obs.period.end} | {_fmt_money(obs.value)} | "
                f"{reason or 'sin motivo explícito registrado'} |"
            )
        if len(unvalidated) > 25:
            lines.append(f"| … | | | {len(unvalidated) - 25} observaciones más |")
        return "\n".join(lines)

    def _missing_section(self) -> str:
        lines = ["## 5. Información ausente o insuficiente", ""]
        missing = self.missing_headline_metrics()
        if missing:
            lines.append("Métricas sin observación para el periodo analizado:")
            for metric, label in missing:
                lines.append(f"- {label} (`{metric}`): sin dato. No se asume cero.")
            lines.append("")
        else:
            lines.append("Todas las métricas principales tienen al menos una observación.")
            lines.append("")
        if self.metrics.revenue_ttm is None:
            lines.append(
                "Ingresos TTM: **no disponibles**. Se exigen cuatro trimestres "
                "consecutivos de duración trimestral real; las presentaciones anuales "
                "o los acumulados YTD no sirven para completar la serie."
            )
            lines.append("")
        if self.metrics.dilution_rate is None:
            reason = self.metrics.notes.get(
                "dilution_rate", "sin motivo registrado por el motor de métricas"
            )
            lines.append(
                "Dilución de acciones: **no calculable**. Motivo registrado: "
                f"{reason}."
            )
            lines.append("")
        lines.append(
            "Consecuencia: los indicadores que dependen de estas cifras aparecen como "
            "«no calculable» en la sección 6. Un dato ausente no es evidencia negativa."
        )
        return "\n".join(lines)

    def _indicators_section(self) -> str:
        m = self.metrics
        lines = ["## 6. Indicadores fundamentales: fórmula y requisito de datos", ""]
        if m.latest_period is not None:
            lines.append(
                f"Periodo base de los indicadores: {m.latest_period.start} → "
                f"{m.latest_period.end} (frecuencia **{m.latest_period.frequency.value}**). "
                "Si la empresa no presenta cierres anuales utilizables, el análisis se "
                "hace con el periodo disponible y así queda indicado: no se extrapola a "
                "un ejercicio anual que no existe en la fuente."
            )
            lines.append("")
        lines.append("| Indicador | Valor | Fórmula | Requisito de datos |")
        lines.append("| --- | --- | --- | --- |")

        def add(label: str, value: str, formula: str, requirement: str) -> None:
            lines.append(f"| {label} | {value} | {formula} | {requirement} |")

        add("Ingresos", _fmt_money(m.revenue), "cifra reportada", "estado de resultados anual")
        add(
            "Crecimiento interanual",
            _fmt_pct(m.revenue_growth),
            "ingresos(t)/ingresos(t-1) - 1",
            "dos periodos de la misma frecuencia",
        )
        add("Márgen bruto", _fmt_pct(m.gross_margin), "beneficio bruto/ingresos", "beneficio bruto")
        add("Márgen operativo", _fmt_pct(m.operating_margin), "resultado operativo/ingresos", "resultado operativo")
        add("Márgen neto", _fmt_pct(m.net_margin), "resultado neto/ingresos", "resultado neto")
        add(
            "Flujo de caja libre",
            _fmt_money(m.free_cash_flow) + (" (estimado)" if m.free_cash_flow_estimated else ""),
            "flujo operativo - |inversiones|",
            "flujo operativo e inversiones",
        )
        add("Conversión FCF/beneficio", _fmt_pct(m.fcf_conversion_net_income), "FCF/resultado neto", "FCF y beneficio neto")
        add("Capex/ingresos", _fmt_pct(m.capex_to_revenue), "|inversiones|/ingresos", "inversiones")
        add("Deuda total", _fmt_money(m.total_debt), "reportada o suma de componentes", "balance")
        add("Deuda neta", _fmt_money(m.net_debt), "deuda total - activos líquidos corrientes", "deuda y caja")
        add("Deuda neta/EBITDA", _fmt_multiple(m.net_debt_to_ebitda), "deuda neta/EBITDA", "EBITDA y deuda neta")
        add("Cobertura de intereses", _fmt_multiple(m.interest_coverage), "resultado operativo/|gasto financiero|", "gasto financiero")
        add("Ratio corriente", _fmt_ratio(m.current_ratio), "activo corriente/pasivo corriente", "partidas corrientes")
        add("Prueba ácida", _fmt_ratio(m.quick_ratio), "(activo corriente - inventario)/pasivo corriente", "inventario")
        add("Tasa impositiva efectiva", _fmt_pct(m.effective_tax_rate), "impuestos/resultado antes de impuestos", "ambas partidas")
        add("NOPAT", _fmt_money(m.nopat), "resultado operativo x (1 - tasa efectiva)", "resultado operativo e impuestos")
        add(
            "ROIC (NOPAT)",
            _fmt_pct(m.roic_nopat),
            "NOPAT/capital invertido",
            "capital invertido" + (" (estimado)" if m.invested_capital_estimated else ""),
        )
        add("Dilución", _fmt_pct(m.dilution_rate), "acciones(t)/acciones(t-1) - 1", "dos periodos de la misma frecuencia")
        add("Dividendos pagados", _fmt_money(m.dividends_paid), "cifra reportada", "estado de flujos")
        add("Recompras", _fmt_money(m.share_repurchases), "cifra reportada", "estado de flujos")
        add(
            "Ingresos TTM",
            _fmt_money(m.revenue_ttm) if m.revenue_ttm else "no calculable",
            "suma de 4 trimestres consecutivos",
            "cuatro trimestres reales consecutivos",
        )
        lines.append("")
        estimaciones = [k for k in m.notes if "estimad" in (m.notes[k] or "")]
        if estimaciones:
            lines.append("Estimaciones declaradas en los indicadores:")
            for key in estimaciones:
                lines.append(f"- `{key}`: {m.notes[key]}")
            lines.append("")
        lines.append(
            "Ningún indicador se rellena con un valor por defecto. Cuando falta un "
            "requisito, la celda dice «no calculable» y el motivo queda en las notas "
            "del motor de métricas."
        )
        return "\n".join(lines)

    def _valuation_section(self) -> str:
        lines = ["## 7. Valoración por escenarios (supuestos explícitos)", ""]
        if not self.scenarios:
            lines.append("No se ha ejecutado valoración. Motivos registrados:")
            for note in self.valuation_notes or ["sin flujo de caja libre utilizable"]:
                lines.append(f"- {note}")
            lines.append("")
            lines.append(
                "Sin valoración no hay margen de seguridad que calcular y, por tanto, "
                "no se emite ninguna conclusión de inversión."
            )
            return "\n".join(lines)
        lines.append(
            "El valor se obtiene descontando el flujo de caja libre proyectado y añadiendo "
            "el valor terminal por Gordon Growth. Todos los parámetros son **supuestos** "
            "del analista; el único dato observado es el FCF base."
        )
        lines.append("")
        lines.append(
            "FCF base: "
            + _fmt_money(self.metrics.free_cash_flow)
            + (
                " (estimación: flujo operativo - inversiones)"
                if self.metrics.free_cash_flow_estimated
                else " (cifra reportada)"
            )
        )
        lines.append("")
        lines.append(
            "Acciones en circulación: "
            + (f"{self.shares_outstanding:,.0f}" if self.shares_outstanding else "no disponibles")
        )
        lines.append("")
        verified_price = self.scenarios[0].share_price if self.scenarios else None
        if verified_price is None:
            lines.append(
                "Precio de mercado verificado: **no disponible**. Este sistema no consulta "
                "precios en este informe, así que no se calcula margen de subida o bajada. "
                "Presentar un porcentaje de recorrido sin precio verificado sería inventar "
                "la comparación."
            )
        else:
            lines.append(
                f"Precio de mercado verificado: **{verified_price:,.2f}** "
                f"{self.scenarios[0].currency}, cierre comprobado en dos fuentes "
                "independientes (`nexo verify`). Con él se calcula el margen de subida de "
                "cada escenario; el margen de seguridad se declara en el informe de "
                "verificación, con su fórmula y sus limitaciones."
            )
        lines.append("")
        for result in self.scenarios:
            lines.append(result.markdown())
            lines.append("")
        if self.valuation_notes:
            lines.append("Notas de la valoración:")
            for note in self.valuation_notes:
                lines.append(f"- {note}")
            lines.append("")
        lines.append(
            "El escenario base **no es una predicción**. Es una de tres combinaciones "
            "explícitas de supuestos, y la horquilla entre escenarios mide la sensibilidad "
            "a esos supuestos, no la probabilidad de cada resultado."
        )
        return "\n".join(lines)

    def _risks_section(self) -> str:
        m = self.metrics
        lines = ["## 8. Riesgos y condiciones que invalidarían la tesis", ""]
        lines.append("Riesgos identificados a partir de los datos disponibles:")
        risks: List[str] = []
        if m.net_debt is not None and m.net_debt.value > 0:
            risks.append(
                "Deuda neta positiva: el valor de patrimonio es sensible a la deuda y a "
                "los tipos de interés usados como tasa de descuento."
            )
        else:
            risks.append(
                "Posición de caja neta según los activos corrientes: no se restan "
                "inversiones a largo plazo, por lo que la deuda neta puede estar "
                "sobrestimada."
            )
        if m.free_cash_flow_estimated:
            risks.append(
                "El FCF es una estimación (flujo operativo - inversiones) y no una cifra "
                "reportada por la empresa; incluye decisiones de capex que pueden no repetirse."
            )
        if m.revenue_ttm is None:
            risks.append(
                "No hay TTM de ingresos: la estacionalidad del negocio no está capturada en "
                "la comparación anual."
            )
        risks.append(
            "El informe usa una sola fuente (SEC EDGAR). Una presentación errónea de la "
            "empresa se propagaría sin contraste externo."
        )
        for risk in risks:
            lines.append(f"- {risk}")
        lines.append("")
        lines.append("Condiciones objetivas que invalidarían la tesis:")
        for rule in self.invalidation_conditions:
            lines.append(f"- {rule}")
        lines.append("")
        if self.invalidated:
            lines.append(
                "**Ya se cumple alguna condición en el periodo analizado:** "
                + "; ".join(self.invalidated)
                + ". La tesis de calidad no queda respaldada por los datos actuales."
            )
        else:
            lines.append(
                "Ninguna condición se cumple en el periodo analizado. Esto no valida la "
                "tesis: solo indica que los datos no la contradicen todavía."
            )
        return "\n".join(lines)

    def _simulated_section(self) -> str:
        simulated = [
            obs
            for obs in self.result.registry.observations.values()
            if obs.effective_provenance_level
            in (ProvenanceLevel.SYNTHETIC, ProvenanceLevel.LOCAL_FIXTURE)
        ]
        lines = ["## 9. Datos simulados", ""]
        if not simulated:
            lines.append(
                "Este informe no contiene datos simulados: todas las observaciones "
                "proceden del documento descargado de la SEC. Los fixtures del repositorio "
                "se usan solo en las pruebas automatizadas."
            )
        else:
            lines.append(
                "**Este informe contiene datos simulados y no debe interpretarse como "
                "información real:**"
            )
            for obs in simulated:
                lines.append(f"- {obs.metric} {obs.period.end}: {_fmt_money(obs.value)}")
        return "\n".join(lines)

    def _limitations_section(self) -> str:
        lines = ["## 10. Limitaciones", ""]
        limitations: List[str] = [
            "Una respuesta HTTP correcta solo demuestra que la descarga funcionó; no "
            "demuestra que la cifra sea cierta.",
            "La corroboración es intra-fuente: no se ha contrastado con una segunda fuente "
            "independiente (por ejemplo, el documento original en HTML o el informe auditado).",
            "No se consultan precios de mercado, tipos de cambio, tipos de interés ni "
            "múltiplos de empresas comparables.",
            "El XBRL puede contener reexpresiones: se conserva la presentación más reciente "
            "por periodo, lo que puede diferir de la publicada originalmente.",
            "Los periodos con el mismo cierre y distinta duración (anual y cuarto trimestre) "
            "comparten clave en el estado financiero; el motor conserva uno solo.",
        ]
        limitations.extend(self.result.limitations)
        for limitation in dict.fromkeys(limitations):
            lines.append(f"- {limitation}")
        lines.append("")
        lines.append(f"**Fecha de actualización de los datos:** {self.generated_at.date().isoformat()}")
        return "\n".join(lines)

    def _traceability_section(self) -> str:
        m = self.metrics
        lines = ["## 11. Trazabilidad: fuente → dato → cálculo → conclusión", ""]
        lines.append("```")
        lines.append(f"Fuente        : {self.result.source_url()}")
        lines.append(f"Documento     : SHA-256 {self.result.content_sha256() or 'no registrado'}")
        lines.append(f"Observaciones : {len(self.result.registry.observations)} "
                     f"({self.quality_summary()['validated']} validadas, "
                     f"{self.quality_summary()['corroborated']} corroboradas)")
        lines.append(f"Estado        : ProvenanceRegistry -> FinancialState -> FinancialMetrics")
        lines.append(f"Indicadores   : margen bruto {_fmt_pct(m.gross_margin)}, "
                     f"ROIC {_fmt_pct(m.roic_nopat)}, "
                     f"deuda neta {_fmt_money(m.net_debt)}")
        if self.scenarios:
            base = self.scenarios[1] if len(self.scenarios) > 1 else self.scenarios[0]
            lines.append(f"Valoración    : escenario {base.scenario.name} -> "
                         f"valor por acción {_fmt_money(Money(base.per_share_value, m.currency, 'units') if base.per_share_value else None)}")
        lines.append("```")
        lines.append("")
        lines.append(
            "Cada cifra de las secciones 3 y 6 proviene de una observación con su "
            "documento, y cada indicador declara su fórmula en la sección 6. Las "
            "conclusiones de la sección 12 solo usan las cifras marcadas como hechos."
        )
        return "\n".join(lines)

    def _conclusion_section(self) -> str:
        m = self.metrics
        lines = ["## 12. Conclusión provisional", ""]
        if m.revenue is None:
            lines.append(
                "**Insuficiente para evaluar.** No hay ingresos identificables para el "
                "periodo analizado, por lo que no se calcula ningún indicador de "
                "rentabilidad y no se emite conclusión de inversión."
            )
            lines.append("")
            lines.append(
                "La ausencia de datos no es evidencia negativa sobre la empresa: es una "
                "limitación del análisis."
            )
            return "\n".join(lines)
        facts = [
            f"ingresos {_fmt_money(m.revenue)} en el periodo {self.latest_end.isoformat()}",
            f"margen bruto {_fmt_pct(m.gross_margin)}",
            f"margen operativo {_fmt_pct(m.operating_margin)}",
            f"flujo de caja libre {_fmt_money(m.free_cash_flow)}"
            + (" (estimado)" if m.free_cash_flow_estimated else ""),
        ]
        lines.append("Hechos con fuente en los que se apoya esta conclusión: " + "; ".join(facts) + ".")
        lines.append("")
        lines.append(
            "**No se emite recomendación de inversión.** Falta un precio de mercado "
            "verificado para calcular margen de seguridad, y falta una segunda fuente "
            "independiente para corroborar las cifras. Cualquier afirmación sobre "
            "rentabilidad futura sería un supuesto, no un resultado."
        )
        lines.append("")
        lines.append(
            "Lo que sí puede afirmarse: los estados financieros presentados son "
            "internamente coherentes en la mayoría de los periodos revisados, y los "
            "indicadores calculados son reproducibles a partir del documento cuya huella "
            "SHA-256 figura en la sección 1."
        )
        return "\n".join(lines)


def build_real_report(
    result: SecEdgarResult,
    *,
    generated_at: Optional[datetime] = None,
    forecast_years: int = 5,
    share_price: Optional[float] = None,
    thresholds: Optional[Dict[str, float]] = None,
) -> RealCompanyReport:
    """Construye el informe de una empresa real a partir de su resultado de SEC EDGAR."""

    generated_at = generated_at or datetime.now(timezone.utc)

    revenue_observations = [
        obs
        for obs in result.registry.observations_for_metric("revenue")
        if obs.period.end <= generated_at.date()
    ]
    if not revenue_observations:
        raise ValueError(
            "No hay observaciones de ingresos: no se puede fechar el análisis ni construir el informe"
        )
    annual = [o for o in revenue_observations if o.period.frequency is Frequency.ANNUAL]
    latest_end = max(o.period.end for o in (annual or revenue_observations))

    state = result.registry.to_financial_state()
    calendar = fiscal_calendar_for(_payload_from(result)) if result.facts else FiscalCalendar(close_month=12)
    metrics = FinancialMetrics.from_state(state, latest_end=latest_end, fiscal_calendar=calendar)

    shares_obs = [
        obs
        for obs in result.registry.observations_for_metric("shares_outstanding")
        if obs.period.end <= latest_end and obs.value is not None and not obs.value.is_missing
    ]
    shares = max(shares_obs, key=lambda o: o.period.end).value.value if shares_obs else None

    report = RealCompanyReport(
        result=result,
        metrics=metrics,
        calendar=calendar,
        generated_at=generated_at,
        latest_end=latest_end,
        shares_outstanding=shares,
    )
    report.build_invalidation_rules(thresholds)
    report.run_scenarios(forecast_years=forecast_years, share_price=share_price)
    return report


def _payload_from(result: SecEdgarResult) -> dict:
    """Reconstruye un payload mínimo con los hechos para inferir el calendario fiscal.

    `fiscal_calendar_for` trabaja sobre el documento companyfacts. Como el resultado ya
    contiene los hechos extraídos, aquí se reconstruye la parte necesaria (formulario y
    fechas) sin volver a descargar nada.
    """

    facts: Dict[str, Dict[str, Dict[str, List[dict]]]] = {"facts": {"us-gaap": {}}}
    for metric, records in result.facts.items():
        for record in records:
            entry: Dict[str, object] = {
                "end": record.end.isoformat(),
                "form": record.form,
                "val": record.value,
            }
            if record.start is not None:
                entry["start"] = record.start.isoformat()
            concept = record.concept
            body = facts["facts"]["us-gaap"].setdefault(
                concept, {"units": {record.unit: []}}
            )
            body["units"].setdefault(record.unit, []).append(entry)
    return facts
