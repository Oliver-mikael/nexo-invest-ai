"""Importación CSV/XLSX con vista previa, mapeo y confirmación humana.

El fichero original no se guarda en esta fase: se procesa en memoria, se limita
su tamaño y solo se persisten las filas normalizadas de la vista previa. Ningún
movimiento se registra hasta que el usuario confirma la previsualización.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Instrument, RealAccount, RealMovement
from app.schemas import RealMovementCreate
from app.services.real_movements import canonical_dedupe_key, create_movement

MAX_BYTES = 5 * 1024 * 1024

ALIASES: Dict[str, List[str]] = {
    "date": ["fecha", "date", "fecha_operacion", "trade_date", "fecha_operación", "dia"],
    "type": ["tipo", "type", "operacion", "operation", "movimiento", "transaction_type"],
    "symbol": ["simbolo", "símbolo", "ticker", "symbol", "instrumento", "activo", "security"],
    "isin": ["isin", "codigo_isin", "código_isin"],
    "instrument_uid": ["instrument_uid", "uid", "id_instrumento"],
    "quantity": ["cantidad", "quantity", "units", "unidades", "titulos", "títulos"],
    "price": ["precio", "price", "precio_unitario", "unit_price"],
    "amount": ["importe", "amount", "monto", "total", "efectivo"],
    "fee": ["comision", "comisión", "fee", "commission", "comisiones"],
    "tax": ["impuesto", "tax", "impuestos", "retencion", "retención", "withholding"],
    "currency": ["moneda", "currency", "divisa", "ccy"],
    "fx_rate": ["cambio", "fx_rate", "tipo_cambio", "tipo de cambio", "fx"],
    "notes": ["notas", "notes", "descripcion", "descripción", "detalle"],
    "external_id": ["id", "external_id", "referencia", "reference", "operacion_id"],
    "market": ["mercado", "market", "bolsa", "exchange"],
}

TYPE_ALIASES = {
    "compra": "buy",
    "buy": "buy",
    "purchase": "buy",
    "venta": "sell",
    "sell": "sell",
    "sale": "sell",
    "dividendo": "dividend",
    "dividend": "dividend",
    "deposito": "deposit",
    "depósito": "deposit",
    "deposit": "deposit",
    "retiro": "withdrawal",
    "withdrawal": "withdrawal",
    "extraccion": "withdrawal",
    "extracción": "withdrawal",
    "comision": "fee",
    "comisión": "fee",
    "fee": "fee",
    "impuesto": "tax",
    "tax": "tax",
    "ajuste": "adjustment",
    "adjustment": "adjustment",
    "split": "split",
    "transferencia_entrada": "transfer_in",
    "transfer_in": "transfer_in",
    "transferencia_salida": "transfer_out",
    "transfer_out": "transfer_out",
}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _text(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _parse_decimal(value: Any, field: str) -> Decimal:
    raw = _text(value)
    if not raw:
        return Decimal("0")
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = re.sub(r"[^0-9,.\-]", "", raw)
    if cleaned in {"", "-", ".", ","}:
        raise ValueError(f"{field}: importe no válido")
    # En precios, cantidades y tipos de cambio un único separador es decimal.
    # En importes, "1.234" se interpreta como miles (formato es-*).
    allow_thousands = field in {"importe", "comisión", "impuesto"}
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if allow_thousands and len(parts) == 2 and len(parts[1]) == 3 and parts[0]:
            cleaned = cleaned.replace(",", "")
        else:
            cleaned = cleaned.replace(",", ".")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if allow_thousands and len(parts) == 2 and len(parts[1]) == 3 and parts[0]:
            cleaned = cleaned.replace(".", "")
    try:
        result = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"{field}: importe no válido") from exc
    return -result if negative else result


def _parse_date(value: Any, order: str = "dmy") -> date:
    raw = _text(value)
    if not raw:
        raise ValueError("fecha vacía")
    raw = raw.split("T")[0].split(" ")[0]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(raw, fmt).date()
            if "/" in raw or "-" in raw:
                parts = re.split(r"[/-]", raw)
                if len(parts) == 3 and len(parts[0]) <= 2 and len(parts[2]) == 4:
                    first, second = int(parts[0]), int(parts[1])
                    if first <= 12 and second <= 12 and first != second:
                        if order == "mdy" and fmt != "%m/%d/%Y":
                            continue
                        if order != "mdy" and fmt == "%m/%d/%Y":
                            continue
            return parsed
        except ValueError:
            continue
    raise ValueError(f"fecha no reconocida: {raw}")


def parse_tabular(filename: str, content: bytes) -> Tuple[List[str], List[Dict[str, Any]]]:
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xlsm")):
        try:
            from openpyxl import load_workbook
        except ImportError as exc:  # pragma: no cover - dependencia declarada
            raise ApiError(
                503, "xlsx_unavailable", "El soporte XLSX no está instalado en el servidor."
            ) from exc
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        sheet = workbook.active
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            raise ApiError(422, "empty_file", "El archivo no contiene filas.")
        headers = [_text(value) for value in rows[0]]
        records = []
        for values in rows[1:]:
            if not any(value is not None and _text(value) for value in values):
                continue
            records.append({headers[i]: values[i] for i in range(min(len(headers), len(values)))})
        return headers, records
    if lower.endswith((".csv", ".txt")):
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ApiError(422, "encoding", "No se pudo decodificar el archivo de texto.")
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        headers = [header for header in (reader.fieldnames or []) if header]
        records = [
            {key: value for key, value in row.items() if key is not None}
            for row in reader
            if any(_text(value) for value in row.values())
        ]
        return headers, records
    raise ApiError(
        415,
        "unsupported_file",
        "Formato no admitido. Usa CSV, TXT o XLSX.",
    )


def suggest_mapping(headers: Iterable[str]) -> Dict[str, str]:
    normalized = {_fold(header): header for header in headers}
    mapping: Dict[str, str] = {}
    for field, aliases in ALIASES.items():
        for alias in aliases:
            key = _fold(alias)
            if key in normalized and normalized[key] not in mapping.values():
                mapping[field] = normalized[key]
                break
    return mapping


def resolve_mapping(headers: Iterable[str], provided: Optional[Dict[str, str]]) -> Dict[str, str]:
    available = {header: header for header in headers}
    suggested = suggest_mapping(headers)
    if not provided:
        return suggested
    mapping = dict(suggested)
    for field, column in provided.items():
        if field not in ALIASES:
            raise ApiError(422, "invalid_mapping", f"Campo de mapeo desconocido: {field}")
        if column and column not in available:
            raise ApiError(
                422, "invalid_mapping", f"La columna «{column}» no existe en el archivo."
            )
        if column:
            mapping[field] = column
    if "date" not in mapping or "type" not in mapping:
        raise ApiError(
            422,
            "missing_mapping",
            "El archivo necesita al menos columnas de fecha y tipo de operación.",
        )
    return mapping


def _resolve_instrument(
    session: Session,
    *,
    uid: Optional[str],
    isin: Optional[str],
    symbol: Optional[str],
    market: Optional[str],
) -> Instrument:
    if uid:
        row = session.execute(select(Instrument).where(Instrument.uid == uid)).scalar_one_or_none()
        if row is None:
            raise ValueError(f"instrumento no encontrado: {uid}")
        return row
    if isin:
        row = session.execute(
            select(Instrument).where(Instrument.isin == isin.upper())
        ).scalar_one_or_none()
        if row is not None:
            return row
    if not symbol:
        raise ValueError("falta el símbolo o ISIN del instrumento")
    query = select(Instrument).where(Instrument.symbol == symbol.upper())
    if market:
        from app.models import Market

        query = query.join(Market).where(Market.code == market.upper())
    rows = session.execute(query).scalars().all()
    if not rows:
        raise ValueError(f"instrumento no encontrado: {symbol}")
    if len(rows) > 1:
        raise ValueError(
            f"el símbolo {symbol} existe en varios mercados; indica mercado o ISIN"
        )
    return rows[0]


def normalize_row(
    session: Session,
    account: RealAccount,
    raw: Dict[str, Any],
    mapping: Dict[str, str],
    *,
    date_order: str = "dmy",
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    errors: List[str] = []

    def value(field: str) -> str:
        column = mapping.get(field)
        return _text(raw.get(column)) if column else ""

    try:
        movement_date = _parse_date(value("date"), date_order)
    except ValueError as exc:
        errors.append(str(exc))
        movement_date = None
    kind_raw = _fold(value("type"))
    kind = TYPE_ALIASES.get(kind_raw)
    if kind is None:
        errors.append(f"tipo de operación no reconocido: {value('type') or '(vacío)'}")
    instrument = None
    if kind in {"buy", "sell", "dividend", "split", "transfer_in", "transfer_out"}:
        try:
            instrument = _resolve_instrument(
                session,
                uid=value("instrument_uid") or None,
                isin=value("isin") or None,
                symbol=value("symbol") or None,
                market=value("market") or None,
            )
        except ValueError as exc:
            errors.append(str(exc))
    try:
        quantity = _parse_decimal(value("quantity"), "cantidad")
        price = _parse_decimal(value("price"), "precio")
        amount = _parse_decimal(value("amount"), "importe")
        fee = _parse_decimal(value("fee") or "0", "comisión")
        tax = _parse_decimal(value("tax") or "0", "impuesto")
        fx_rate = _parse_decimal(value("fx_rate"), "tipo de cambio") if value("fx_rate") else None
    except ValueError as exc:
        errors.append(str(exc))
        quantity = price = amount = fee = tax = Decimal("0")
        fx_rate = None
    currency = value("currency").upper() or None
    if instrument is not None and currency is None:
        currency = instrument.currency
    if instrument is not None and currency and currency != instrument.currency:
        errors.append(
            f"la moneda {currency} no coincide con la del instrumento ({instrument.currency})"
        )
    effective_currency = currency or account.base_currency
    if effective_currency != account.base_currency and fx_rate is None:
        errors.append(
            "una operación en moneda distinta de la base requiere tipo de cambio (columna fx_rate)"
        )
    payload = {
        "movement_type": kind,
        "movement_date": movement_date.isoformat() if movement_date else None,
        "instrument_uid": instrument.uid if instrument else None,
        "quantity": str(quantity),
        "price": str(price),
        "amount": str(amount),
        "fee": str(fee),
        "tax": str(tax),
        "currency": currency,
        "fx_rate": None if fx_rate is None else str(fx_rate),
        "fx_date": movement_date.isoformat() if movement_date else None,
        "fx_source": "import" if fx_rate is not None else "",
        "external_id": value("external_id") or None,
        "transfer_cost_basis": None,
        "notes": value("notes"),
    }
    if kind in {"transfer_in", "transfer_out"} and instrument is not None:
        errors.append("los traspasos de valores requieren coste de adquisición; regístralos manualmente")
    try:
        model = RealMovementCreate(**payload)
        if model.movement_type in {"deposit", "withdrawal", "dividend", "fee", "tax"} and model.amount <= 0:
            errors.append("el importe debe ser positivo para este tipo")
        if model.movement_type in {"buy", "sell"} and model.quantity <= 0:
            errors.append("la cantidad debe ser positiva para compra o venta")
        if model.movement_type == "adjustment" and model.amount == 0:
            errors.append("el ajuste requiere importe")
    except Exception as exc:  # Pydantic ValidationError
        errors.append(str(exc).splitlines()[0])
    return payload, errors


def existing_keys(session: Session, account: RealAccount) -> set[str]:
    rows = session.execute(
        select(RealMovement.dedupe_key).where(
            RealMovement.account_id == account.id, RealMovement.dedupe_key.is_not(None)
        )
    ).all()
    return {row[0] for row in rows if row[0]}


def prepare_rows(
    session: Session,
    account: RealAccount,
    records: List[Dict[str, Any]],
    mapping: Dict[str, str],
    *,
    date_order: str = "dmy",
) -> List[Dict[str, Any]]:
    known = existing_keys(session, account)
    seen: set[str] = set()
    prepared: List[Dict[str, Any]] = []
    for index, raw in enumerate(records, start=2):
        payload, errors = normalize_row(
            session, account, raw, mapping, date_order=date_order
        )
        duplicate = False
        duplicate_reason = ""
        if payload and not errors:
            key = canonical_dedupe_key(
                movement_type=payload["movement_type"],
                movement_date=date.fromisoformat(payload["movement_date"]),
                instrument_uid=payload["instrument_uid"],
                quantity=Decimal(payload["quantity"]),
                price=Decimal(payload["price"]),
                amount=Decimal(payload["amount"]),
                fee=Decimal(payload["fee"]),
                tax=Decimal(payload["tax"]),
                currency=payload["currency"] or account.base_currency,
                external_id=payload["external_id"],
            )
            payload["dedupe_key"] = key
            if key in known:
                duplicate = True
                duplicate_reason = "ya existe un movimiento con los mismos datos"
            elif key in seen:
                duplicate = True
                duplicate_reason = "duplicado dentro del mismo archivo"
            seen.add(key)
        prepared.append(
            {
                "row": index,
                "raw": {str(key): _text(value) for key, value in raw.items()},
                "payload": payload,
                "errors": errors,
                "duplicate": duplicate,
                "duplicate_reason": duplicate_reason,
            }
        )
    return prepared


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def confirm_batch(
    session: Session,
    account: RealAccount,
    batch: Any,
    *,
    rows: Optional[List[Dict[str, Any]]] = None,
    allow_partial: bool = False,
) -> Dict[str, Any]:
    from app.models import utcnow

    source_rows = rows if rows is not None else batch.rows
    created: List[int] = []
    skipped = 0
    errors: List[Dict[str, Any]] = []
    for index, row in enumerate(source_rows, start=1):
        if row.get("errors"):
            errors.append({"row": row.get("row", index), "errors": row["errors"]})
            continue
        if row.get("duplicate"):
            skipped += 1
            continue
        payload_dict = row.get("payload") or row
        try:
            payload = RealMovementCreate(**payload_dict)
            movement = create_movement(
                session,
                account,
                payload,
                source="import",
                import_batch_id=batch.id,
            )
            created.append(movement.id)
        except ApiError as exc:
            errors.append({"row": row.get("row", index), "errors": [exc.message]})
        except Exception as exc:  # validación Pydantic y datos corruptos
            errors.append({"row": row.get("row", index), "errors": [str(exc).splitlines()[0]]})
    if errors and not allow_partial:
        raise ApiError(
            422,
            "import_has_errors",
            "La importación contiene filas inválidas. Corrígelas o confirma una importación parcial.",
            {"errors": errors[:50]},
        )
    batch.status = "confirmed"
    batch.confirmed_at = utcnow()
    return {
        "batch_id": batch.id,
        "created": len(created),
        "skipped_duplicates": skipped,
        "errors": errors,
        "movement_ids": created,
    }
