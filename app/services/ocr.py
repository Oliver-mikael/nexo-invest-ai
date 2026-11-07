"""Extracción local de datos de documentos, sin enviarlos a terceros.

- PDF con capa de texto: `pypdf`.
- Imágenes: Tesseract mediante `pytesseract` y Pillow.
- Si el binario de Tesseract no está instalado, se devuelve un error explícito;
  no se simula una extracción ni se envía el documento a un servicio externo.

La extracción es una *propuesta*. El endpoint que la usa no registra ningún
movimiento: el usuario revisa y confirma los campos en una segunda petición.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.errors import ApiError

AMOUNT_RE = r"([0-9][0-9.,]*)"
DATE_RE = re.compile(
    r"\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]20\d{2})\b"
)
CURRENCY_RE = re.compile(r"\b(USD|EUR|BOB|GBP|CHF|JPY|CAD|AUD|MXN|BRL|ARS|CLP|COP|PEN)\b")
SYMBOL_RE = re.compile(r"\b[A-Z]{1,5}(?:\.[A-Z]{1,3})?\b")
TYPE_PATTERNS = [
    ("sell", r"\b(venta|sold|sell|venta de)\b"),
    ("buy", r"\b(compra|bought|buy|purchase)\b"),
    ("dividend", r"\b(dividendo|dividend)\b"),
    ("fee", r"\b(comisi[oó]n|fee|commission)\b"),
    ("tax", r"\b(impuesto|tax|retenci[oó]n|withholding)\b"),
    ("deposit", r"\b(dep[oó]sito|deposit|ingreso)\b"),
    ("withdrawal", r"\b(retiro|withdrawal|extracci[oó]n)\b"),
]
STOPWORDS = {
    "THE",
    "AND",
    "FOR",
    "USD",
    "EUR",
    "BOB",
    "TOTAL",
    "NET",
    "DATE",
    "FECHA",
}


class OcrUnavailable(RuntimeError):
    pass


@dataclass
class Extraction:
    text: str
    engine: str
    fields: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text[:20000],
            "engine": self.engine,
            "fields": self.fields,
            "warnings": self.warnings,
            "review_required": True,
            "note": (
                "Datos propuestos por extracción local. Revisa y corrige antes de "
                "registrar el movimiento; nada se ha guardado todavía."
            ),
        }


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise OcrUnavailable("pypdf no está instalado en el servidor.") from exc
    reader = PdfReader(str(path))
    chunks = []
    for page in reader.pages[:20]:
        chunks.append(page.extract_text() or "")
    return "\n".join(chunks).strip()


def _read_image(path: Path) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise OcrUnavailable(
            "El OCR local requiere Pillow y pytesseract instalados."
        ) from exc
    try:
        image = Image.open(path)
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        try:
            return pytesseract.image_to_string(image, lang="spa+eng").strip()
        except pytesseract.TesseractError:
            return pytesseract.image_to_string(image, lang="eng").strip()
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailable(
            "Tesseract no está instalado en el servidor. Instala el binario "
            "«tesseract-ocr» (y el paquete de español) para habilitar el OCR local."
        ) from exc
    except Exception as exc:  # imagen corrupta o no soportada
        raise ApiError(422, "invalid_image", "No se pudo leer la imagen.") from exc


def _parse_iso_date(raw: str) -> Optional[str]:
    parts = re.split(r"[-/]", raw)
    if len(parts) != 3:
        return None
    try:
        if len(parts[0]) == 4:
            parsed = date(int(parts[0]), int(parts[1]), int(parts[2]))
        else:
            parsed = date(int(parts[2]), int(parts[1]), int(parts[0]))
    except ValueError:
        return None
    return parsed.isoformat()


def _decimal(raw: str) -> Optional[str]:
    cleaned = raw.strip().replace(" ", "")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return f"{value:.10f}".rstrip("0").rstrip(".")


def extract_fields(text: str) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    date_match = DATE_RE.search(text)
    if date_match:
        parsed = _parse_iso_date(date_match.group(1))
        if parsed:
            fields["movement_date"] = parsed
    currency_match = CURRENCY_RE.search(text.upper())
    if currency_match:
        fields["currency"] = currency_match.group(1)
    lowered = text.lower()
    for kind, pattern in TYPE_PATTERNS:
        if re.search(pattern, lowered):
            fields["movement_type"] = kind
            break

    def near(labels: str) -> Optional[str]:
        match = re.search(
            rf"(?:{labels})\s*[:#]?\s*(?:[A-Z]{{3}}\s*)?{AMOUNT_RE}",
            text,
            flags=re.IGNORECASE,
        )
        return _decimal(match.group(1)) if match else None

    for field_name, labels in {
        "quantity": r"cantidad|quantity|unidades|units|t[ií]tulos",
        "price": r"precio|price|precio unitario|unit price",
        "amount": r"importe|amount|total|monto",
        "fee": r"comisi[oó]n|fee|commission",
        "tax": r"impuesto|tax|retenci[oó]n|withholding",
    }.items():
        value = near(labels)
        if value is not None:
            fields[field_name] = value
    symbol_match = re.search(
        r"(?:s[ií]mbolo|symbol|ticker)\s*[:#]?\s*([A-Z][A-Z0-9.\-]{0,9})",
        text,
        flags=re.IGNORECASE,
    )
    if symbol_match:
        fields["symbol"] = symbol_match.group(1).upper()
    else:
        candidates = [
            token
            for token in SYMBOL_RE.findall(text)
            if token.upper() not in STOPWORDS and 1 < len(token) <= 6
        ]
        if len(candidates) == 1:
            fields["symbol"] = candidates[0].upper()
    return fields


def extract(path: Path, content_type: str) -> Extraction:
    suffix = path.suffix.lower()
    if content_type == "application/pdf" or suffix == ".pdf":
        text = _read_pdf(path)
        if not text:
            raise ApiError(
                422,
                "pdf_without_text",
                "El PDF no tiene capa de texto. Convierte la página a imagen para usar OCR.",
            )
        return Extraction(text=text, engine="pypdf", fields=extract_fields(text))
    if content_type.startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        text = _read_image(path)
        if not text:
            raise ApiError(
                422, "empty_extraction", "No se pudo extraer texto legible de la imagen."
            )
        return Extraction(
            text=text,
            engine="tesseract-local",
            fields=extract_fields(text),
            warnings=[
                "La extracción por OCR puede confundir dígitos y símbolos. "
                "Compara cada campo con el documento original."
            ],
        )
    raise ApiError(415, "unsupported_document", "Solo se admiten PDF, PNG, JPEG y WebP.")
