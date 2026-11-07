"""Comprobación determinista de cifras en el texto generado por IA.

Los modelos no son la fuente de verdad: el expediente (`evidence_ledger`) sí. Este
módulo extrae las cifras del texto y marca las que no pueden rastrearse hasta una
cifra del expediente, para que el informe las muestre como no respaldadas en lugar
de presentarlas como hechos.

No es un corrector semántico: es un filtro de trazabilidad numérica explícito y
reproducible, con tolerancias declaradas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence

YEAR_RE = re.compile(r"^(19|20)\d{2}$")
NUMBER_RE = re.compile(r"[-+]?\d[\d.,]*")
PERCENT_HINT = "%"


@dataclass
class UnsupportedNumber:
    raw: str
    value: float
    kind: str  # money | percent
    context: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "raw": self.raw,
            "value": self.value,
            "kind": self.kind,
            "context": self.context,
        }


def parse_number(raw: str) -> float | None:
    text = raw.strip().replace(" ", "")
    if not text:
        return None
    negative = text.startswith("-")
    text = text.lstrip("+-")
    if "," in text and "." in text:
        # Formato español: 1.234,56 -> 1234.56
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        parts = text.split(",")
        text = "".join(parts) if all(len(p) == 3 for p in parts[1:]) else text.replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value


def ledger_values(ledger: Sequence[Dict[str, Any]]) -> List[tuple[float, str]]:
    values: List[tuple[float, str]] = []
    for entry in ledger:
        raw = entry.get("value")
        if isinstance(raw, (int, float)):
            values.append((float(raw), str(entry.get("id", ""))))
    return values


def _matches(value: float, candidates: Iterable[tuple[float, str]], relative: float) -> str | None:
    for candidate, ident in candidates:
        if candidate == 0:
            if abs(value) < 1e-9:
                return ident
            continue
        if abs(value - candidate) / abs(candidate) <= relative:
            return ident
    return None


def find_unsupported_numbers(
    text: str,
    ledger: Sequence[Dict[str, Any]],
    *,
    extra_allowed: Sequence[float] = (),
) -> List[UnsupportedNumber]:
    """Cifras del texto que no aparecen (con tolerancia) en el expediente."""

    candidates = ledger_values(ledger)
    for value in extra_allowed:
        if isinstance(value, (int, float)):
            candidates.append((float(value), "allowed"))
    found: List[UnsupportedNumber] = []
    seen: set[tuple[float, str]] = set()
    for match in NUMBER_RE.finditer(text):
        raw = match.group(0).strip(" .,")
        if not raw or YEAR_RE.match(raw):
            continue
        value = parse_number(raw)
        if value is None:
            continue
        context = text[max(0, match.start() - 40) : match.end() + 40].replace("\n", " ")
        is_percent = PERCENT_HINT in text[match.end() : match.end() + 3]
        if is_percent:
            fraction = value / 100.0
            if _matches(fraction, candidates, 0.01) or _matches(value, candidates, 0.01):
                continue
            key = (round(value, 4), "percent")
            if key in seen:
                continue
            seen.add(key)
            found.append(UnsupportedNumber(raw=f"{raw}%", value=value, kind="percent", context=context))
            continue
        if abs(value) < 1000:
            continue  # años, conteos y tasas pequeñas no se auditan aquí
        if _matches(value, candidates, 0.02):
            continue
        key = (round(value, 2), "money")
        if key in seen:
            continue
        seen.add(key)
        found.append(UnsupportedNumber(raw=raw, value=value, kind="money", context=context))
    return found
