"""Adaptador ExchangeRate-API «Open Access» — segunda fuente de divisas.

Fuente verificada en vivo (2026-10-31): `https://open.er-api.com/v6/latest/{base}`.

Por qué este proveedor:

- Sin clave; refresco diario único (recomendación oficial: 1 petición/24 h).
- Cubre BOB. Devuelve `time_last_update_utc`, que se conserva como fecha real
  del dato, no como fecha de consulta.
- Límite: 429 con bloqueo de 20 minutos si se abusa. Usamos caché y TTL ≥1 h.

Términos (https://www.exchangerate-api.com/terms): atribución obligatoria,
caché propia permitida, **no redistribuir los datos** ni revenderlos como API.
Solo se almacena para uso interno de valoración.

Calidad: tasa diaria de mercado agregada → `close` y naturaleza `market`.
No es la tasa oficial de un banco central: en Bolivia NO se presenta como
oficial. Sirve para detectar divergencias frente a Frankfurter.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

from app.services.data.base import (
    FX_KIND_MARKET,
    FxObservation,
    ProviderDataError,
    Provenance,
    parse_decimal,
)
from app.services.data.http import HttpFetcher

BASE_URL = "https://open.er-api.com/v6/latest"


def _data_date(payload: Dict[str, Any]) -> date:
    raw = payload.get("time_last_update_utc")
    if isinstance(raw, str) and raw:
        try:
            parsed = parsedate_to_datetime(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.date()
        except (TypeError, ValueError):
            pass
    unix = payload.get("time_last_update_unix")
    if isinstance(unix, (int, float)) and not isinstance(unix, bool):
        return datetime.fromtimestamp(float(unix), tz=timezone.utc).date()
    raise ProviderDataError("ExchangeRate-API no indicó la fecha de los datos")


class ExchangeRateApiProvider:
    name = "erapi"
    category = "fx"
    website = "https://www.exchangerate-api.com"
    license_url = "https://www.exchangerate-api.com/terms"
    terms_url = "https://www.exchangerate-api.com/terms"
    limits = "1 petición/24 h recomendada; 429 con bloqueo de 20 min si se excede."
    supports_history = False

    def __init__(self, fetcher: HttpFetcher) -> None:
        self.fetcher = fetcher

    def fetch(
        self,
        base: str,
        quotes: Optional[List[str]] = None,
    ) -> List[FxObservation]:
        payload = self.fetcher.get_json(f"{BASE_URL}/{base.upper()}")
        if not isinstance(payload, dict):
            raise ProviderDataError("ExchangeRate-API devolvió una respuesta inesperada")
        if payload.get("result") != "success":
            raise ProviderDataError(
                f"ExchangeRate-API respondió error: {payload.get('error-type') or payload}"
            )
        rates = payload.get("rates")
        if not isinstance(rates, dict) or not rates:
            raise ProviderDataError("ExchangeRate-API no incluyó tasas")
        base_code = str(payload.get("base_code") or base).upper()
        wanted = {q.upper() for q in quotes} if quotes else None
        data_as_of = _data_date(payload)
        retrieved_at = datetime.now(timezone.utc)

        observations: List[FxObservation] = []
        for quote, value in rates.items():
            quote_code = str(quote).upper()
            if quote_code == base_code:
                continue
            if wanted is not None and quote_code not in wanted:
                continue
            observations.append(
                FxObservation(
                    base_currency=base_code,
                    quote_currency=quote_code,
                    rate=parse_decimal(value, field_name=f"rates.{quote_code}"),
                    as_of=data_as_of,
                    provenance=Provenance(
                        provider=self.name,
                        category="fx",
                        source_url=f"{BASE_URL}/{base_code}",
                        data_as_of=data_as_of,
                        retrieved_at=retrieved_at,
                        quality="close",
                        kind=FX_KIND_MARKET,
                        notes="tasa agregada de mercado; no es una tasa oficial de banco central",
                    ),
                )
            )
        if not observations:
            raise ProviderDataError(
                f"ExchangeRate-API no devolvió el par {base_code} solicitado"
            )
        return observations
