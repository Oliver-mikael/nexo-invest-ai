"""Adaptador StockAnalysis — precios históricos diarios multi-mercado.

Fuente verificada en vivo (2026-10-31):

    https://stockanalysis.com/api/symbol/s/{sym}/history?range=1Y&period=Daily[&exchange=etr]

Comprobaciones reales realizadas:

- `AAPL` sin `exchange` (EE. UU.) → 200 con OHLCV.
- `SAP` + `exchange=etr` (Alemania) → 200.
- `SAN` + `exchange=bme` (España) → 200.
- `VOD` + `exchange=lse` (Reino Unido) → 200.
- Símbolos con sufijo tipo `SAN.MC` → 400: NO se usan; se mapea por mercado.
- `WALMEX`/mercados LATAM sin cobertura → 400 → error explícito, sin inventar.

Columnas: `t` (fecha), `o/h/l/c` (cierre sin ajustar), `a` (cierre ajustado),
`v` (volumen). La semántica se conserva: la valoración usa `c` sin ajustar y
`a` se guarda aparte con identidad de fuente distinta.

Restricciones (sin documentación pública de API):

- API **no oficial** y sin clave; puede cambiar o requerir clave en el futuro.
- Asumido uso personal/no redistribución; se cachea localmente y no se
  reexpone a terceros. Para uso comercial hay que acordarlo con StockAnalysis.
- Cobertura limitada a US, Alemania, España y Reino Unido verificada. Cualquier
  otro mercado devuelve error explícito: jamás se sustituye por otro valor.
- Solo cierres diarios: calidad `close`, nunca `realtime`.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.services.data.base import (
    PriceBar,
    ProviderDataError,
    Provenance,
    parse_decimal,
    parse_iso_date,
)
from app.services.data.http import HttpFetcher

BASE_URL = "https://stockanalysis.com/api/symbol/s"

# MIC de mercado -> parámetro `exchange` de StockAnalysis. Vacío = mercado
# estadounidense, que funciona sin parámetro. Los mercados no listados no se
# soportan: se lanza ProviderDataError en lugar de adivinar.
EXCHANGE_BY_MIC: Dict[str, str] = {
    "XNAS": "",
    "XNYS": "",
    "XASE": "",
    "ARCX": "",
    "XETR": "etr",
    "ETRA": "etr",
    "XFRA": "etr",
    "XLON": "lse",
    "XBME": "bme",
}
EXCHANGE_BY_COUNTRY: Dict[str, str] = {
    "US": "",
    "DE": "etr",
    "ES": "bme",
    "GB": "lse",
}

SUPPORTED_MARKETS = sorted({m for m in EXCHANGE_BY_MIC.values() if m} | {"us"})


def resolve_exchange(market_code: str, country_code: str) -> Optional[str]:
    """Devuelve el parámetro `exchange`, `None` si el mercado es EE. UU.

    Lanza `ProviderDataError` si el mercado no está soportado.
    """
    mic = (market_code or "").upper()
    if mic in EXCHANGE_BY_MIC:
        return EXCHANGE_BY_MIC[mic]
    country = (country_code or "").upper()
    if country in EXCHANGE_BY_COUNTRY:
        return EXCHANGE_BY_COUNTRY[country]
    raise ProviderDataError(
        f"El mercado '{market_code or country_code}' no está soportado por el "
        f"proveedor de precios (soportados: US, DE, ES, GB). No se sustituye por "
        f"otro mercado."
    )


def _range_param(start: Optional[date], end: Optional[date]) -> str:
    if start is None:
        return "1Y"
    upper = end or date.today()
    span = max(1, (upper - start).days)
    if span <= 10:
        return "5D"
    if span <= 45:
        return "1M"
    if span <= 400:
        return "1Y"
    if span <= 1900:
        return "5Y"
    return "MAX"


class StockAnalysisProvider:
    name = "stockanalysis"
    category = "prices"
    website = "https://stockanalysis.com"
    license_url = "https://stockanalysis.com/terms/"
    terms_url = "https://stockanalysis.com/terms/"
    limits = "API no oficial sin clave; caché local recomendada; cobertura verificada US/DE/ES/GB; solo cierres diarios."
    supports_history = True

    def __init__(self, fetcher: HttpFetcher) -> None:
        self.fetcher = fetcher

    def fetch_history(
        self,
        symbol: str,
        *,
        market_code: str,
        country_code: str,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> List[PriceBar]:
        exchange = resolve_exchange(market_code, country_code)
        params: Dict[str, str] = {
            "range": _range_param(start, end),
            "period": "Daily",
        }
        if exchange:
            params["exchange"] = exchange

        url = f"{BASE_URL}/{symbol.strip().upper()}/history"
        payload = self.fetcher.get_json(url, params=params)
        if not isinstance(payload, dict) or payload.get("status") not in (200, "200", None):
            message = payload.get("message") if isinstance(payload, dict) else str(payload)[:120]
            raise ProviderDataError(
                f"StockAnalysis devolvió un estado inesperado para "
                f"{symbol}: {message}"
            )
        rows = payload.get("data")
        if not isinstance(rows, list) or not rows:
            raise ProviderDataError(
                f"StockAnalysis no devolvió histórico para {symbol} "
                f"(mercado {market_code or country_code})"
            )

        retrieved_at = datetime.now(timezone.utc)
        bars: List[PriceBar] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ProviderDataError("Fila de precios inesperada de StockAnalysis")
            as_of = parse_iso_date(row.get("t"), field_name="t")
            if start is not None and as_of < start:
                continue
            if end is not None and as_of > end:
                continue
            adjusted_raw = row.get("a")
            bars.append(
                PriceBar(
                    as_of=as_of,
                    open=parse_decimal(row.get("o"), field_name="o") if row.get("o") is not None else None,
                    high=parse_decimal(row.get("h"), field_name="h") if row.get("h") is not None else None,
                    low=parse_decimal(row.get("l"), field_name="l") if row.get("l") is not None else None,
                    close=parse_decimal(row.get("c"), field_name="c"),
                    adjusted_close=(
                        parse_decimal(adjusted_raw, field_name="a")
                        if adjusted_raw is not None
                        else None
                    ),
                    volume=parse_decimal(row.get("v"), field_name="v") if row.get("v") is not None else None,
                    provenance=Provenance(
                        provider=self.name,
                        category="prices",
                        source_url=url,
                        data_as_of=as_of,
                        retrieved_at=retrieved_at,
                        quality="close",
                        kind="",
                        notes="cierre diario; no es tiempo real",
                    ),
                )
            )
        if not bars:
            raise ProviderDataError(
                f"El rango solicitado para {symbol} no contiene sesiones válidas"
            )
        bars.sort(key=lambda bar: bar.as_of, reverse=True)
        return bars

    def fetch_recent(
        self,
        symbol: str,
        *,
        market_code: str,
        country_code: str,
    ) -> Tuple[PriceBar, date]:
        """Último cierre disponible. Devuelve (vela, fecha real del dato)."""
        bars = self.fetch_history(
            symbol,
            market_code=market_code,
            country_code=country_code,
            start=date.today().replace(day=1),
            end=date.today(),
        )
        latest = bars[0]
        return latest, latest.as_of
