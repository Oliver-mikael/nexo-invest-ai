"""Contraste de datos entre fuentes independientes y margen de seguridad.

Qué comprueba este módulo y con qué honestidad:

- **Ingresos anuales:** compara la cifra de SEC EDGAR (fuente primaria, XBRL de los
  documentos presentados) con la del mismo periodo en Nasdaq (fuente de distribución
  independiente). Si las dos coinciden, el dato sube a `EXTERNAL_CORROBORATED` con la
  limitación escrita de que Nasdaq se deriva de los mismos documentos que presenta la
  empresa: se comprueba la cadena de distribución, no una medición independiente.
- **Precio de cierre:** compara el cierre sin ajustar de Yahoo Finance con el
  `Close/Last` de Nasdaq para una fecha de negociación concreta, y comprueba que ambos
  corresponden al mismo símbolo. Solo si las dos fuentes coinciden se considera precio
  utilizable para calcular margen de seguridad.
- **Margen de seguridad:** se calcula solo con precio verificado y valor intrínseco
  positivo, con la fórmula declarada. No es una predicción ni una recomendación.

Nada de lo anterior rellena huecos: si un periodo o una fecha no está en ambas fuentes,
el resultado es `INCOMPARABLE`, con el motivo escrito, y no una coincidencia inventada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import List, Optional, Sequence

from nexo_invest.core.sources import ProvenanceLevel
from nexo_invest.data.nasdaq import NasdaqFinancials, NasdaqHistory

# Relación de unidad que se admite al alinear la fuente primaria (USD) con una fuente
# que no declara unidad. Cualquier otra razón se trata como alineación fallida.
UNIT_FACTORS: Sequence[float] = (1.0, 10.0, 100.0, 1_000.0, 1_000_000.0, 1_000_000_000.0)

DEFAULT_REVENUE_TOLERANCE = 0.001   # 0,1 %
DEFAULT_PRICE_TOLERANCE = 0.0005    # 0,05 % (medio céntimo sobre 347 USD)


class ContrastStatus(Enum):
    MATCH = "coincide"
    MISMATCH = "discrepancia"
    INCOMPARABLE = "incomparable"


def contrast_failed(
    *, metric: str, period_end: date, primary_value: Optional[float], reason: str
) -> Contrast:
    """Contraste imposible porque la segunda fuente no respondió.

    Se registra el motivo y se queda en `INCOMPARABLE`: un fallo de descarga no es
    una coincidencia ni una discrepancia, y tampoco se convierte en cero.
    """

    return Contrast(
        metric=metric,
        period_end=period_end,
        status=ContrastStatus.INCOMPARABLE,
        primary_value=primary_value,
        secondary_value=None,
        reasons=[reason],
        limitations=[
            "Sin segunda fuente no hay contraste: la cifra queda como descargada y "
            "validada internamente, no corroborada."
        ],
    )


@dataclass
class Contrast:
    """Resultado de un contraste entre dos fuentes para una cifra concreta."""

    metric: str
    period_end: date
    status: ContrastStatus
    primary_value: Optional[float]
    secondary_value: Optional[float]
    aligned_secondary_value: Optional[float] = None
    inferred_unit_factor: Optional[float] = None
    absolute_difference: Optional[float] = None
    relative_difference: Optional[float] = None
    tolerance: float = 0.0
    primary_currency: str = "USD"
    primary_scale: str = "units"
    secondary_currency: Optional[str] = None
    secondary_unit_note: str = "no declarada por la fuente; se infiere por contraste"
    primary_source: str = ""
    primary_url: Optional[str] = None
    primary_retrieval: Optional[date] = None
    primary_reference: Optional[str] = None
    secondary_source: str = ""
    secondary_url: Optional[str] = None
    secondary_retrieval: Optional[date] = None
    secondary_reference: Optional[str] = None
    reasons: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    # Identidad del documento primario cuando el contraste es HTML vs CompanyFacts.
    accession: Optional[str] = None
    content_sha256: Optional[str] = None
    fiscal_year: Optional[int] = None
    fiscal_period: Optional[str] = None
    form: Optional[str] = None

    @property
    def provenance_level(self) -> ProvenanceLevel:
        if self.status is ContrastStatus.MATCH:
            return ProvenanceLevel.EXTERNAL_CORROBORATED
        return ProvenanceLevel.EXTERNAL_DOWNLOADED

    @property
    def usable_for_margin_of_safety(self) -> bool:
        return self.status is ContrastStatus.MATCH

    def summary(self) -> str:
        return {
            ContrastStatus.MATCH: "coincide con la segunda fuente",
            ContrastStatus.MISMATCH: "discrepancia con la segunda fuente",
            ContrastStatus.INCOMPARABLE: "no comparable con la segunda fuente",
        }[self.status]


def _relative_difference(a: float, b: float) -> float:
    denominator = max(abs(a), abs(b))
    return abs(a - b) / denominator if denominator else (0.0 if a == b else float("inf"))


def _best_unit_alignment(
    primary: float, secondary: float
) -> Optional[tuple]:
    """Busca la potencia de diez que mejor alinea ambas cifras.

    Devuelve (factor, valor alineado, diferencia relativa). Si la mejor alineación no
    es una potencia de diez razonable, el contraste no se declara comparable.
    """

    if secondary == 0:
        return None
    best = None
    for factor in UNIT_FACTORS:
        aligned = secondary * factor
        diff = _relative_difference(primary, aligned)
        if best is None or diff < best[2]:
            best = (factor, aligned, diff)
    return best


def contrast_annual_revenue(
    *,
    metric: str,
    period_end: date,
    primary_value: float,
    primary_url: str,
    primary_retrieval: date,
    primary_reference: str,
    secondary: NasdaqFinancials,
    secondary_label: str = "Total Revenue",
    tolerance: float = DEFAULT_REVENUE_TOLERANCE,
    primary_currency: str = "USD",
    primary_scale: str = "units",
    secondary_currency: str = "USD",
) -> Contrast:
    """Compara la cifra de un periodo fiscal completo entre la fuente primaria y Nasdaq.

    Solo se acepta un periodo con fecha de cierre idéntica en ambas fuentes: no se
    aproxima al cierre más cercano ni se rellena con otro ejercicio.
    """

    base = dict(
        metric=metric,
        period_end=period_end,
        primary_value=primary_value,
        primary_currency=primary_currency,
        primary_scale=primary_scale,
        primary_source="SEC EDGAR (XBRL, documento presentado)",
        primary_url=primary_url,
        primary_retrieval=primary_retrieval,
        primary_reference=primary_reference,
        secondary_source="Nasdaq (api.nasdaq.com, estado de resultados)",
        secondary_url=secondary.source.url if secondary.source else None,
        secondary_retrieval=(
            secondary.fetch.retrieved_at.date() if secondary.fetch else None
        ),
        secondary_reference=(
            f"{secondary.ticker} · columna {secondary_label} · "
            f"cierres: {', '.join(d.isoformat() for d in secondary.period_endings)}"
        ),
        secondary_currency=secondary_currency,
        tolerance=tolerance,
    )

    if period_end not in secondary.period_endings:
        return Contrast(
            status=ContrastStatus.INCOMPARABLE,
            secondary_value=None,
            reasons=[
                "La segunda fuente no publica una columna con fecha de cierre "
                f"idéntica a {period_end.isoformat()}."
            ],
            limitations=[
                "Sin fecha de cierre común no se compara nada: no se elige el periodo "
                "más cercano ni se interpola."
            ],
            **base,
        )

    raw = secondary.value_for(secondary_label, period_end)
    if raw is None:
        return Contrast(
            status=ContrastStatus.INCOMPARABLE,
            secondary_value=None,
            reasons=[
                f"La segunda fuente no publica la fila «{secondary_label}» para el "
                f"periodo {period_end.isoformat()}."
            ],
            limitations=["Una celda ausente no se interpreta como cero."],
            **base,
        )

    alignment = _best_unit_alignment(primary_value, raw)
    if alignment is None:
        return Contrast(
            status=ContrastStatus.INCOMPARABLE,
            secondary_value=raw,
            reasons=["La segunda fuente publicó una celda vacía para ese periodo."],
            limitations=["Una celda ausente no se interpreta como cero."],
            **base,
        )

    factor, aligned, rel_diff = alignment
    if rel_diff > tolerance:
        return Contrast(
            status=ContrastStatus.MISMATCH,
            secondary_value=raw,
            aligned_secondary_value=aligned,
            inferred_unit_factor=factor,
            absolute_difference=abs(primary_value - aligned),
            relative_difference=rel_diff,
            reasons=[
                f"Diferencia relativa {rel_diff:.4%} por encima de la tolerancia "
                f"{tolerance:.4%} con la mejor alineación de unidad (×{factor:g})."
            ],
            limitations=[
                "Una discrepancia real obliga a investigar el documento original antes "
                "de usar cualquiera de las dos cifras."
            ],
            **base,
        )

    limitations = [
        "Nasdaq es una distribución independiente del mismo documento presentado por "
        "la empresa, no una fuente primaria distinta: la coincidencia comprueba la "
        "cadena de distribución, no una medición independiente.",
        f"La relación de unidad (×{factor:g}) está inferida; el endpoint no la declara.",
    ]
    if factor != 1.0:
        limitations.append(
            "Las cifras de ambas fuentes están en distinta escala; el valor alineado "
            "se obtuvo multiplicando el de la segunda fuente por "
            f"{factor:g}."
        )
    return Contrast(
        status=ContrastStatus.MATCH,
        secondary_value=raw,
        aligned_secondary_value=aligned,
        inferred_unit_factor=factor,
        absolute_difference=abs(primary_value - aligned),
        relative_difference=rel_diff,
        reasons=[
            f"Coinciden dentro de la tolerancia {tolerance:.4%} con la relación de "
            f"unidad inferida ×{factor:g}."
        ],
        limitations=limitations,
        **base,
    )


def contrast_primary_document(
    *,
    period_start: date,
    period_end: date,
    html_value: Decimal,
    html_url: str,
    html_retrieval: date,
    accession: str,
    content_sha256: str,
    fiscal_year: int,
    companyfacts_value: Optional[Decimal],
    cik: int,
    fiscal_period: Optional[str] = None,
    companyfacts_retrieval: Optional[date] = None,
    concept: str = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    form: str = "10-K",
    html_from_cache: bool = False,
    tolerance: float = 0.0,
) -> Contrast:
    """Contrasta el valor extraído del HTML primario con el de CompanyFacts.

    Son dos formatos de la MISMA presentación: la coincidencia valida la extracción
    del documento original y no una fuente independiente, y así queda escrito en las
    limitaciones. Si CompanyFacts no publica el periodo, el resultado es
    `INCOMPARABLE`: no se compara con otro ejercicio ni se rellena con cero.
    """

    primary_value = float(html_value)
    secondary_value = (
        float(companyfacts_value) if companyfacts_value is not None else None
    )
    reference = (
        f"accession {accession} · formulario {form} · ejercicio fiscal {fiscal_year}"
        + (f" ({fiscal_period})" if fiscal_period else "")
        + f" · periodo {period_start.isoformat()}..{period_end.isoformat()}"
        + f" · concepto {concept}"
    )
    limitations: List[str] = [
        "El HTML iXBRL y la API CompanyFacts son dos formatos de la misma "
        "presentación de la SEC: la coincidencia valida la extracción del documento "
        "original, no una medición independiente.",
        "El SHA-256 fija los bytes exactos leídos; si el documento cambiara, "
        "cambiaría el hash y la verificación tendría que repetirse.",
    ]
    if html_from_cache:
        limitations.append(
            "El HTML procede de la caché local: la fecha de consulta es la del archivo "
            "guardado, no una descarga nueva de esta ejecución."
        )

    base = dict(
        metric="revenue",
        period_end=period_end,
        primary_value=primary_value,
        secondary_value=secondary_value,
        primary_currency="USD",
        primary_scale="units",
        primary_source="SEC EDGAR · documento HTML primario (Inline XBRL)",
        primary_url=html_url,
        primary_retrieval=html_retrieval,
        primary_reference=reference,
        secondary_source="SEC EDGAR · API CompanyFacts (JSON)",
        secondary_url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json",
        secondary_retrieval=companyfacts_retrieval or html_retrieval,
        secondary_reference=f"periodo exacto {period_start.isoformat()}..{period_end.isoformat()}",
        secondary_currency="USD",
        tolerance=tolerance,
        accession=accession,
        content_sha256=content_sha256,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        form=form,
    )

    if companyfacts_value is None:
        return Contrast(
            status=ContrastStatus.INCOMPARABLE,
            reasons=[
                "CompanyFacts no publica ese periodo para el concepto: no hay con qué "
                "contrastar la cifra extraída del HTML."
            ],
            limitations=limitations
            + [
                "El valor del HTML queda extraído pero sin contraste: no se declara "
                "corroborado."
            ],
            **base,
        )

    rel_diff = _relative_difference(primary_value, secondary_value)
    matched = rel_diff <= tolerance
    reasons = [
        f"HTML {primary_value:,.0f} USD vs CompanyFacts {secondary_value:,.0f} USD · "
        f"diferencia relativa {rel_diff:.6%} con tolerancia {tolerance:.4%}."
    ]
    if matched:
        reasons.append(
            "El valor extraído del documento original coincide con la cifra que la API "
            "de la SEC publica para el mismo periodo y el mismo accession."
        )
    else:
        reasons.append(
            "Las dos representaciones del mismo documento no coinciden: hay que "
            "investigar la extracción antes de usar cualquiera de las dos cifras."
        )

    return Contrast(
        status=ContrastStatus.MATCH if matched else ContrastStatus.MISMATCH,
        absolute_difference=abs(primary_value - secondary_value),
        relative_difference=rel_diff,
        reasons=reasons,
        limitations=limitations,
        **base,
    )


@dataclass
class PriceEvidence:
    """Precio de cierre para una fecha concreta, con la comprobación entre fuentes."""

    symbol: str
    price_date: date
    close: float
    adjusted_close: Optional[float]
    status: ContrastStatus
    currency: str = "USD"
    is_adjusted: bool = False
    relative_difference: Optional[float] = None
    tolerance: float = 0.0
    primary_source: str = ""
    primary_url: Optional[str] = None
    primary_retrieval: Optional[date] = None
    secondary_source: str = ""
    secondary_url: Optional[str] = None
    secondary_retrieval: Optional[date] = None
    reasons: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)

    @property
    def provenance_level(self) -> ProvenanceLevel:
        if self.status is ContrastStatus.MATCH:
            return ProvenanceLevel.EXTERNAL_CORROBORATED
        return ProvenanceLevel.EXTERNAL_DOWNLOADED

    @property
    def usable_for_margin_of_safety(self) -> bool:
        return self.status is ContrastStatus.MATCH

    def summary(self) -> str:
        return {
            ContrastStatus.MATCH: "coincide con la segunda fuente",
            ContrastStatus.MISMATCH: "discrepancia con la segunda fuente",
            ContrastStatus.INCOMPARABLE: "no comparable con la segunda fuente",
        }[self.status]


def contrast_close_price(
    *,
    symbol: str,
    when: date,
    primary: object,
    primary_source_name: str,
    primary_url: Optional[str],
    primary_retrieval: Optional[date],
    secondary: NasdaqHistory,
    tolerance: float = DEFAULT_PRICE_TOLERANCE,
) -> PriceEvidence:
    """Compara el cierre sin ajustar de Yahoo con el Close/Last de Nasdaq.

    `primary` es un `PriceSeries` de `data.prices`. Se exige que ambos datos
    correspondan al mismo símbolo y a la misma fecha de negociación; si falta alguno,
    no se calcula precio utilizable.
    """

    from nexo_invest.data.prices import PriceSeries  # importación local: sin ciclo

    if not isinstance(primary, PriceSeries):
        raise TypeError("primary debe ser un PriceSeries")
    limitations: List[str] = [
        "Yahoo Finance y Nasdaq son agregadores: ninguno es el mercado oficial ni "
        "el SIP. La coincidencia comprueba dos distribuciones independientes, no el "
        "tape oficial.",
        "El cierre comparado es sin ajustar. Los ajustes por dividendo o desdoblamiento "
        "se aplican en momentos distintos según el proveedor.",
    ]

    def _fail(reason: str) -> PriceEvidence:
        return PriceEvidence(
            symbol=symbol,
            price_date=when,
            close=float("nan"),
            adjusted_close=None,
            status=ContrastStatus.INCOMPARABLE,
            primary_source=primary_source_name,
            primary_url=primary_url,
            primary_retrieval=primary_retrieval,
            secondary_source=f"Nasdaq · Close/Last · {secondary.ticker}",
            secondary_url=secondary.source.url if secondary.source else None,
            secondary_retrieval=(
                secondary.fetch.retrieved_at.date() if secondary.fetch else None
            ),
            reasons=[reason],
            limitations=limitations,
        )

    if primary.symbol.upper() != symbol.upper():
        return _fail(
            f"La fuente primaria devuelve {primary.symbol} cuando se pidió {symbol}."
        )
    if secondary.ticker.upper() != symbol.upper():
        return _fail(
            f"La segunda fuente devuelve {secondary.ticker} cuando se pidió {symbol}."
        )

    primary_close = primary.value_at(when, adjusted=False)
    primary_index = primary.index_at_or_before(when)
    if primary_index is None or primary.dates[primary_index] != when:
        return _fail(
            f"La fuente primaria no tiene sesión con fecha {when.isoformat()} "
            "(el dato más cercano es anterior y no se usa como si fuera ese día)."
        )
    primary_adjusted = primary.adjusted_closes[primary_index]

    secondary_close = secondary.close_on(when)
    if secondary_close is None:
        return _fail(
            f"La segunda fuente no publica sesión con fecha {when.isoformat()}."
        )

    rel_diff = _relative_difference(float(primary_close), secondary_close)
    status = ContrastStatus.MATCH if rel_diff <= tolerance else ContrastStatus.MISMATCH
    reasons = [
        (
            f"Coinciden dentro de la tolerancia {tolerance:.4%} "
            f"(diferencia relativa {rel_diff:.6%})."
            if status is ContrastStatus.MATCH
            else (
                f"Diferencia relativa {rel_diff:.6%} por encima de la tolerancia "
                f"{tolerance:.4%}: el cierre de las dos fuentes no coincide."
            )
        )
    ]
    if status is ContrastStatus.MATCH and abs(primary_adjusted - primary_close) > 1e-9:
        reasons.append(
            "El cierre ajustado de la fuente primaria difiere del sin ajustar en esa "
            "sesión; se compara el sin ajustar con el sin ajustar."
        )

    return PriceEvidence(
        symbol=symbol.upper(),
        price_date=when,
        close=float(primary_close),
        adjusted_close=float(primary_adjusted),
        status=status,
        currency=primary.currency,
        is_adjusted=False,
        relative_difference=rel_diff,
        tolerance=tolerance,
        primary_source=primary_source_name,
        primary_url=primary_url,
        primary_retrieval=primary_retrieval,
        secondary_source=f"Nasdaq · Close/Last · {secondary.ticker}",
        secondary_url=secondary.source.url if secondary.source else None,
        secondary_retrieval=(
            secondary.fetch.retrieved_at.date() if secondary.fetch else None
        ),
        reasons=reasons,
        limitations=limitations,
    )


def margin_of_safety(intrinsic_per_share: Optional[float], price: Optional[float]) -> Optional[float]:
    """Margen de seguridad = 1 − precio / valor intrínseco por acción.

    Definición declarada (Graham): fracción del valor intrínseco que el precio deja
    libre. Se devuelve None si falta alguno de los dos términos o si el valor
    intrínseco no es positivo: un valor por acción negativo o ausente no admite
    margen de seguridad, y forzarlo produciría un porcentaje sin sentido.
    """

    if intrinsic_per_share is None or price is None:
        return None
    if intrinsic_per_share <= 0 or price <= 0:
        return None
    return 1.0 - (price / intrinsic_per_share)


# -- informe ---------------------------------------------------------------------------


def _pct(value: Optional[float], digits: int = 2) -> str:
    return "no calculable" if value is None else f"{value * 100:.{digits}f} %"


def _money(value: Optional[float], currency: str = "USD") -> str:
    if value is None:
        return "no disponible"
    return f"{value:,.0f} {currency}"


def verification_markdown(
    *,
    entity_name: str,
    ticker: str,
    generated_at: str,
    revenue: Contrast,
    price: Optional[PriceEvidence],
    scenarios: Sequence[object],
    valuation_notes: Sequence[str],
    price_note: str,
    extra_notes: Sequence[str] = (),
) -> str:
    """Informe de verificación: contraste de datos + valoración con precio comprobado."""

    lines: List[str] = []
    lines.append(f"# Nexo Invest AI — Verificación de datos y valoración: {entity_name}")
    lines.append("")
    lines.append(f"**Generado:** {generated_at} · **Ticker:** {ticker}")
    lines.append("")
    lines.append(
        "**Naturaleza del documento:** comprobación reproducible de datos y "
        "sensibilidad de la valoración a supuestos. No es asesoramiento financiero ni "
        "recomendación de compra o venta."
    )
    lines.append("")

    # 1. contraste de ingresos
    lines.append("## 1. Contraste de ingresos: fuente primaria vs. segunda fuente")
    lines.append("")
    lines.append("| Campo | Fuente primaria | Segunda fuente |")
    lines.append("| --- | --- | --- |")
    lines.append(f"| Origen | {revenue.primary_source} | {revenue.secondary_source} |")
    lines.append(f"| URL | {revenue.primary_url or 'no registrada'} | {revenue.secondary_url or 'no registrada'} |")
    lines.append(
        f"| Fecha de consulta | {revenue.primary_retrieval} | {revenue.secondary_retrieval} |"
    )
    lines.append(f"| Periodo fiscal (cierre) | {revenue.period_end.isoformat()} | {revenue.period_end.isoformat()} |")
    lines.append(
        f"| Cifra | {_money(revenue.primary_value, revenue.primary_currency)} "
        f"({revenue.primary_scale}) | "
        + (
            _money(revenue.aligned_secondary_value, revenue.secondary_currency or 'USD')
            + f" (celda original {_money(revenue.secondary_value)}, unidad inferida ×"
            + (f"{revenue.inferred_unit_factor:g}" if revenue.inferred_unit_factor else "?")
            + ")"
            if revenue.aligned_secondary_value is not None
            else "sin cifra utilizable"
        )
        + " |"
    )
    lines.append(f"| Referencia | {revenue.primary_reference or '—'} | {revenue.secondary_reference or '—'} |")
    lines.append("")
    lines.append(f"**Resultado:** {revenue.summary()}.")
    lines.append("")
    for reason in revenue.reasons:
        lines.append(f"- {reason}")
    lines.append("")
    lines.append("Limitaciones de este contraste:")
    lines.append("")
    for limitation in revenue.limitations:
        lines.append(f"- {limitation}")
    lines.append("")

    # 2. precio
    lines.append("## 2. Precio de cierre verificado")
    lines.append("")
    if price is None or price.status is not ContrastStatus.MATCH:
        lines.append(
            "**No hay precio comprobado.** Sin dos fuentes que coincidan para la misma "
            "fecha no se presenta ningún precio como cierto y no se calcula margen de "
            "seguridad."
        )
        lines.append("")
        if price is not None:
            lines.append(f"Resultado del intento: {price.summary()}.")
            lines.append("")
            for reason in price.reasons:
                lines.append(f"- {reason}")
            lines.append("")
    else:
        lines.append("| Campo | Valor |")
        lines.append("| --- | --- |")
        lines.append(f"| Símbolo | {price.symbol} |")
        lines.append(f"| Fecha de negociación | {price.price_date.isoformat()} |")
        lines.append(f"| Cierre sin ajustar | {price.close:,.2f} {price.currency} |")
        lines.append(
            "| Cierre ajustado (misma sesión) | "
            + (f"{price.adjusted_close:,.2f} {price.currency}" if price.adjusted_close is not None else "no disponible")
            + " |"
        )
        lines.append(f"| Primera fuente | {price.primary_source} ({price.primary_url or 'sin URL'}) |")
        lines.append(
            f"| Fecha de consulta (primera) | {price.primary_retrieval} |"
        )
        lines.append(f"| Segunda fuente | {price.secondary_source} ({price.secondary_url or 'sin URL'}) |")
        lines.append(
            f"| Fecha de consulta (segunda) | {price.secondary_retrieval} |"
        )
        lines.append(f"| Diferencia relativa | {price.relative_difference:.6%} |")
        lines.append(f"| Resultado | {price.summary()} |")
        lines.append(f"| Nivel de procedencia | {price.provenance_level.value} |")
        lines.append("")
        for reason in price.reasons:
            lines.append(f"- {reason}")
        lines.append("")
        lines.append("Limitaciones del precio:")
        lines.append("")
        for limitation in price.limitations:
            lines.append(f"- {limitation}")
        lines.append("")

    # 3. valoración
    lines.append("## 3. Valoración por escenarios con el precio comprobado")
    lines.append("")
    if price is None or not price.usable_for_margin_of_safety:
        lines.append(
            "Sin precio comprobado no se presenta margen de seguridad ni margen de "
            "subida: la comparación sería inventada."
        )
        lines.append("")
    else:
        lines.append(
            f"Precio usado en la comparación: **{price.close:,.2f} {price.currency}** "
            f"({price.price_date.isoformat()}, cierre sin ajustar, coincidente en dos "
            "fuentes)."
        )
        lines.append("")
        lines.append(
            "**Fórmulas declaradas** (ninguna es una predicción):"
        )
        lines.append("")
        lines.append(
            "- Valor de empresa = Σ FCF proyectado / (1 + t)^t + valor terminal "
            "descontado (Gordon Growth: FCF_terminal = FCF_último × (1 + g) / (r − g))."
        )
        lines.append(
            "- Valor de patrimonio = valor de empresa − deuda neta (cuando la deuda neta "
            "está observada; si no, se declara y no se asume cero)."
        )
        lines.append("- Valor por acción = valor de patrimonio / acciones en circulación.")
        lines.append(
            "- Margen de subida = valor por acción / precio − 1."
        )
        lines.append(
            "- **Margen de seguridad = 1 − precio / valor por acción** (Graham). Solo se "
            "muestra con precio comprobado y valor por acción positivo."
        )
        lines.append("")
    if not scenarios:
        lines.append("No se ejecutó ninguna valoración. Motivos:")
        lines.append("")
        for note in valuation_notes or ["sin FCF utilizable"]:
            lines.append(f"- {note}")
        lines.append("")
    for scenario in scenarios:
        lines.append(scenario.markdown())
        lines.append("")
        per_share = getattr(scenario, "per_share_value", None)
        if per_share is not None and price is not None and price.usable_for_margin_of_safety:
            mofs = margin_of_safety(per_share, price.close)
            if mofs is None:
                lines.append("- **Margen de seguridad:** no calculable (valor por acción no positivo).")
            elif mofs < 0:
                lines.append(
                    f"- **Margen de seguridad:** {_pct(mofs)} — **negativo**, es decir: con "
                    "estos supuestos el precio supera el valor estimado por acción. No hay "
                    "margen de seguridad y, aun así, esto no es una recomendación de venta: "
                    "la cifra mide la sensibilidad a los supuestos, no el precio justo."
                )
            else:
                lines.append(
                    f"- **Margen de seguridad:** {_pct(mofs)} — fracción del valor estimado "
                    "que el precio deja libre, según la fórmula declarada."
                )
            lines.append("")
        elif per_share is None:
            lines.append(
                "- **Margen de seguridad:** no calculable (valor por acción ausente)."
            )
            lines.append("")
    if valuation_notes:
        lines.append("Notas de la valoración:")
        lines.append("")
        for note in valuation_notes:
            lines.append(f"- {note}")
        lines.append("")
    lines.append(
        "Los escenarios son sensibilidad a supuestos, no previsiones. El escenario base "
        "no es una predicción segura y este documento no recomienda comprar ni vender."
    )
    lines.append("")

    if extra_notes:
        lines.append("## 4. Comprobaciones adicionales")
        lines.append("")
        for note in extra_notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.append(f"Nota de procedencia del precio: {price_note}")
    return "\n".join(lines)


def primary_document_markdown(
    *,
    entity_name: str,
    ticker: str,
    generated_at: str,
    evidence: Contrast,
) -> str:
    """Informe de la verificación del documento primario (HTML vs CompanyFacts).

    Sigue la misma estructura que `verification_markdown`: cabecera, evidencia
    identificable, resultado con razones y limitaciones. Si la descarga falló, el
    estado sale explícitamente como `VERIFICACIÓN NO COMPLETADA`.
    """

    if evidence.primary_value is None:
        state = "VERIFICACIÓN NO COMPLETADA"
    elif evidence.status is ContrastStatus.MATCH:
        state = "VERIFICADA — el valor del HTML coincide con CompanyFacts"
    elif evidence.status is ContrastStatus.MISMATCH:
        state = "COMPLETADA CON DISCREPANCIA — no usar ninguna de las dos cifras sin investigar"
    else:
        state = "EXTRACCIÓN COMPLETADA — contraste con CompanyFacts pendiente"

    def _row(label: str, value: object) -> str:
        return f"| {label} | {value if value not in (None, '') else 'no disponible'} |"

    lines: List[str] = []
    lines.append(
        f"# Nexo Invest AI — Verificación del documento primario: {entity_name}"
    )
    lines.append("")
    lines.append(f"**Generado:** {generated_at} · **Ticker:** {ticker}")
    lines.append("")
    lines.append(f"**Estado:** {state}")
    lines.append("")
    lines.append(
        "**Naturaleza del documento:** comprobación reproducible de una descarga y de "
        "una extracción de datos. No es asesoramiento financiero ni recomendación."
    )
    lines.append("")

    lines.append("## 1. Evidencia de la descarga")
    lines.append("")
    lines.append("| Campo | Valor |")
    lines.append("| --- | --- |")
    lines.append(_row("URL", evidence.primary_url or "no disponible"))
    lines.append(_row("Accession", evidence.accession))
    lines.append(_row("SHA-256 del contenido", evidence.content_sha256))
    lines.append(
        _row(
            "Fecha de consulta",
            evidence.primary_retrieval.isoformat() if evidence.primary_retrieval else None,
        )
    )
    lines.append(_row("Formulario", evidence.form))
    lines.append(_row("Ejercicio fiscal", evidence.fiscal_year))
    lines.append(_row("Periodo fiscal", evidence.period_end.isoformat()))
    lines.append(_row("Referencia", evidence.primary_reference))
    lines.append("")

    lines.append("## 2. Cifras")
    lines.append("")
    lines.append("| Campo | Valor |")
    lines.append("| --- | --- |")
    lines.append(_row("Valor extraído del HTML", _money(evidence.primary_value)))
    lines.append(_row("Valor en CompanyFacts", _money(evidence.secondary_value)))
    lines.append(
        _row(
            "Diferencia relativa",
            None
            if evidence.relative_difference is None
            else f"{evidence.relative_difference:.6%}",
        )
    )
    lines.append(_row("Resultado", evidence.summary()))
    lines.append("")

    if evidence.reasons:
        lines.append("## 3. Detalle")
        lines.append("")
        for reason in evidence.reasons:
            lines.append(f"- {reason}")
        lines.append("")

    if evidence.limitations:
        lines.append("## 4. Limitaciones")
        lines.append("")
        for limitation in evidence.limitations:
            lines.append(f"- {limitation}")
        lines.append("")

    return "\n".join(lines)
