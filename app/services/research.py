"""Pipeline de investigación: motor + orquestador + auditoría + informe.

El informe final tiene siempre las mismas 18 secciones, exista o no IA. En modo
básico las secciones cualitativas dicen «información no disponible» en lugar de
rellenarse con texto inventado; las cuantitativas salen del motor financiero.

Cada sección declara su base: hecho verificado, dato de fuente, interpretación de
IA, supuesto, estimación o información no disponible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.ai.audit import find_unsupported_numbers
from app.ai.orchestrator import OrchestrationResult
from app.services.engine import AnalysisBundle

SECTION_TITLES: Tuple[Tuple[str, str], ...] = (
    ("identification", "Identificación de la empresa"),
    ("business", "Descripción del negocio"),
    ("market", "Sector y mercado"),
    ("competitors", "Competidores"),
    ("moat", "Ventajas competitivas"),
    ("financial_quality", "Calidad financiera"),
    ("growth", "Crecimiento"),
    ("margins", "Márgenes"),
    ("cash_flow", "Flujo de caja"),
    ("debt", "Deuda"),
    ("valuation", "Valoración"),
    ("scenarios", "Escenarios"),
    ("risks", "Riesgos"),
    ("catalysts", "Catalizadores"),
    ("thesis", "Tesis de inversión"),
    ("contrary", "Argumentos contrarios"),
    ("invalidation", "Condiciones de invalidación"),
    ("conclusion", "Conclusión"),
)

BASIS_LABELS = {
    "fact": "hecho verificado",
    "source": "dato de fuente",
    "ai": "interpretación de IA",
    "assumption": "supuesto",
    "estimate": "estimación",
    "unavailable": "información no disponible",
}


def _fmt_money(value: Optional[float], currency: str = "USD") -> str:
    if value is None:
        return "no disponible"
    return f"{value:,.0f} {currency}"


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "no disponible"
    return f"{value:.2%}"


def _fmt_num(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "no disponible"
    return f"{value:,.{digits}f}"


def _metric(payload: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    for entry in payload.get("metrics", []):
        if entry.get("key") == key:
            return entry
    return None


def _metric_value(payload: Dict[str, Any], key: str) -> Optional[float]:
    entry = _metric(payload, key)
    if entry is None:
        return None
    raw = entry.get("value")
    return float(raw) if isinstance(raw, (int, float)) else None


@dataclass
class Section:
    id: str
    title: str
    basis: str
    paragraphs: List[str] = field(default_factory=list)
    bullets: List[str] = field(default_factory=list)
    table: Optional[Dict[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "basis": self.basis,
            "basis_label": BASIS_LABELS.get(self.basis, self.basis),
            "paragraphs": self.paragraphs,
            "bullets": self.bullets,
            "table": self.table,
        }


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(", ".join(f"{k}: {_text(v)}" for k, v in item.items() if v))
            else:
                parts.append(_text(item))
        return "\n".join(p for p in parts if p)
    if isinstance(value, dict):
        return "\n".join(f"{k}: {_text(v)}" for k, v in value.items() if v)
    return str(value)


def _role_section(output: Optional[Dict[str, Any]], keys: Sequence[str]) -> str:
    if not output:
        return ""
    sections = output.get("sections") or {}
    parts = []
    for key in keys:
        if key in sections:
            rendered = _text(sections[key])
            if rendered:
                parts.append(rendered)
    return "\n\n".join(parts)


def _previous_snapshot(previous: Sequence[Dict[str, Any]]) -> List[str]:
    changes: List[str] = []
    for item in previous:
        created = item.get("created_at") or "sin fecha"
        base_value = item.get("base_per_share")
        changes.append(
            f"Investigación anterior ({created}): valor base por acción "
            f"{_fmt_num(base_value)} {item.get('currency', '')}".strip()
        )
    return changes


def _valuation_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(payload.get("valuation", {}).get("scenarios", []))


def build_sections(
    bundle: AnalysisBundle,
    orchestration: Optional[OrchestrationResult],
) -> List[Section]:
    payload = bundle.payload
    identity = payload["identity"]
    provenance = payload["provenance"]
    currency = identity.get("currency", "USD")
    outputs = orchestration.outputs() if orchestration else {}
    business = outputs.get("business_researcher")
    financial = outputs.get("financial_analyst")
    contrarian = outputs.get("contrarian_analyst")
    auditor = outputs.get("evidence_auditor")
    coordinator = outputs.get("coordinator")

    sections: List[Section] = []

    sections.append(
        Section(
            id="identification",
            title=SECTION_TITLES[0][1],
            basis="fact",
            paragraphs=[
                f"{identity.get('name', '')} ({identity.get('ticker', '')}), CIK "
                f"{identity.get('cik') or 'no disponible'}. Moneda de presentación: {currency}. "
                f"Último periodo analizado: {identity.get('latest_period_end', 'no disponible')}. "
                f"Fuente primaria: {provenance.get('source_url') or 'no disponible'}."
            ],
            bullets=[
                f"SHA-256 del documento: {provenance.get('content_sha256') or 'no registrado'}",
                f"Observaciones: {provenance['counts']['total']} totales, "
                f"{provenance['counts']['validated']} validadas, "
                f"{provenance['counts']['corroborated']} corroboradas.",
                f"Calidad declarada: {provenance.get('quality_label')}.",
            ],
        )
    )

    business_text = _role_section(business, ["business_model", "products", "strategy"])
    sections.append(
        Section(
            id="business",
            title=SECTION_TITLES[1][1],
            basis="ai" if business_text else "unavailable",
            paragraphs=[business_text] if business_text else [],
            bullets=(
                []
                if business_text
                else [
                    "Sin proveedor de IA configurado o rol no ejecutado: no se genera "
                    "descripción cualitativa. El sistema no la inventa."
                ]
            ),
        )
    )

    market_text = _role_section(business, ["market"])
    sections.append(
        Section(
            id="market",
            title=SECTION_TITLES[2][1],
            basis="ai" if market_text else "unavailable",
            paragraphs=[market_text] if market_text else [],
            bullets=[] if market_text else ["Información de mercado no disponible en el expediente."],
        )
    )

    competitors_text = _role_section(business, ["competitors"])
    sections.append(
        Section(
            id="competitors",
            title=SECTION_TITLES[3][1],
            basis="ai" if competitors_text else "unavailable",
            paragraphs=[competitors_text] if competitors_text else [],
            bullets=[] if competitors_text else ["No hay comparables cargados en el expediente."],
        )
    )

    moat_text = _role_section(business, ["moat"])
    sections.append(
        Section(
            id="moat",
            title=SECTION_TITLES[4][1],
            basis="ai" if moat_text else "unavailable",
            paragraphs=[moat_text] if moat_text else [],
            bullets=[] if moat_text else ["Ventajas competitivas no evaluadas sin fuentes externas."],
        )
    )

    quality_text = _role_section(financial, ["quality"]) or provenance.get("statement", "")
    sections.append(
        Section(
            id="financial_quality",
            title=SECTION_TITLES[5][1],
            basis="fact" if not _role_section(financial, ["quality"]) else "ai",
            paragraphs=[quality_text] if quality_text else [],
            bullets=[
                f"Ingresos: {_fmt_money(_metric_value(payload, 'revenue'), currency)}",
                f"Resultado neto: {_fmt_money(_metric_value(payload, 'net_income'), currency)}",
                f"ROIC (NOPAT): {_fmt_pct(_metric_value(payload, 'roic_nopat'))}",
                f"Deuda neta / EBITDA: {_fmt_num(_metric_value(payload, 'net_debt_to_ebitda'))}x",
            ],
        )
    )

    growth_text = _role_section(financial, ["growth"])
    sections.append(
        Section(
            id="growth",
            title=SECTION_TITLES[6][1],
            basis="ai" if growth_text else "fact",
            paragraphs=[growth_text] if growth_text else [],
            bullets=[
                f"Crecimiento de ingresos: {_fmt_pct(_metric_value(payload, 'revenue_growth'))}",
                f"Crecimiento fiscal: {_fmt_pct(_metric_value(payload, 'revenue_growth_fiscal'))}",
            ],
        )
    )

    margins_text = _role_section(financial, ["margins"])
    sections.append(
        Section(
            id="margins",
            title=SECTION_TITLES[7][1],
            basis="ai" if margins_text else "fact",
            paragraphs=[margins_text] if margins_text else [],
            bullets=[
                f"Margen bruto: {_fmt_pct(_metric_value(payload, 'gross_margin'))}",
                f"Margen operativo: {_fmt_pct(_metric_value(payload, 'operating_margin'))}",
                f"Margen neto: {_fmt_pct(_metric_value(payload, 'net_margin'))}",
            ],
        )
    )

    cash_text = _role_section(financial, ["cash_flow"])
    fcf = _metric_value(payload, "free_cash_flow")
    sections.append(
        Section(
            id="cash_flow",
            title=SECTION_TITLES[8][1],
            basis="ai" if cash_text else "estimate",
            paragraphs=[cash_text] if cash_text else [],
            bullets=[
                f"Flujo de caja libre: {_fmt_money(fcf, currency)}"
                + (" (estimado: flujo operativo - capex)" if payload["valuation"].get("fcf_estimated") else ""),
                f"Flujo operativo: {_fmt_money(_metric_value(payload, 'operating_cash_flow'), currency)}",
                f"Conversión FCF/beneficio neto: "
                f"{_fmt_pct(_metric_value(payload, 'fcf_conversion_net_income'))}",
            ],
        )
    )

    debt_text = _role_section(financial, ["debt"])
    sections.append(
        Section(
            id="debt",
            title=SECTION_TITLES[9][1],
            basis="ai" if debt_text else "fact",
            paragraphs=[debt_text] if debt_text else [],
            bullets=[
                f"Deuda total: {_fmt_money(_metric_value(payload, 'total_debt'), currency)}",
                f"Caja y equivalentes: "
                f"{_fmt_money(_metric_value(payload, 'cash_and_equivalents'), currency)}",
                f"Deuda neta: {_fmt_money(_metric_value(payload, 'net_debt'), currency)}",
                f"Cobertura de intereses: {_fmt_num(_metric_value(payload, 'interest_coverage'))}x",
            ],
        )
    )

    valuation_text = _role_section(financial, ["valuation"])
    sections.append(
        Section(
            id="valuation",
            title=SECTION_TITLES[10][1],
            basis="ai" if valuation_text else "estimate",
            paragraphs=[valuation_text] if valuation_text else [],
            bullets=[f"{note}" for note in payload["valuation"].get("notes", [])]
            + [
                f"FCF base: {_fmt_money(payload['valuation'].get('base_fcf'), currency)}",
                "El valor por acción procede del motor DCF, nunca de una cifra generada por IA.",
            ],
        )
    )

    rows = _valuation_rows(payload)
    scenario_table = {
        "columns": ["Escenario", "Crecimiento", "Descuento", "Terminal", f"Valor/acción ({currency})"],
        "rows": [
            [
                row.get("name", ""),
                _fmt_pct((row.get("growth_rates") or [None])[0]),
                _fmt_pct(row.get("discount_rate")),
                _fmt_pct(row.get("terminal_growth")),
                _fmt_num(row.get("per_share_value")),
            ]
            for row in rows
        ],
        "caption": (
            "Escenarios del motor. Los supuestos son explícitos y modificables en la "
            "calculadora de valoración."
        ),
    }
    sensitivity = payload["valuation"].get("sensitivity", {})
    sensitivity_table = None
    if sensitivity.get("available"):
        sensitivity_table = {
            "columns": ["Descuento \\ Terminal"]
            + [f"{tg:.2%}" for tg in sensitivity.get("terminal_growths", [])],
            "rows": [
                [
                    f"{rate:.2%}",
                    *[
                        _fmt_num(
                            next(
                                (
                                    cell.get("per_share_value")
                                    for cell in sensitivity.get("cells", [])
                                    if cell.get("discount_rate") == rate
                                    and cell.get("terminal_growth") == tg
                                ),
                                None,
                            )
                        )
                        for tg in sensitivity.get("terminal_growths", [])
                    ],
                ]
                for rate in sensitivity.get("discount_rates", [])
            ],
            "caption": "Sensibilidad del escenario base. No es un rango de precio objetivo.",
        }
    sections.append(
        Section(
            id="scenarios",
            title=SECTION_TITLES[11][1],
            basis="assumption",
            paragraphs=[
                "Cada escenario cambia crecimiento del flujo, descuento, crecimiento terminal "
                "y un ajuste explícito al FCF base. Ninguno es una previsión."
            ],
            table=scenario_table,
        )
    )
    if sensitivity_table is not None:
        sections.append(
            Section(
                id="sensitivity",
                title="Sensibilidad",
                basis="assumption",
                table=sensitivity_table,
            )
        )

    risks_text = _role_section(contrarian, ["ignored_risks", "red_flags", "counter_thesis"])
    auditor_text = _role_section(auditor, ["issues", "contradictions", "missing_data"])
    risk_bullets = list(payload["risks"].get("already_invalidated", []))
    risk_bullets += [f"{cond}" for cond in payload["risks"].get("invalidation_conditions", [])]
    risk_paragraphs = []
    if risks_text:
        risk_paragraphs.append(risks_text)
    if auditor_text:
        risk_paragraphs.append(f"Auditoría de evidencia:\n{auditor_text}")
    sections.append(
        Section(
            id="risks",
            title=SECTION_TITLES[12][1],
            basis="ai" if risk_paragraphs else "fact",
            paragraphs=risk_paragraphs,
            bullets=risk_bullets[:12],
        )
    )

    catalysts_text = _role_section(business, ["catalysts"])
    sections.append(
        Section(
            id="catalysts",
            title=SECTION_TITLES[13][1],
            basis="ai" if catalysts_text else "unavailable",
            paragraphs=[catalysts_text] if catalysts_text else [],
            bullets=[] if catalysts_text else ["Catalizadores no disponibles sin fuentes externas."],
        )
    )

    thesis_text = _role_section(coordinator, ["thesis", "conclusion"]) or _role_section(contrarian, ["counter_thesis"])
    sections.append(
        Section(
            id="thesis",
            title=SECTION_TITLES[14][1],
            basis="ai" if coordinator and thesis_text else "unavailable",
            paragraphs=[thesis_text] if thesis_text else [],
            bullets=[] if thesis_text else ["No hay tesis: el coordinador no se ejecutó."],
        )
    )

    contrary_text = _role_section(
        contrarian, ["counter_thesis", "competitive_threats", "financial_deterioration", "overvaluation", "optimistic_assumptions"]
    )
    sections.append(
        Section(
            id="contrary",
            title=SECTION_TITLES[15][1],
            basis="ai" if contrary_text else "unavailable",
            paragraphs=[contrary_text] if contrary_text else [],
            bullets=[] if contrary_text else ["Argumentos contrarios no generados."],
        )
    )

    disagreements = (coordinator or {}).get("sections", {}).get("disagreements")
    invalidation_text = _role_section(coordinator, ["invalidation_conditions"])
    invalidation_bullets = [f"{cond}" for cond in payload["risks"].get("invalidation_conditions", [])]
    if disagreements:
        invalidation_bullets.append(f"Desacuerdos entre roles: {_text(disagreements)}")
    sections.append(
        Section(
            id="invalidation",
            title=SECTION_TITLES[16][1],
            basis="assumption",
            paragraphs=[invalidation_text] if invalidation_text else [],
            bullets=invalidation_bullets,
        )
    )

    conclusion_text = _role_section(coordinator, ["conclusion"])
    engine_conclusion = (
        "El motor no emite recomendaciones. La valoración depende de supuestos declarados y "
        "la calidad del dato está etiquetada como "
        f"{provenance.get('quality_label')}."
    )
    sections.append(
        Section(
            id="conclusion",
            title=SECTION_TITLES[17][1],
            basis="ai" if conclusion_text else "fact",
            paragraphs=[conclusion_text or engine_conclusion],
            bullets=[
                f"Investigación generada con el perfil "
                f"{orchestration.profile if orchestration else 'basic'}.",
                f"Coste de IA del trabajo: "
                f"{orchestration.usage.cost_usd if orchestration else 0.0:.4f} USD "
                f"(presupuesto {orchestration.budget_usd if orchestration else 0.0:.2f} USD).",
            ],
        )
    )
    return sections


def collect_claims(outputs: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    for role, output in outputs.items():
        for claim in output.get("claims", []):
            claims.append({**claim, "role": role})
    return claims


def audit_outputs(
    outputs: Dict[str, Dict[str, Any]], ledger: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    checked_chars = 0
    for role, output in outputs.items():
        text = json.dumps(output.get("sections", {}), ensure_ascii=False)
        checked_chars += len(text)
        for item in find_unsupported_numbers(text, ledger):
            findings.append({"role": role, **item.as_dict()})
    cited = sorted({cid for output in outputs.values() for claim in output.get("claims", []) for cid in claim.get("evidence_ids", [])})
    known = {str(entry.get("id")) for entry in ledger}
    unknown_citations = [cid for cid in cited if cid not in known]
    return {
        "unsupported_numbers": findings[:40],
        "unsupported_count": len(findings),
        "checked_chars": checked_chars,
        "cited_evidence": cited[:60],
        "unknown_citations": unknown_citations[:40],
        "verdict": (
            "sin cifras sin respaldo detectadas"
            if not findings
            else f"{len(findings)} cifras sin respaldo en el expediente"
        ),
    }


def build_markdown(
    *,
    bundle: AnalysisBundle,
    sections: Sequence[Section],
    orchestration: Optional[OrchestrationResult],
    audit: Dict[str, Any],
    generated_at: datetime,
) -> str:
    payload = bundle.payload
    identity = payload["identity"]
    provenance = payload["provenance"]
    lines: List[str] = []
    lines.append(f"# Nexo Invest AI — Investigación: {identity.get('name')} ({identity.get('ticker')})")
    lines.append("")
    lines.append(f"**Generado:** {generated_at.isoformat()}")
    lines.append("")
    lines.append(
        f"**Perfil:** {(orchestration.profile if orchestration else 'basic')} · "
        f"**Coste IA:** {(orchestration.usage.cost_usd if orchestration else 0.0):.4f} USD"
    )
    lines.append("")
    lines.append(f"**Fuente primaria:** {provenance.get('source_url') or 'no disponible'}")
    lines.append("")
    lines.append(f"**SHA-256:** {provenance.get('content_sha256') or 'no registrado'}")
    lines.append("")
    lines.append(f"**Calidad del dato:** {provenance.get('quality_label')}")
    lines.append("")
    lines.append(
        "> Documento de investigación reproducible. No es asesoramiento financiero ni "
        "recomendación de compra o venta. Las cifras con fuente son trazables al documento "
        "de la SEC citado; las interpretaciones de IA están etiquetadas como tales."
    )
    lines.append("")
    for section in sections:
        lines.append(f"## {section.title}")
        lines.append("")
        lines.append(f"*Base: {BASIS_LABELS.get(section.basis, section.basis)}*")
        lines.append("")
        for paragraph in section.paragraphs:
            lines.append(paragraph)
            lines.append("")
        for bullet in section.bullets:
            lines.append(f"- {bullet}")
        if section.bullets:
            lines.append("")
        if section.table:
            caption = section.table.get("caption")
            if caption:
                lines.append(f"{caption}")
                lines.append("")
            columns = section.table.get("columns", [])
            rows = section.table.get("rows", [])
            if columns:
                lines.append("| " + " | ".join(str(c) for c in columns) + " |")
                lines.append("| " + " | ".join("---" for _ in columns) + " |")
                for row in rows:
                    lines.append("| " + " | ".join(str(c) for c in row) + " |")
                lines.append("")
    lines.append("## Auditoría de la investigación")
    lines.append("")
    lines.append(f"- {audit.get('verdict', 'sin auditoría')}")
    lines.append(f"- Caracteres de texto de IA revisados: {audit.get('checked_chars', 0)}")
    unknown = audit.get("unknown_citations") or []
    lines.append(
        "- Citas a evidencias inexistentes: "
        + (", ".join(unknown) if unknown else "ninguna")
    )
    unsupported = audit.get("unsupported_numbers") or []
    for item in unsupported[:20]:
        lines.append(
            f"  - [{item.get('role')}] {item.get('raw')} sin respaldo: "
            f"«{str(item.get('context', ''))[:120]}»"
        )
    lines.append("")
    if orchestration is not None:
        lines.append("### Roles ejecutados")
        lines.append("")
        lines.append("| Rol | Estado | Modelo | Tokens (entrada/salida) | Coste |")
        lines.append("| --- | --- | --- | --- | --- |")
        for role in orchestration.roles:
            lines.append(
                f"| {role.label} | {role.status} | {role.provider}:{role.model} | "
                f"{role.usage.tokens_in}/{role.usage.tokens_out} | {role.usage.cost_usd:.4f} USD |"
            )
        lines.append("")
        if orchestration.stopped_reason:
            lines.append(f"Nota: {orchestration.stopped_reason}.")
            lines.append("")
    return "\n".join(lines)


def assemble(
    *,
    bundle: AnalysisBundle,
    orchestration: Optional[OrchestrationResult],
    previous: Sequence[Dict[str, Any]] = (),
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc)
    sections = build_sections(bundle, orchestration)
    outputs = orchestration.outputs() if orchestration else {}
    audit = audit_outputs(outputs, bundle.payload.get("ledger", []))
    markdown = build_markdown(
        bundle=bundle,
        sections=sections,
        orchestration=orchestration,
        audit=audit,
        generated_at=generated_at,
    )
    base_scenario = next(
        (row for row in _valuation_rows(bundle.payload) if row.get("name") == "base"),
        None,
    )
    return {
        "ticker": bundle.ticker,
        "company": bundle.payload["identity"].get("name"),
        "generated_at": generated_at.isoformat(),
        "profile": orchestration.profile if orchestration else "basic",
        "sections": [section.as_dict() for section in sections],
        "audit": audit,
        "usage": orchestration.usage.as_dict() if orchestration else {},
        "roles": [role.as_dict() for role in orchestration.roles] if orchestration else [],
        "base_per_share": (base_scenario or {}).get("per_share_value"),
        "currency": bundle.payload["identity"].get("currency"),
        "provenance": bundle.payload.get("provenance", {}),
        "metrics": bundle.payload.get("metrics", []),
        "scenarios": _valuation_rows(bundle.payload),
        "previous": _previous_snapshot(previous),
        "markdown": markdown,
    }
