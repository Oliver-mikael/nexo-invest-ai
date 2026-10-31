"""Plantillas de los roles de investigación.

Regla común a todos los roles, incluida en el mensaje de sistema:

- Solo puede citar cifras que aparezcan en el EXPEDIENTE, referenciadas por su `id`.
- Toda afirmación cuantitativa debe llevar `evidence_ids`.
- Lo que no esté en el expediente se declara como interpretación, supuesto o
  información no disponible. Nunca se inventan fuentes, precios ni resultados.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Sequence

SYSTEM_PROMPT = (
    "Eres un analista de inversión dentro de Nexo Invest AI. Trabajas con un EXPEDIENTE "
    "cerrado de cifras verificadas. Reglas obligatorias:\n"
    "1. NO inventes cifras, fuentes, precios ni fechas. Si un dato no está en el EXPEDIENTE, "
    "escribe 'información no disponible'.\n"
    "2. Cada cifra que uses debe existir en el EXPEDIENTE y citarse en 'evidence_ids' con su id.\n"
    "3. Distingue hecho (dato del expediente), interpretación (tu razonamiento), supuesto "
    "(valor elegido) y estimación (cálculo declarado). Usa 'kind' para etiquetar cada claim.\n"
    "4. Responde SOLO con un objeto JSON válido, sin markdown ni texto fuera del JSON.\n"
    "5. No emitas recomendaciones de compra o venta ni precios objetivo."
)

JSON_SHAPE = (
    '{"summary": "una frase", '
    '"sections": {"clave": "texto o lista"}, '
    '"claims": [{"text": "...", "kind": "fact|interpretation|assumption|estimate|unavailable", '
    '"evidence_ids": ["metric:revenue"]}], '
    '"sources": [{"title": "...", "url": "..."}]}'
)

ROLE_INSTRUCTIONS: Dict[str, str] = {
    "business_researcher": (
        "Rol: INVESTIGADOR EMPRESARIAL. Describe el modelo de negocio, productos, mercado, "
        "competencia, ventajas competitivas, estrategia, noticias y catalizadores usando solo "
        "el expediente y conocimiento general no numérico. Claves de 'sections': "
        "business_model, products, market, competitors, moat, strategy, news, catalysts. "
        "Si no dispones de información externa verificada, indícalo en cada clave."
    ),
    "financial_analyst": (
        "Rol: ANALISTA FINANCIERO. Evalúa calidad financiera, crecimiento, márgenes, flujo de "
        "caja, deuda, rentabilidad y valoración. Claves de 'sections': quality, growth, margins, "
        "cash_flow, debt, profitability, valuation. Cita cada cifra con su id del expediente."
    ),
    "evidence_auditor": (
        "Rol: AUDITOR DE EVIDENCIA. Revisa las afirmaciones de los demás roles y del expediente. "
        "Claves de 'sections': issues (lista de {claim, problem, severity, evidence_id}), "
        "contradictions, missing_data. Marca como problema cualquier cifra que no esté en el "
        "expediente o cualquier periodo/unidad incoherente."
    ),
    "contrarian_analyst": (
        "Rol: ANALISTA CONTRARIO. Construye el mejor argumento contra la tesis. Claves de "
        "'sections': counter_thesis, ignored_risks, competitive_threats, financial_deterioration, "
        "overvaluation, optimistic_assumptions, red_flags."
    ),
    "coordinator": (
        "Rol: ANALISTA COORDINADOR. Consolida los resultados anteriores sin inventar consenso. "
        "Claves de 'sections': thesis, conclusion, disagreements (lista), "
        "invalidation_conditions (lista), confidence. Si dos roles discrepan, conserva ambas "
        "posiciones en 'disagreements' en lugar de promediarlas."
    ),
}

ROLE_LABELS: Dict[str, str] = {
    "business_researcher": "Investigador empresarial",
    "financial_analyst": "Analista financiero",
    "evidence_auditor": "Auditor de evidencia",
    "contrarian_analyst": "Analista contrario",
    "coordinator": "Analista coordinador",
}


def build_context(
    *,
    identity: Dict[str, Any],
    ledger: Sequence[Dict[str, Any]],
    valuation: Dict[str, Any],
    provenance: Dict[str, Any],
    previous: Sequence[Dict[str, Any]] = (),
    max_ledger: int = 60,
) -> str:
    """Expediente compacto en JSON. Se recorta para no disparar el coste."""

    compact_ledger: List[Dict[str, Any]] = []
    for entry in list(ledger)[:max_ledger]:
        compact_ledger.append(
            {
                "id": entry.get("id"),
                "label": entry.get("label"),
                "value": entry.get("value"),
                "unit": entry.get("unit"),
                "period_end": entry.get("period_end"),
                "provenance": entry.get("provenance"),
            }
        )
    scenarios = [
        {
            "name": item.get("name"),
            "discount_rate": item.get("discount_rate"),
            "terminal_growth": item.get("terminal_growth"),
            "growth_rates": item.get("growth_rates"),
            "per_share_value": item.get("per_share_value"),
            "enterprise_value": item.get("enterprise_value"),
            "equity_value": item.get("equity_value"),
        }
        for item in valuation.get("scenarios", [])
    ]
    payload = {
        "company": identity,
        "provenance": {
            "quality_label": provenance.get("quality_label"),
            "counts": provenance.get("counts"),
            "missing_metrics": provenance.get("missing_metrics"),
            "source_url": provenance.get("source_url"),
        },
        "evidence_ledger": compact_ledger,
        "engine_valuation": {
            "scenarios": scenarios,
            "sensitivity": valuation.get("sensitivity", {}).get("base"),
            "notes": valuation.get("notes", []),
        },
        "previous_research": list(previous)[:3],
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def build_messages(role: str, context: str, *, extra: str = "") -> List[Dict[str, str]]:
    instruction = ROLE_INSTRUCTIONS.get(role, "")
    user = (
        f"{instruction}\n\n"
        f"Devuelve exactamente esta estructura JSON: {JSON_SHAPE}\n\n"
        f"EXPEDIENTE:\n{context}\n"
    )
    if extra:
        user += f"\nCONTEXTO ADICIONAL:\n{extra}\n"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
