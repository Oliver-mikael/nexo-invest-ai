from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional


class Frequency(Enum):
    ANNUAL = "annual"
    QUARTERLY = "quarterly"
    TTM = "ttm"

    def is_annual(self) -> bool:
        return self is Frequency.ANNUAL

    def is_quarterly(self) -> bool:
        return self is Frequency.QUARTERLY

    def is_ttm(self) -> bool:
        return self is Frequency.TTM


class Scale(Enum):
    """Magnitud de la unidad reportada. Usada para evitar mezclar escalas sin
    transformación documentada."""

    REPORTED = "reported"
    THOUSANDS = "thousands"
    MILLIONS = "millions"
    UNITS = "units"
    BILLIONS = "billions"

    def to_millions_factor(self) -> float:
        return {
            Scale.REPORTED: 1.0,
            Scale.THOUSANDS: 1e-3,
            Scale.MILLIONS: 1.0,
            Scale.UNITS: 1e-6,
            Scale.BILLIONS: 1e3,
        }[self]

    @classmethod
    def from_str(cls, value: str) -> "Scale":
        try:
            return cls(value.lower())
        except ValueError:
            raise ValueError(f"Escala no soportada: {value}")


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    frequency: Frequency

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(
                f"Periodo invalido: inicio {self.start} despues de fin {self.end}"
            )


class Money:
    """Valor monetario con moneda, escala y etiqueta explicitas.

    La escala indica la magnitud de la unidad base usada en el numero. Ejemplo:
    Money(value=120.0, currency="USD", scale=Scale.MILLIONS) significa 120 millones.
    """

    def __init__(
        self,
        value: float,
        currency: str = "USD",
        scale: Scale | str = Scale.REPORTED,
        label: Optional[str] = None,
    ) -> None:
        if isinstance(scale, str):
            scale = Scale.from_str(scale)
        if value is None or (isinstance(value, float) and value != value):
            object.__setattr__(self, "value", float("nan"))
        else:
            object.__setattr__(self, "value", float(value))
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "scale", scale)
        object.__setattr__(self, "label", label)

    @property
    def is_missing(self) -> bool:
        return self.value != self.value

    def __bool__(self) -> bool:
        return not self.is_missing

    def to_scale(self, target: Scale) -> "Money":
        """Convierte el valor a otra escala compatible (misma moneda)."""
        if self.is_missing or target is self.scale:
            return Money(self.value, self.currency, target, self.label)
        factor = self.scale.to_millions_factor() / target.to_millions_factor()
        return Money(self.value * factor, self.currency, target, self.label)

    def __repr__(self) -> str:
        label = f" ({self.label})" if self.label else ""
        return (
            f"Money(value={self.value}{label}, currency={self.currency}, "
            f"scale={self.scale.value})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return (
            self.currency == other.currency
            and self.scale is other.scale
            and self.value == other.value
        )
