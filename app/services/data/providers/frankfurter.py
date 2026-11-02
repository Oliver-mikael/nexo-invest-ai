"""Adaptador Frankfurter v2 — divisas actuales e históricas.

Fuente verificada en vivo (2026-10-31): `https://api.frankfurter.dev/v2/rates`.

Por qué este proveedor:

- Sin clave, sin registro y sin cuota mensual; solo control anti-abuso.
- La v2 cubre 228 monedas y 106 proveedores oficiales, incluido BOB con el
  Banco Central de Bolivia. La v1 (solo BCE) no sirve para Bolivia.
- Símbolo `license_url`: MIT para el código; los datos mezclados son cálculo
  propio de Frankfurter y libres para uso comercial. Consultas a un proveedor
  concreto (`providers=...`) quedan sujetas a sus términos.
- No hay endpoint de timestamp: solo fecha de calendario (`date`). Se conserva
  como fecha del dato, jamás como instante.

Calidad: los datos son diarios, por eso `close`; nunca `realtime`. Si se pide
un proveedor concreto se marca `official` (el catálogo de Frankfurter son
bancos centrales y fuentes oficiales); la mezcla sin pinneado es `reference`.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.data.base import (
    FX_KIND_OFFICIAL,
    FX_KIND_REFERENCE,
    FxObservation,
    ProviderDataError,
    Provenance,
    parse_decimal,
    parse_iso_date,
)
from app.services.data.http import HttpFetcher

BASE_URL = "https://api.frankfurter.dev/v2"


class FrankfurterProvider:
    name = "frankfurter"
    category = "fx"
    website = "https://frankfurter.dev"
    license_url = "https://github.com/lineofflight/frankfurter/blob/main/LICENSE"
    terms_url = "https://frankfurter.dev"
    limits = "Sin cuota diaria ni clave; límite anti-abuso y 422 en rangos >5 años con `providers`."
    supports_history = True

    def __init__(self, fetcher: HttpFetcher) -> None:
        self.fetcher = fetcher

    def _kind(self, providers: Optional[List[str]]) -> str:
        return FX_KIND_OFFICIAL if providers else FX_KIND_REFERENCE

    def fetch(
        self,
        base: str,
        quotes: List[str],
        *,
        start: Optional[date] = None,
        end: Optional[date] = None,
        providers: Optional[List[str]] = None,
    ) -> List[FxObservation]:
        params: Dict[str, Any] = {"base": base.upper()}
        if quotes:
            params["quotes"] = ",".join(q.upper() for q in quotes)
        if start is not None:
            params["from"] = start.isoformat()
        if end is not None:
            params["to"] = end.isoformat()
        if providers:
            params["providers"] = ",".join(p.upper() for p in providers)

        payload = self.fetcher.get_json(f"{BASE_URL}/rates", params=params)
        if not isinstance(payload, list):
            message = payload.get("message") if isinstance(payload, dict) else str(payload)[:120]
            raise ProviderDataError(f"Frankfurter devolvió una respuesta inesperada: {message}")

        kind = self._kind(providers)
        provider_note = f"proveedor concreto: {','.join(p.upper() for p in providers)}" if providers else "mezcla de bancos centrales"
        retrieved_at = datetime.now(timezone.utc)
        observations: List[FxObservation] = []
        for row in payload:
            if not isinstance(row, dict):
                raise ProviderDataError("Fila de Frankfurter no esperada")
            row_base = str(row.get("base", "")).upper()
            row_quote = str(row.get("quote", "")).upper()
            if row_base == row_quote:
                continue  # fila de identidad que incluye v2
            observations.append(
                FxObservation(
                    base_currency=row_base,
                    quote_currency=row_quote,
                    rate=parse_decimal(row.get("rate"), field_name="rate"),
                    as_of=parse_iso_date(row.get("date"), field_name="date"),
                    provenance=Provenance(
                        provider=self.name,
                        category="fx",
                        source_url=f"{BASE_URL}/rates",
                        data_as_of=parse_iso_date(row.get("date"), field_name="date"),
                        retrieved_at=retrieved_at,
                        quality="close",
                        kind=kind,
                        notes=provider_note,
                    ),
                )
            )
        if not observations:
            raise ProviderDataError(
                f"Frankfurter no devolvió observaciones para {base.upper()} -> {quotes}"
            )
        return observations
