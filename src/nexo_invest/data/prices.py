"""Adaptador de precios de mercado (endpoint público de Yahoo Finance, sin clave).

Advertencia de procedencia, deliberadamente explícita:

- Yahoo Finance **no es una fuente oficial** de precios como lo es un mercado o un
  regulador. Es un endpoint público sin autenticación, cómodo para investigación,
  pero sin garantía contractual de exactitud ni de disponibilidad.
- Por eso toda serie descargada aquí queda en nivel `EXTERNAL_DOWNLOADED`: se
  descargó correctamente y nada más. No se marca como validada ni corroborada, y
  ninguna conclusión que dependa de ella puede presentarse como verificada.
- Se guarda el SHA-256 del contenido crudo, la URL, la fecha de consulta y el rango
  solicitado, de modo que una serie se puede reproducir o volver a comprobar.
- Si la descarga falla, se registra el error y no se devuelve ninguna serie: no se
  rellena el hueco con precios inventados ni con el último valor conocido.

Los precios usados para calcular rentabilidades son los **ajustados** (`adjclose`),
que incorporan dividendos y desdoblamientos. El precio de cierre sin ajustar se
conserva aparte porque es el que se compara con un valor por acción.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from nexo_invest.core.sources import DataOrigin, DataSource, DataType, ProvenanceLevel, VerificationState
from nexo_invest.data.sec_edgar import FetchRecord

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; NexoInvestAI/0.1; research prototype)"

PROVENANCE_LIMITATIONS: Tuple[str, ...] = (
    "Fuente no oficial (Yahoo Finance): endpoint público sin garantía de exactitud ni disponibilidad.",
    "Nivel de procedencia EXTERNAL_DOWNLOADED: la descarga funcionó, la serie no está verificada.",
    "No se ha contrastado con un proveedor oficial de precios ni con el mercado de origen.",
    "Los precios ajustados incorporan dividendos y desdoblamientos; el ajuste puede diferir entre proveedores.",
)


class PriceSourceError(RuntimeError):
    """Error de descarga o de contenido de la fuente de precios."""


@dataclass
class PriceSeries:
    """Serie diaria de precios con su procedencia."""

    symbol: str
    currency: str
    dates: List[date] = field(default_factory=list)
    adjusted_closes: List[float] = field(default_factory=list)
    closes: List[float] = field(default_factory=list)
    volumes: List[Optional[float]] = field(default_factory=list)
    source: Optional[DataSource] = None
    fetch: Optional[FetchRecord] = None
    limitations: List[str] = field(default_factory=list)
    provenance_level: ProvenanceLevel = ProvenanceLevel.EXTERNAL_DOWNLOADED

    def __len__(self) -> int:
        return len(self.dates)

    def __post_init__(self) -> None:
        if not (len(self.dates) == len(self.adjusted_closes) == len(self.closes)):
            raise ValueError(
                "PriceSeries incoherente: fechas, cierres ajustados y cierres deben "
                "tener la misma longitud"
            )

    def index_at_or_before(self, when: date) -> Optional[int]:
        """Índice del último dato con fecha <= `when`. No usa información futura."""

        candidate = None
        for index, day in enumerate(self.dates):
            if day <= when:
                candidate = index
            else:
                break
        return candidate

    def value_at(self, when: date, *, adjusted: bool = True) -> Optional[float]:
        index = self.index_at_or_before(when)
        if index is None:
            return None
        return self.adjusted_closes[index] if adjusted else self.closes[index]

    def trading_days_before(self, when: date, count: int) -> Optional[float]:
        """Precio de cierre `count` sesiones antes de `when`, sin mirar al futuro."""

        index = self.index_at_or_before(when)
        if index is None or index - count < 0:
            return None
        return self.adjusted_closes[index - count]

    def slice(self, start: Optional[date] = None, end: Optional[date] = None) -> "PriceSeries":
        indices = [
            i
            for i, day in enumerate(self.dates)
            if (start is None or day >= start) and (end is None or day <= end)
        ]
        return PriceSeries(
            symbol=self.symbol,
            currency=self.currency,
            dates=[self.dates[i] for i in indices],
            adjusted_closes=[self.adjusted_closes[i] for i in indices],
            closes=[self.closes[i] for i in indices],
            volumes=[self.volumes[i] for i in indices],
            source=self.source,
            fetch=self.fetch,
            limitations=list(self.limitations),
            provenance_level=self.provenance_level,
        )


def parse_chart_payload(payload: dict, *, symbol: Optional[str] = None) -> PriceSeries:
    """Convierte la respuesta de `chart` en una serie, descartando huecos.

    Yahoo devuelve `null` en días sin negociación (por ejemplo, valores suspendidos).
    Esos puntos se descartan en lugar de rellenarse: una serie con huecos rellenados
    produciría rentabilidades falsas.
    """

    if not isinstance(payload, dict):
        raise PriceSourceError("Respuesta de precios no interpretable como objeto JSON")
    chart = payload.get("chart")
    if not isinstance(chart, dict) or chart.get("error"):
        raise PriceSourceError(f"La fuente devolvió un error: {chart.get('error') if isinstance(chart, dict) else 'desconocido'}")
    results = chart.get("result")
    if not isinstance(results, list) or not results:
        raise PriceSourceError("La respuesta no contiene ninguna serie de precios")
    result = results[0]
    meta = result.get("meta") or {}
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote = (indicators.get("quote") or [{}])[0]
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    adjusted = ((indicators.get("adjclose") or [{}])[0]).get("adjclose")

    series = PriceSeries(
        symbol=str(meta.get("symbol") or symbol or "desconocido"),
        currency=str(meta.get("currency") or "USD"),
    )
    for position, stamp in enumerate(timestamps):
        close = closes[position] if position < len(closes) else None
        adjusted_close = (
            adjusted[position]
            if adjusted is not None and position < len(adjusted)
            else close
        )
        if close is None or adjusted_close is None:
            continue
        volume = volumes[position] if position < len(volumes) else None
        series.dates.append(datetime.fromtimestamp(int(stamp), tz=timezone.utc).date())
        series.closes.append(float(close))
        series.adjusted_closes.append(float(adjusted_close))
        series.volumes.append(float(volume) if volume is not None else None)
    if not series.dates:
        raise PriceSourceError("La serie descargada no contiene ninguna sesión utilizable")
    return series


class YahooPriceClient:
    """Cliente mínimo con límite de peticiones, caché en disco y huella del contenido."""

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        min_interval_seconds: float = 0.6,
        timeout: float = 20.0,
        user_agent: Optional[str] = None,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.min_interval_seconds = max(min_interval_seconds, 0.2)
        self.timeout = timeout
        self.user_agent = user_agent or os.environ.get("NEXO_PRICE_USER_AGENT") or DEFAULT_USER_AGENT
        self._lock = threading.Lock()
        self._last_request_at = 0.0
        self.fetches: List[FetchRecord] = []

    def _cache_path(self, url: str) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        name = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24] + ".json"
        return self.cache_dir / name

    def _throttle(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            remaining = self.min_interval_seconds - elapsed
            if remaining > 0:
                time.sleep(remaining)
            self._last_request_at = time.monotonic()

    def get_json(self, url: str, use_cache: bool = True) -> Tuple[dict, FetchRecord]:
        cache_path = self._cache_path(url) if use_cache else None
        if cache_path is not None and cache_path.exists():
            raw = cache_path.read_bytes()
            record = FetchRecord(
                url=url,
                retrieved_at=datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc),
                status=200,
                bytes_received=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                from_cache=True,
            )
            self.fetches.append(record)
            return json.loads(raw.decode("utf-8")), record

        self._throttle()
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            self.fetches.append(
                FetchRecord(url=url, retrieved_at=datetime.now(timezone.utc), status=exc.code,
                            bytes_received=0, sha256="", from_cache=False, error=f"HTTP {exc.code}")
            )
            raise PriceSourceError(f"La fuente de precios devolvió HTTP {exc.code} para {url}") from exc
        except Exception as exc:
            self.fetches.append(
                FetchRecord(url=url, retrieved_at=datetime.now(timezone.utc), status=None,
                            bytes_received=0, sha256="", from_cache=False,
                            error=f"{type(exc).__name__}: {exc}")
            )
            raise PriceSourceError(f"No se pudo consultar {url}: {type(exc).__name__}: {exc}") from exc

        record = FetchRecord(
            url=url,
            retrieved_at=datetime.now(timezone.utc),
            status=status,
            bytes_received=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            from_cache=False,
        )
        self.fetches.append(record)
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(raw)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise PriceSourceError(f"Respuesta no interpretable como JSON desde {url}") from exc
        return payload, record

    def fetch_series(
        self,
        symbol: str,
        *,
        range_: str = "5y",
        interval: str = "1d",
        use_cache: bool = True,
    ) -> PriceSeries:
        """Descarga una serie diaria y le adjunta su procedencia completa."""

        url = YAHOO_CHART_URL.format(symbol=symbol.upper()) + f"?range={range_}&interval={interval}"
        payload, record = self.get_json(url, use_cache=use_cache)
        series = parse_chart_payload(payload, symbol=symbol.upper())
        series.fetch = record
        series.limitations = list(PROVENANCE_LIMITATIONS)
        series.provenance_level = ProvenanceLevel.EXTERNAL_DOWNLOADED
        series.source = DataSource(
            id=f"yahoo-chart-{series.symbol}-{range_}-{interval}",
            name=f"Yahoo Finance chart · {series.symbol} ({range_}, {interval})",
            entity=series.symbol,
            url=url,
            reference=f"{series.symbol} · {range_} · {interval} · {len(series)} sesiones",
            data_type=DataType.SHARE_PRICE,
            publication_date=series.dates[-1],
            retrieval_date=record.retrieved_at.date(),
            currency=series.currency,
            extraction_method="yahoo finance chart JSON (adjclose)",
            verification_state=VerificationState.PENDING,
            origin=DataOrigin.EXTERNAL_UNVERIFIED,
            notes=f"SHA-256 del contenido descargado: {record.sha256}",
            limitations=list(series.limitations),
            hash=record.sha256,
        )
        return series


def series_from_fixture(
    path: Path,
    *,
    symbol: Optional[str] = None,
    as_of: Optional[date] = None,
) -> PriceSeries:
    """Carga una serie guardada como fixture local, conservando su procedencia.

    El fixture contiene una descarga real congelada. Se conserva el nivel
    `EXTERNAL_DOWNLOADED` (los datos se descargaron de verdad) y se añade la
    limitación de que, al ser una copia, debe volver a comprobarse contra la fuente
    antes de usarse para una decisión.
    """

    raw = Path(path).read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    series = parse_chart_payload(payload, symbol=symbol)
    if as_of is not None:
        series = series.slice(end=as_of)
    digest = hashlib.sha256(raw).hexdigest()
    series.limitations = list(PROVENANCE_LIMITATIONS) + [
        f"Copia local congelada desde {Path(path).name}; su SHA-256 es {digest}.",
        "Al ser una copia, no refleja sesiones posteriores a la fecha de descarga.",
    ]
    origin_url = YAHOO_CHART_URL.format(symbol=(symbol or series.symbol).upper())
    series.provenance_level = ProvenanceLevel.EXTERNAL_DOWNLOADED
    series.source = DataSource(
        id=f"fixture-prices-{series.symbol}",
        name=f"Serie de precios guardada como fixture · {series.symbol}",
        entity=series.symbol,
        url=f"file://{Path(path).as_posix()}",
        reference=f"{series.symbol} · {len(series)} sesiones · SHA-256 {digest}",
        data_type=DataType.SHARE_PRICE,
        publication_date=series.dates[-1],
        retrieval_date=series.dates[-1],
        currency=series.currency,
        extraction_method="fixture local de una descarga real (yahoo finance chart JSON)",
        verification_state=VerificationState.PENDING,
        origin=DataOrigin.EXTERNAL_UNVERIFIED,
        notes=(
            f"SHA-256 del fichero de fixture: {digest}. "
            f"URL original de la descarga: {origin_url}"
        ),
        limitations=list(series.limitations),
        hash=digest,
    )
    return series
