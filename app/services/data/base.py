"""Tipos comunes de la capa de datos de mercado (Fase 5).

Diseño:

- Los adaptadores devuelven observaciones normalizadas, jamás filas ORM.
- Toda observación lleva procedencia completa: proveedor, URL, fecha del dato y
  fecha de consulta. El motor contable nunca ve el proveedor crudo.
- Si un dato no es fiable, el adaptador lanza un error tipado; no rellena huecos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

# Calidades ya usadas por la plataforma. Se reutilizan sin cambiar el significado.
QUALITY_REALTIME = "realtime"
QUALITY_DELAYED = "delayed"
QUALITY_CLOSE = "close"
QUALITY_HISTORICAL = "historical"
QUALITY_ESTIMATED = "estimated"
QUALITIES = {
    QUALITY_REALTIME,
    QUALITY_DELAYED,
    QUALITY_CLOSE,
    QUALITY_HISTORICAL,
    QUALITY_ESTIMATED,
}

# Naturaleza de un tipo de cambio. En Bolivia conviven varias tasas: la que
# publica el banco central, la comercial y la de mercado. No se unifican.
FX_KIND_OFFICIAL = "official"
FX_KIND_MARKET = "market"
FX_KIND_REFERENCE = "reference"
FX_KIND_ESTIMATED = "estimated"
FX_KINDS = {FX_KIND_OFFICIAL, FX_KIND_MARKET, FX_KIND_REFERENCE, FX_KIND_ESTIMATED}

CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

# Calidades para datos no cotizados (fundamentos reportados, metadatos de
# noticias). No se usan nunca para precios ni tipos de cambio.
REPORT_QUALITIES = {"reported", "metadata"}
PROVENANCE_QUALITIES = QUALITIES | REPORT_QUALITIES


class DataError(RuntimeError):
    """Error base de la capa de datos."""


class ProviderUnavailable(DataError):
    """El proveedor no responde o devuelve 5xx: se puede reintentar más tarde."""


class ProviderTimeout(DataError):
    """El proveedor superó el tiempo límite."""


class ProviderRateLimited(DataError):
    """El proveedor limitó las peticiones (HTTP 429)."""


class ProviderDataError(DataError):
    """Respuesta inesperada o inválida: reintentar no arreglaría nada."""


class ProviderNotConfigured(DataError):
    """No hay proveedor configurado para esta categoría."""


def parse_decimal(value: Any, *, field_name: str = "valor") -> Decimal:
    """Convierte un decimal de JSON a `Decimal` sin pasar por `float`."""
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, bool) or value is None:
        raise ProviderDataError(f"El campo '{field_name}' no es numérico: {value!r}")
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        # Solo ocurre si el proveedor del adaptador parseó con float. Se usa str()
        # para no propagar el error binario en más cifras de las que hay.
        result = Decimal(str(value))
    elif isinstance(value, str):
        try:
            result = Decimal(value.strip())
        except Exception as exc:  # noqa: BLE001
            raise ProviderDataError(
                f"El campo '{field_name}' no es un decimal válido: {value!r}"
            ) from exc
    else:
        raise ProviderDataError(f"El campo '{field_name}' no es numérico: {value!r}")
    if not result.is_finite():
        raise ProviderDataError(f"El campo '{field_name}' no es finito: {value!r}")
    return result


def parse_iso_date(value: Any, *, field_name: str = "fecha") -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str) or len(value) < 10:
        raise ProviderDataError(f"El campo '{field_name}' no es una fecha ISO: {value!r}")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ProviderDataError(
            f"El campo '{field_name}' no es una fecha ISO válida: {value!r}"
        ) from exc


def validate_currency(code: Any) -> str:
    if not isinstance(code, str):
        raise ProviderDataError(f"Código de moneda inválido: {code!r}")
    normalized = code.strip().upper()
    if not CURRENCY_RE.match(normalized):
        raise ProviderDataError(f"Código de moneda inválido: {code!r}")
    return normalized


@dataclass(frozen=True)
class Provenance:
    """Procedencia completa de una observación obtenida de un proveedor."""

    provider: str
    category: str
    source_url: str
    data_as_of: date
    retrieved_at: datetime
    quality: str = QUALITY_CLOSE
    kind: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if self.quality not in PROVENANCE_QUALITIES:
            raise ProviderDataError(f"Calidad desconocida: {self.quality!r}")

    def public_view(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "category": self.category,
            "source_url": self.source_url,
            "data_as_of": self.data_as_of.isoformat(),
            "retrieved_at": self.retrieved_at.isoformat(),
            "quality": self.quality,
            "kind": self.kind,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class FxObservation:
    """Un tipo de cambio para un par y una fecha concretos."""

    base_currency: str
    quote_currency: str
    rate: Decimal
    as_of: date
    provenance: Provenance

    def __post_init__(self) -> None:
        base = validate_currency(self.base_currency)
        quote = validate_currency(self.quote_currency)
        object.__setattr__(self, "base_currency", base)
        object.__setattr__(self, "quote_currency", quote)
        if base == quote:
            raise ProviderDataError("Un par de divisas no puede ser base y cotización iguales")
        if self.rate <= 0:
            raise ProviderDataError(f"Tipo de cambio no positivo: {self.rate}")
        if self.provenance.quality not in QUALITIES:
            raise ProviderDataError("Calidad de tipo de cambio desconocida")


@dataclass(frozen=True)
class PriceBar:
    """Vela diaria en la moneda nativa del instrumento.

    `close` es el cierre sin ajustar (el que usa la valoración). `adjusted_close`
    solo existe cuando el proveedor lo suministra; nunca se sustituye uno por otro.
    """

    as_of: date
    open: Optional[Decimal]
    high: Optional[Decimal]
    low: Optional[Decimal]
    close: Decimal
    adjusted_close: Optional[Decimal]
    volume: Optional[Decimal]
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.close <= 0:
            raise ProviderDataError(f"Cierre no positivo: {self.close}")
        for name, value in (("open", self.open), ("high", self.high), ("low", self.low)):
            if value is not None and value < 0:
                raise ProviderDataError(f"El campo {name} no puede ser negativo: {value}")
        if self.adjusted_close is not None and self.adjusted_close <= 0:
            raise ProviderDataError(
                f"Cierre ajustado no positivo: {self.adjusted_close}"
            )


@dataclass(frozen=True)
class FundamentalObservation:
    """Fundamento reportado por el emisor, con periodo fiscal explícito."""

    instrument_id: int
    period_type: str  # annual | quarter
    fiscal_end: date
    fiscal_start: Optional[date]
    reported_at: Optional[date]
    currency: str
    source: str
    provenance: Provenance
    metrics: Dict[str, Optional[Decimal]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.period_type not in {"annual", "quarter"}:
            raise ProviderDataError(f"Tipo de periodo inválido: {self.period_type!r}")
        if self.currency and not CURRENCY_RE.match(self.currency):
            raise ProviderDataError(f"Moneda inválida: {self.currency!r}")


@dataclass(frozen=True)
class NewsObservation:
    """Metadato de noticia o evento: título, enlace y resumen corto, nunca el texto completo."""

    title: str
    external_id: str
    source: str
    category: str = "news"
    url: str = ""
    summary: str = ""
    published_at: Optional[datetime] = None
    instrument_id: Optional[int] = None


def dedupe_observations(items: List[Any]) -> List[Any]:
    """Elimina duplicados preservando el primer orden."""
    seen = set()
    result = []
    for item in items:
        key = (
            getattr(item, "base_currency", ""),
            getattr(item, "quote_currency", ""),
            getattr(item, "instrument_id", 0),
            getattr(item, "as_of", None),
            getattr(item, "fiscal_end", None),
            getattr(item, "external_id", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
