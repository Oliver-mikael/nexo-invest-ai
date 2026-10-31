"""Extracción local de hechos Inline XBRL (iXBRL) desde un documento HTML.

Este módulo **no descarga nada**: trabaja sobre bytes/texto ya presentes en el
workspace. La descarga automática queda fuera de alcance (ver `docs/KNOWN_ISSUES.md`).

Qué hace
--------

- Lee contextos `xbrli:context`: periodo de duración (`startDate`/`endDate`) o
  instantáneo (`instant`) y dimensiones (`xbrldi:explicitMember`/`typedMember` o la
  mera presencia de un `xbrli:segment`).
- Lee unidades `xbrli:unit` con una medida `xbrli:measure` simple.
- Lee hechos `ix:nonFraction`: concepto (`name`), contexto, unidad, texto, `scale`,
  `sign`, `format`, `xsi:nil` e id.
- Convierte el texto a `Decimal` en tres pasos explícitos y en este orden:
  transformación de `format` -> aplicar `scale` (10**scale) -> aplicar `sign`.
- Selecciona un hecho por concepto + periodo (+ unidad, + ausencia de dimensiones)
  y **nunca** elige "el primero que aparezca".

Alcance admitido (declarado)
----------------------------

- Transformaciones numéricas: `ixt:num-dot-decimal` (separador de miles `,` y
  decimal `.`), `ixt:num-comma-decimal` (separador de miles `.` y decimal `,`) y
  `ixt:numdash` (guión negativo al final). Todo otro `format` se **rechaza** con
  `UnsupportedFormatError`: no se intenta adivinar.
- Hechos sin `format`: solo se aceptan enteros (`500`, `-500`). Un texto con
  separadores o decimales sin `format` es ambiguo entre notaciones y se rechaza.
- Espacios y separadores no separables (U+00A0, U+202F, U+2007), zero-width
  (U+200B) y BOM (U+FEFF) se eliminan antes de interpretar; un espacio ASCII
  intermedio no se elimina y provoca rechazo explícito.
- `scale` ausente equivale a 0 (factor 1); `scale` negativo también está soportado.
- `sign="-"` niega el valor y `sign="+"` lo deja como está; cualquier otro valor
  de `sign` se rechaza.

Qué NO cubre (limitaciones)
---------------------------

- `ix:nonNumeric`, continuaciones (`ix:continuedAt`), etiquetas inline dentro de un
  hecho distintas del propio marcado (se concatena su texto).
- Unidades compuestas (`xbrli:divide`) y cualquier unidad no declarada: se rechazan.
- Marcado dentro de `<script>`/`<style>` (el analizador HTML de la stdlib no lo
  interpreta como etiquetas), entidades en CDATA y la representación canónica
  completa de XBRL.
- No es una validación XBRL: comprueba coherencia interna (contexto, unidad,
  formato, escala, signo, ambigüedad), no el esquema de la SEC.

Errores (distinciones obligatorias)
-----------------------------------

- `FactNotFoundError`: el concepto/periodo/unidad solicitado no tiene hecho.
- `InvalidFactError`: el hecho existe pero su dato no es interpretable (texto vacío,
  formato no soportado, unidad no resoluble, contexto referenciado ausente vía
  `UnknownContextError`, signo desconocido).
- `AmbiguousFactError`: más de un valor distinto para la misma selección.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Sequence, Tuple

REVENUE_CONCEPT = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
USD_MEASURE = "iso4217:USD"

# Transformaciones implementadas y probadas. Cualquier otra se rechaza.
SUPPORTED_FORMATS = frozenset(
    {
        "ixt:num-dot-decimal",
        "ixt:num-comma-decimal",
        "ixt:numdash",
    }
)

_DOT_DECIMAL_RE = re.compile(r"^-?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?$")
_COMMA_DECIMAL_RE = re.compile(r"^-?(?:\d{1,3}(?:\.\d{3})*|\d+)(?:,\d+)?$")
_INTEGER_RE = re.compile(r"^-?\d+$")

# Caracteres de formato (no separadores de miles): se eliminan siempre.
_NON_SEPARATOR_CHARS = "\u00a0\u202f\u2007\u200b\ufeff"


# --------------------------------------------------------------------------------------
# Errores
# --------------------------------------------------------------------------------------


class InlineXbrlError(ValueError):
    """Error base de la extracción Inline XBRL."""


class FactNotFoundError(InlineXbrlError):
    """No existe ningún hecho para el concepto/periodo/unidad solicitado."""


class InvalidFactError(InlineXbrlError):
    """El hecho existe pero su dato no es interpretable de forma segura."""


class UnknownContextError(InvalidFactError):
    """El hecho referencia un contexto que no está declarado en el documento."""


class UnsupportedFormatError(InvalidFactError):
    """Transformación `format` no implementada: se rechaza en lugar de adivinar."""


class AmbiguousFactError(InlineXbrlError):
    """Más de un valor distinto para la misma selección: no se elige ninguno."""


# --------------------------------------------------------------------------------------
# Modelo
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class XbrlContext:
    """Contexto `xbrli:context`: periodo y (si las hay) dimensiones."""

    id: str
    start: Optional[date]  # None en contextos instantáneos
    end: date
    is_instant: bool
    dimensions: Tuple[str, ...]

    @property
    def is_consolidated(self) -> bool:
        """Un contexto sin dimensiones describe la entidad consolidada."""
        return not self.dimensions

    def matches_period(self, period_start: date, period_end: date) -> bool:
        return self.start == period_start and self.end == period_end


@dataclass(frozen=True)
class InlineFact:
    """Hecho `ix:nonFraction` leído del HTML, todavía sin interpretar."""

    concept: str
    context_id: str
    unit_id: Optional[str]
    text: str
    scale: Optional[int]
    sign: Optional[str]
    format: Optional[str]
    is_nil: bool
    fact_id: Optional[str]
    position: int
    # `scale` presente pero no legible: se rechaza de forma explícita, no se
    # interpreta como factor 1.
    scale_error: bool = False


@dataclass(frozen=True)
class ResolvedFact:
    """Hecho seleccionado e interpretado, con su valor en `Decimal`."""

    concept: str
    fact_id: Optional[str]
    context_id: str
    period_start: Optional[date]
    period_end: date
    dimensions: Tuple[str, ...]
    unit_measure: Optional[str]
    raw_text: str
    scale: Optional[int]
    sign: Optional[str]
    format: Optional[str]
    value: Decimal

    @property
    def is_consolidated(self) -> bool:
        return not self.dimensions


@dataclass
class InlineXbrlDocument:
    """Documento iXBRL parseado: contextos, unidades y hechos."""

    contexts: Dict[str, XbrlContext] = field(default_factory=dict)
    units: Dict[str, Optional[str]] = field(default_factory=dict)
    facts: List[InlineFact] = field(default_factory=list)

    def facts_for(self, concept: str) -> List[InlineFact]:
        return [f for f in self.facts if f.concept == concept]


# --------------------------------------------------------------------------------------
# Lectura del HTML
# --------------------------------------------------------------------------------------


class _InlineXbrlParser(HTMLParser):
    """Analizador HTML de la stdlib orientado a iXBRL.

    `HTMLParser` convierte etiquetas y atributos a minúsculas (`contextRef` ->
    `contextref`), por lo que todas las claves se normalizan al leerlas.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.contexts: Dict[str, XbrlContext] = {}
        self.units: Dict[str, Optional[str]] = {}
        self.facts: List[InlineFact] = []
        self._fact_stack: List[Dict[str, Any]] = []
        self._ctx_stack: List[Dict[str, Any]] = []
        self._date_target: Optional[Dict[str, Any]] = None
        self._date_field: Optional[str] = None
        self._dim_target: Optional[Dict[str, Any]] = None
        self._unit_stack: List[Dict[str, Any]] = []
        self._measure_target: Optional[Dict[str, Any]] = None
        self._position = 0

    # -- helpers ------------------------------------------------------------------------

    @staticmethod
    def _attrs(attrs: Sequence[Tuple[str, Optional[str]]]) -> Dict[str, str]:
        return {k.lower(): v for k, v in attrs if v is not None}

    def _current_ctx(self) -> Optional[Dict[str, Any]]:
        return self._ctx_stack[-1] if self._ctx_stack else None

    def _current_unit(self) -> Optional[Dict[str, Any]]:
        return self._unit_stack[-1] if self._unit_stack else None

    # -- eventos ------------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        data = self._attrs(attrs)

        if tag == "ix:nonfraction":
            scale_text = data.get("scale")
            scale: Optional[int] = None
            scale_error = False
            if scale_text is not None:
                try:
                    scale = int(scale_text)
                except ValueError:
                    # `scale` presente pero ilegible: no se asume factor 1.
                    scale_error = True
            self._fact_stack.append(
                {
                    "concept": data.get("name", ""),
                    "context_id": data.get("contextref", ""),
                    "unit_id": data.get("unitref"),
                    "scale": scale,
                    "scale_error": scale_error,
                    "sign": data.get("sign"),
                    "format": data.get("format"),
                    "is_nil": data.get("xsi:nil", "").lower() == "true",
                    "fact_id": data.get("id"),
                    "text": [],
                }
            )
        elif tag == "xbrli:context":
            self._ctx_stack.append(
                {
                    "id": data.get("id", ""),
                    "start": None,
                    "end": None,
                    "instant": False,
                    "dimensions": [],
                    "segment": False,
                }
            )
        elif tag in ("xbrli:startdate", "xbrli:enddate", "xbrli:instant"):
            self._date_target = self._current_ctx()
            self._date_field = {
                "xbrli:startdate": "start",
                "xbrli:enddate": "end",
                "xbrli:instant": "end",
            }[tag]
            if tag == "xbrli:instant" and self._date_target is not None:
                self._date_target["instant"] = True
        elif tag == "xbrli:segment":
            ctx = self._current_ctx()
            if ctx is not None:
                ctx["segment"] = True
        elif tag in ("xbrldi:explicitmember", "xbrldi:typedmember"):
            ctx = self._current_ctx()
            if ctx is not None:
                dimensions = ctx["dimensions"]
                assert isinstance(dimensions, list)
                dimensions.append(f"{data.get('dimension', '?')}=?")
                self._dim_target = ctx
        elif tag == "xbrli:unit":
            self._unit_stack.append({"id": data.get("id", ""), "measures": [], "divide": False})
        elif tag == "xbrli:measure":
            self._measure_target = self._current_unit()
        elif tag == "xbrli:divide":
            unit = self._current_unit()
            if unit is not None:
                unit["divide"] = True

    def handle_startendtag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        # Un hecho autocontenido (`<ix:nonFraction .../>`) no tendrá etiqueta final.
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag == "ix:nonfraction":
            if not self._fact_stack:
                return
            record = self._fact_stack.pop()
            text_parts = record.get("text")
            self.facts.append(
                InlineFact(
                    concept=str(record.get("concept", "")),
                    context_id=str(record.get("context_id", "")),
                    unit_id=record.get("unit_id"),
                    text="".join(text_parts) if isinstance(text_parts, list) else "",
                    scale=record.get("scale"),
                    scale_error=bool(record.get("scale_error")),
                    sign=record.get("sign"),
                    format=record.get("format"),
                    is_nil=bool(record.get("is_nil")),
                    fact_id=record.get("fact_id"),
                    position=self._position,
                )
            )
            self._position += 1
        elif tag == "xbrli:context":
            if not self._ctx_stack:
                return
            record = self._ctx_stack.pop()
            self._date_target = None
            self._date_field = None
            self._dim_target = None
            raw_start = record.get("start")
            raw_end = record.get("end")
            if raw_end is None:
                return  # contexto sin periodo: se ignora y cualquier uso dará error
            try:
                end = date.fromisoformat(str(raw_end).strip())
                start = date.fromisoformat(str(raw_start).strip()) if raw_start else None
            except ValueError:
                return
            raw_dimensions = record.get("dimensions")
            dimensions = [str(d) for d in raw_dimensions] if isinstance(raw_dimensions, list) else []
            if record.get("segment") and not dimensions:
                dimensions = ["xbrli:segment"]
            context_id = str(record.get("id", ""))
            if not context_id:
                return
            self.contexts[context_id] = XbrlContext(
                id=context_id,
                start=start,
                end=end,
                is_instant=bool(record.get("instant")),
                dimensions=tuple(dimensions),
            )
        elif tag == "xbrli:measure":
            self._measure_target = None
        elif tag == "xbrli:unit":
            if not self._unit_stack:
                return
            unit = self._unit_stack.pop()
            raw_measures = unit.get("measures")
            measures = (
                [str(m) for m in raw_measures if m] if isinstance(raw_measures, list) else []
            )
            unit_id = str(unit.get("id", ""))
            if not unit_id:
                return
            if unit.get("divide") or len(measures) != 1:
                self.units[unit_id] = None  # unidad compuesta: no soportada
            else:
                self.units[unit_id] = measures[0]
        elif tag in ("xbrli:startdate", "xbrli:enddate", "xbrli:instant"):
            self._date_target = None
            self._date_field = None
        elif tag in ("xbrldi:explicitmember", "xbrldi:typedmember"):
            self._dim_target = None

    def handle_data(self, data: str) -> None:
        if self._fact_stack:
            record = self._fact_stack[-1]
            text = record.get("text")
            if isinstance(text, list):
                text.append(data)
            return
        if self._dim_target is not None:
            dimensions = self._dim_target.get("dimensions")
            if isinstance(dimensions, list) and dimensions:
                member = str(dimensions[-1]).replace("?", data.strip() or "?")
                dimensions[-1] = member
            return
        if self._date_target is not None and self._date_field is not None:
            current = self._date_target.get(self._date_field)
            self._date_target[self._date_field] = (
                data if current is None else f"{current}{data}"
            )
            return
        if self._measure_target is not None:
            measures = self._measure_target.get("measures")
            if isinstance(measures, list):
                measures.append(data.strip())


# --------------------------------------------------------------------------------------
# API pública
# --------------------------------------------------------------------------------------


def document_sha256(raw: bytes) -> str:
    """SHA-256 de los bytes exactos del documento."""
    return hashlib.sha256(raw).hexdigest()


def parse_document(html: str) -> InlineXbrlDocument:
    """Parsea un documento iXBRL en memoria.

    El parseo es estructural: no interpreta valores. La interpretación y todos los
    rechazos (formato, texto, unidad, ambigüedad) ocurren en la selección.
    """
    parser = _InlineXbrlParser()
    parser.feed(html)
    parser.close()
    document = InlineXbrlDocument(
        contexts=parser.contexts, units=parser.units, facts=parser.facts
    )
    if not document.contexts and not document.facts:
        raise InvalidFactError(
            "El contenido no parece un documento Inline XBRL "
            "(0 contextos y 0 hechos ix:nonFraction)"
        )
    return document


def _clean_text(text: str) -> str:
    """Elimina separadores no separables y espacios externos, sin reinterpretar."""
    for char in _NON_SEPARATOR_CHARS:
        text = text.replace(char, "")
    return text.strip(" \t\r\n")


def resolve_number(
    text: str,
    *,
    scale: Optional[int],
    sign: Optional[str],
    format: Optional[str],
    fact_id: Optional[str] = None,
) -> Decimal:
    """Interpreta el texto de un hecho como `Decimal`, en tres pasos explícitos.

    Pasos: transformación `format` -> `scale` -> `sign`. Cualquier entrada no
    soportada lanza `InvalidFactError` (o `UnsupportedFormatError` para formatos
    no implementados); nunca se adivina.
    """
    reference = f" (hecho {fact_id})" if fact_id else ""

    if format is not None and format not in SUPPORTED_FORMATS:
        raise UnsupportedFormatError(f"Formato no soportado: {format}{reference}")

    cleaned = _clean_text(text)
    if not cleaned:
        raise InvalidFactError(f"Hecho sin valor numérico{reference}")

    if format is None:
        if not _INTEGER_RE.match(cleaned):
            raise InvalidFactError(
                f"Texto {cleaned!r} sin `format`: solo se aceptan enteros{reference}"
            )
    elif format == "ixt:num-comma-decimal":
        if not _COMMA_DECIMAL_RE.match(cleaned):
            raise InvalidFactError(
                f"Texto {cleaned!r} no válido para ixt:num-comma-decimal{reference}"
            )
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:  # ixt:num-dot-decimal e ixt:numdash
        # El guión final solo lo admite ixt:numdash: en el resto es un rechazo.
        trailing_dash = format == "ixt:numdash" and cleaned.endswith("-")
        if trailing_dash:
            cleaned = cleaned[:-1]
        if not _DOT_DECIMAL_RE.match(cleaned):
            raise InvalidFactError(
                f"Texto {cleaned!r} no válido para {format}{reference}"
            )
        cleaned = cleaned.replace(",", "")  # separador de miles en notación con punto
        if trailing_dash and sign is not None and sign != "-":
            raise InvalidFactError(
                f"Guión final y signo {sign!r} incompatibles{reference}"
            )
        if trailing_dash and sign is None:
            sign = "-"  # el guión final ya expresa el signo negativo

    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:  # defensa ante textos que pasan el regex
        raise InvalidFactError(f"Valor no interpretable: {cleaned!r}{reference}") from exc

    if scale is not None:
        value = value * (Decimal(10) ** scale)

    if sign == "-":
        value = -value
    elif sign is not None and sign != "+":
        raise InvalidFactError(f"Valor de `sign` no soportado: {sign!r}{reference}")

    return value


def _fact_value(fact: InlineFact) -> Decimal:
    if fact.is_nil:
        raise InvalidFactError(f"El hecho {fact.fact_id} está a nil: no tiene valor")
    if fact.scale_error:
        raise InvalidFactError(
            f"Atributo scale no interpretable en el hecho {fact.fact_id or '?'}"
        )
    return resolve_number(
        fact.text,
        scale=fact.scale,
        sign=fact.sign,
        format=fact.format,
        fact_id=fact.fact_id,
    )


def select_fact(
    document: InlineXbrlDocument,
    *,
    concept: str,
    period_start: date,
    period_end: date,
    unit_measure: Optional[str] = None,
    require_no_dimensions: bool = True,
) -> ResolvedFact:
    """Selecciona el hecho de un concepto para un periodo concreto.

    Reglas, en orden:

    1. El concepto tiene que existir en el documento (`FactNotFoundError`).
    2. Contexto referenciado ausente -> `UnknownContextError`.
    3. El periodo tiene que coincidir exactamente y, si `require_no_dimensions`, el
       contexto tiene que ser el consolidado (sin dimensiones).
    4. Si se pide unidad, todos los candidatos tienen que tenerla resoluble.
    5. Los hechos `xsi:nil` se excluyen: no aportan valor.
    6. Cualquier candidato no interpretable -> `InvalidFactError` (no se ignora).
    7. Más de un valor distinto -> `AmbiguousFactError` (no se elige ninguno).

    Nunca se devuelve "el primer hecho encontrado" sin pasar todas las reglas.
    """
    matching = document.facts_for(concept)
    if not matching:
        raise FactNotFoundError(f"Concepto ausente en el documento: {concept}")

    period_matched: List[Tuple[InlineFact, XbrlContext]] = []
    for fact in matching:
        context = document.contexts.get(fact.context_id)
        if context is None:
            raise UnknownContextError(
                f"El hecho {fact.fact_id or '?'} referencia un contexto inexistente: "
                f"{fact.context_id or '(sin contexto)'}"
            )
        if not context.matches_period(period_start, period_end):
            continue
        if require_no_dimensions and context.dimensions:
            continue
        period_matched.append((fact, context))

    if not period_matched:
        contexts = {
            document.contexts[f.context_id].id: document.contexts[f.context_id]
            for f in matching
            if f.context_id in document.contexts
        }
        available = sorted(
            (
                f"{c.start.isoformat()}..{c.end.isoformat()}"
                if c.start is not None
                else f"instantáneo {c.end.isoformat()}"
            )
            + (" (con dimensiones)" if c.dimensions else "")
            for c in contexts.values()
        )
        raise FactNotFoundError(
            f"Ningún hecho de {concept} para {period_start.isoformat()}.."
            f"{period_end.isoformat()}"
            + (" sin dimensiones" if require_no_dimensions else "")
            + f". Periodos presentes: {', '.join(available) or 'ninguno'}"
        )

    candidates = period_matched
    if unit_measure is not None:
        unit_matched: List[Tuple[InlineFact, XbrlContext]] = []
        for fact, context in candidates:
            if fact.unit_id is None:
                raise InvalidFactError(
                    f"El hecho {fact.fact_id or '?'} no declara unidad"
                )
            resolved_unit = document.units.get(fact.unit_id)
            if resolved_unit is None:
                if fact.unit_id in document.units:
                    raise InvalidFactError(
                        f"Unidad compuesta no soportada en el hecho "
                        f"{fact.fact_id or '?'} ({fact.unit_id})"
                    )
                raise InvalidFactError(
                    f"Unidad no declarada en el documento: {fact.unit_id} "
                    f"(hecho {fact.fact_id or '?'})"
                )
            if resolved_unit == unit_measure:
                unit_matched.append((fact, context))
        if not unit_matched:
            declared = sorted(
                {document.units.get(f.unit_id, "?") or "?" for f, _ in candidates}
            )
            raise FactNotFoundError(
                f"Ningún hecho de {concept} con unidad {unit_measure}; "
                f"las unidades disponibles en los candidatos son: "
                f"{', '.join(declared)}"
            )
        candidates = unit_matched

    valued = [(fact, context) for fact, context in candidates if not fact.is_nil]
    if not valued:
        raise FactNotFoundError(
            f"Los hechos de {concept} para el periodo solicitado están a xsi:nil: "
            "no aportan valor"
        )

    values: Dict[Decimal, List[InlineFact]] = {}
    for fact, context in valued:
        try:
            value = _fact_value(fact)
        except InlineXbrlError as exc:
            raise InvalidFactError(str(exc)) from exc
        values.setdefault(value, []).append(fact)

    if len(values) > 1:
        detail = "; ".join(
            f"{value} (hechos {', '.join(f.fact_id or '?' for f in facts)})"
            for value, facts in sorted(values.items(), key=lambda item: item[0])
        )
        raise AmbiguousFactError(
            f"{len(values)} valores distintos para {concept}: {detail}. "
            "No se selecciona ninguno."
        )

    fact, context = valued[0]
    return ResolvedFact(
        concept=fact.concept,
        fact_id=fact.fact_id,
        context_id=context.id,
        period_start=context.start,
        period_end=context.end,
        dimensions=context.dimensions,
        unit_measure=document.units.get(fact.unit_id) if fact.unit_id else None,
        raw_text=fact.text,
        scale=fact.scale,
        sign=fact.sign,
        format=fact.format,
        value=next(iter(values)),
    )


def extract_annual_revenue(
    document: InlineXbrlDocument,
    *,
    period_start: date,
    period_end: date,
    concept: str = REVENUE_CONCEPT,
    unit_measure: str = USD_MEASURE,
) -> ResolvedFact:
    """Ingreso anual consolidado (contexto sin dimensiones) para un ejercicio.

    El periodo se declara siempre de forma explícita: no se infiere el año fiscal
    ni se acepta el primer hecho del concepto.
    """
    return select_fact(
        document,
        concept=concept,
        period_start=period_start,
        period_end=period_end,
        unit_measure=unit_measure,
        require_no_dimensions=True,
    )
