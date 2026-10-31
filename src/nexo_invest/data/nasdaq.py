"""Segunda fuente financiera independiente: Nasdaq (api.nasdaq.com), gratuita y sin clave.

Qué aporta este adaptador y qué no:

- Aporta una **distribución independiente** de las cifras publicadas por la empresa
  (estado de resultados por año fiscal) y de los cierres diarios (Close/Last).
- **No aporta una fuente primaria distinta**: los datos fundamentales de Nasdaq se
  derivan de los mismos documentos que presenta la empresa. La coincidencia con SEC
  EDGAR comprueba la cadena de distribución, no una medición independiente. Esa
  distinción queda escrita en cada limitación del contraste.
- El endpoint no declara la unidad de sus cifras (llegan como `$416,161,000`). La
  relación de unidad se **infiere** comparando con la fuente primaria y se registra
  como inferida, nunca como declarada por la fuente.
- La fuente se consulta con `User-Agent` identificable, límite de peticiones y
  caché en disco; se conserva la URL, la fecha de consulta y el SHA-256 del
  contenido crudo para poder reproducir o volver a comprobar el dato.
- Si la descarga falla, se registra el error y no se devuelve ninguna tabla: el
  hueco se queda vacío, no se rellena con la última cifra conocida.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from nexo_invest.core.sources import (
    DataOrigin,
    DataSource,
    DataType,
    VerificationState,
)
from nexo_invest.data.sec_edgar import FetchRecord

NASDAQ_FINANCIALS_URL = "https://api.nasdaq.com/api/company/{ticker}/financials?assetclass=stocks"
NASDAQ_HISTORICAL_URL = (
    "https://api.nasdaq.com/api/quote/{ticker}/historical"
    "?assetclass=stocks&fromdate={start}&todate={end}&limit={limit}"
)
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; NexoInvestAI/0.1; research prototype)"

# Comportamiento observado el 2026-10-28 y verificado con peticiones repetidas:
# un User-Agent que incluye una URL de contacto en el mismo string recibe un
# corte de conexión silencioso (timeout) en api.nasdaq.com, mientras que la forma
# corta anterior responde en 0,1 s. La SEC exige lo contrario (contacto en el
# User-Agent); por eso cada adaptador lleva su propio identificador y esta
# restricción queda documentada aquí en lugar de escondida.
NASDAQ_UA_RESTRICTION = (
    "api.nasdaq.com corta silenciosamente las peticiones cuyo User-Agent incluye "
    "una URL de contacto; se usa la forma corta identificable del adaptador."
)

LIMITATIONS: Tuple[str, ...] = (
    "Segunda fuente de distribución independiente (Nasdaq), no fuente primaria: sus "
    "cifras se derivan de los mismos documentos que publica la empresa.",
    "El endpoint no declara la unidad de las cifras; la relación de unidad se infiere "
    "por contraste con la fuente primaria y queda registrada como inferida.",
    "Nasdaq no es el mercado oficial de precios: es un agregador de datos de mercado.",
    "Sin garantía contractual de exactitud ni disponibilidad; puede cambiar o dejar "
    "de responder sin aviso.",
    "Restricción de acceso observada (2026-10-28): un User-Agent con URL de contacto "
    "recibe corte silencioso; se usa la forma corta identificable.",
)


class NasdaqError(RuntimeError):
    """Error de descarga o de contenido en la fuente Nasdaq."""


# -- parsing --------------------------------------------------------------------------


_MONEY_RE = re.compile(r"^\$?\s*(-?[\d,]+(?:\.\d+)?)$")


def parse_money(raw: object) -> Optional[float]:
    """Convierte un texto tipo `$416,161,000` o `12,345` a float.

    Cadena vacía o ausente -> None (dato no disponible). Nunca 0: una cifra que no
    llegó no es una cifra cero.
    """

    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text:
        return None
    match = _MONEY_RE.match(text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_nasdaq_date(raw: object) -> Optional[date]:
    """Convierte `10/27/2026` (M/D/Y) a date. Devuelve None si no se puede interpretar."""

    if not raw:
        return None
    try:
        month, day, year = (int(part) for part in str(raw).strip().split("/"))
        return date(year, month, day)
    except (ValueError, TypeError):
        return None


# -- tablas descargadas ----------------------------------------------------------------


@dataclass
class NasdaqFinancials:
    """Estado de resultados por columnas (un año fiscal por columna)."""

    ticker: str
    period_endings: List[date]
    values: Dict[str, List[Optional[float]]] = field(default_factory=dict)
    raw_values: Dict[Tuple[str, int], str] = field(default_factory=dict)
    source: Optional[DataSource] = None
    fetch: Optional[FetchRecord] = None
    limitations: List[str] = field(default_factory=list)

    def row(self, label: str) -> List[Optional[float]]:
        return list(self.values.get(label, []))

    def value_for(self, label: str, period_end: date) -> Optional[float]:
        """Valor de la fila `label` para el cierre fiscal `period_end`.

        Devuelve None si la fuente no publica esa columna: no se aproxima al cierre
        más cercano ni se rellena con otro periodo.
        """

        if period_end not in self.period_endings:
            return None
        index = self.period_endings.index(period_end)
        series = self.values.get(label)
        if series is None or index >= len(series):
            return None
        return series[index]


@dataclass
class NasdaqHistory:
    """Cierres diarios sin ajustar (Close/Last) tal y como los publica Nasdaq."""

    ticker: str
    dates: List[date] = field(default_factory=list)
    closes: List[float] = field(default_factory=list)
    source: Optional[DataSource] = None
    fetch: Optional[FetchRecord] = None
    limitations: List[str] = field(default_factory=list)

    def close_on(self, when: date) -> Optional[float]:
        if when not in self.dates:
            return None
        return self.closes[self.dates.index(when)]


# -- cliente ---------------------------------------------------------------------------


class NasdaqClient:
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
        self.user_agent = user_agent or os.environ.get("NEXO_NASDAQ_USER_AGENT") or DEFAULT_USER_AGENT
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
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                raise NasdaqError(f"Respuesta en caché no interpretable como JSON desde {url}") from exc
            if not isinstance(payload, dict):
                raise NasdaqError(f"Se esperaba un objeto JSON en {url}")
            return payload, record

        self._throttle()
        request = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            self.fetches.append(
                FetchRecord(
                    url=url,
                    retrieved_at=datetime.now(timezone.utc),
                    status=exc.code,
                    bytes_received=0,
                    sha256="",
                    from_cache=False,
                    error=f"HTTP {exc.code}",
                )
            )
            raise NasdaqError(f"Nasdaq devolvió HTTP {exc.code} para {url}") from exc
        except Exception as exc:
            self.fetches.append(
                FetchRecord(
                    url=url,
                    retrieved_at=datetime.now(timezone.utc),
                    status=None,
                    bytes_received=0,
                    sha256="",
                    from_cache=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            raise NasdaqError(
                f"No se pudo consultar {url}: {type(exc).__name__}: {exc}"
            ) from exc

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
            raise NasdaqError(f"Respuesta no interpretable como JSON desde {url}") from exc
        if not isinstance(payload, dict):
            raise NasdaqError(f"Se esperaba un objeto JSON en {url}")
        return payload, record

    # -- API pública ---------------------------------------------------------------

    def financials(self, ticker: str) -> NasdaqFinancials:
        """Descarga el estado de resultados anual del ticker indicado."""

        symbol = ticker.upper().strip()
        url = NASDAQ_FINANCIALS_URL.format(ticker=symbol)
        payload, record = self.get_json(url)
        table = parse_financials(payload, ticker=symbol, fetch=record)
        table.limitations = list(LIMITATIONS)
        table.source = self._financials_source(table)
        return table

    def historical(
        self,
        ticker: str,
        start: date,
        end: date,
        limit: int = 4000,
    ) -> NasdaqHistory:
        """Descarga cierres diarios (Close/Last) en el rango indicado."""

        symbol = ticker.upper().strip()
        if start > end:
            raise ValueError(f"Rango invertido: {start} > {end}")
        url = NASDAQ_HISTORICAL_URL.format(
            ticker=symbol,
            start=start.isoformat(),
            end=end.isoformat(),
            limit=limit,
        )
        payload, record = self.get_json(url)
        history = parse_historical(payload, ticker=symbol, fetch=record)
        history.limitations = list(LIMITATIONS) + [
            "Close/Last sin ajustar: incorpora dividendos y desdoblamientos solo en "
            "la medida en que la fuente lo haya reexpresado.",
        ]
        history.source = self._history_source(history, url, record)
        return history

    def _financials_source(self, table: NasdaqFinancials) -> DataSource:
        fetch = table.fetch
        return DataSource(
            id=f"nasdaq-financials-{table.ticker.lower()}",
            name=f"Nasdaq · estado de resultados · {table.ticker}",
            entity=table.ticker,
            url=fetch.url if fetch else NASDAQ_FINANCIALS_URL.format(ticker=table.ticker),
            reference=(
                f"{table.ticker} · {len(table.period_endings)} años fiscales · "
                f"SHA-256 {fetch.sha256 if fetch else 'desconocido'}"
            ),
            data_type=DataType.INCOME_STATEMENT,
            publication_date=table.period_endings[-1] if table.period_endings else None,
            retrieval_date=fetch.retrieved_at.date() if fetch else None,
            currency="USD",
            extraction_method="nasdaq api income statement JSON",
            verification_state=VerificationState.PENDING,
            origin=DataOrigin.EXTERNAL_UNVERIFIED,
            notes=(
                f"SHA-256 del contenido descargado: {fetch.sha256 if fetch else 'desconocido'}"
            ),
            limitations=list(table.limitations),
            hash=fetch.sha256 if fetch else None,
        )

    def _history_source(
        self, history: NasdaqHistory, url: str, fetch: FetchRecord
    ) -> DataSource:
        return DataSource(
            id=f"nasdaq-historical-{history.ticker.lower()}",
            name=f"Nasdaq · cierres diarios · {history.ticker}",
            entity=history.ticker,
            url=url,
            reference=(
                f"{history.ticker} · {len(history.dates)} sesiones · "
                f"SHA-256 {fetch.sha256}"
            ),
            data_type=DataType.SHARE_PRICE,
            publication_date=history.dates[-1] if history.dates else None,
            retrieval_date=fetch.retrieved_at.date(),
            currency="USD",
            extraction_method="nasdaq api historical close (Close/Last)",
            verification_state=VerificationState.PENDING,
            origin=DataOrigin.EXTERNAL_UNVERIFIED,
            notes=f"SHA-256 del contenido descargado: {fetch.sha256}",
            limitations=list(history.limitations),
            hash=fetch.sha256,
        )


# -- funciones puras (testeables sin red) ----------------------------------------------


def parse_financials(
    payload: dict, *, ticker: str, fetch: Optional[FetchRecord] = None
) -> NasdaqFinancials:
    """Convierte la respuesta de `/api/company/{t}/financials` en una tabla.

    Solo se leen las filas con etiqueta; una celda vacía queda como None y nunca
    como 0.
    """

    data = (payload or {}).get("data") or {}
    table = data.get("incomeStatementTable")
    if not isinstance(table, dict):
        raise NasdaqError("La respuesta no contiene incomeStatementTable")
    headers = table.get("headers") or {}
    raw_columns = [
        (key, headers.get(key))
        for key in sorted(headers, key=lambda k: (len(k), k))
        if key != "value1"
    ]
    endings: List[date] = []
    column_keys: List[str] = []
    for key, label in raw_columns:
        parsed = parse_nasdaq_date(label)
        if parsed is None:
            continue
        endings.append(parsed)
        column_keys.append(key)

    values: Dict[str, List[Optional[float]]] = {}
    raw_values: Dict[Tuple[str, int], str] = {}
    for row in table.get("rows") or []:
        if not isinstance(row, dict):
            continue
        label = str(row.get("value1") or "").strip()
        if not label:
            continue
        series: List[Optional[float]] = []
        for position, key in enumerate(column_keys):
            raw = row.get(key)
            if isinstance(raw, str) and raw.strip():
                raw_values[(label, position)] = raw.strip()
            series.append(parse_money(raw))
        values[label] = series

    if not endings:
        raise NasdaqError("La respuesta no contiene ningún cierre fiscal interpretable")
    return NasdaqFinancials(
        ticker=ticker.upper(),
        period_endings=endings,
        values=values,
        raw_values=raw_values,
        fetch=fetch,
    )


def parse_historical(
    payload: dict, *, ticker: str, fetch: Optional[FetchRecord] = None
) -> NasdaqHistory:
    """Convierte la respuesta de `/api/quote/{t}/historical` en una serie.

    Los días sin fila simplemente no existen: no se rellena ningún hueco.
    """

    data = (payload or {}).get("data") or {}
    if data.get("symbol") and str(data["symbol"]).upper() != ticker.upper():
        raise NasdaqError(
            f"La fuente devolvió {data.get('symbol')} cuando se pidió {ticker}: "
            "el dato no corresponde al activo solicitado"
        )
    table = data.get("tradesTable") or {}
    rows = table.get("rows") or []
    history = NasdaqHistory(ticker=ticker.upper())
    for row in rows:
        if not isinstance(row, dict):
            continue
        when = parse_nasdaq_date(row.get("date"))
        close = parse_money(row.get("close"))
        if when is None or close is None:
            continue
        history.dates.append(when)
        history.closes.append(close)
    if fetch is not None:
        history.fetch = fetch
    # Las filas llegan de la más reciente a la más antigua: se ordenan ascendentes.
    order = sorted(range(len(history.dates)), key=lambda i: history.dates[i])
    history.dates = [history.dates[i] for i in order]
    history.closes = [history.closes[i] for i in order]
    if not history.dates:
        raise NasdaqError("La respuesta no contiene ninguna sesión utilizable")
    return history


def historical_from_fixture(
    path: Path, *, ticker: str
) -> NasdaqHistory:
    """Carga una descarga real congelada como fixture, conservando su procedencia.

    El nivel se declara `LOCAL_FIXTURE`: es una copia local de una descarga real.
    Antes de usarla para una decisión hay que volver a comprobarla contra la fuente.
    """

    raw = Path(path).read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    digest = hashlib.sha256(raw).hexdigest()
    history = parse_historical(payload, ticker=ticker)
    history.limitations = list(LIMITATIONS) + [
        f"Copia local congelada desde {Path(path).name}; su SHA-256 es {digest}.",
        "Al ser una copia, no refleja sesiones posteriores a la fecha de descarga.",
    ]
    history.fetch = FetchRecord(
        url=f"file://{Path(path).as_posix()}",
        retrieved_at=datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc),
        status=200,
        bytes_received=len(raw),
        sha256=digest,
        from_cache=True,
    )
    history.source = DataSource(
        id=f"fixture-nasdaq-history-{ticker.lower()}",
        name=f"Fixture local de cierres Nasdaq · {ticker.upper()}",
        entity=ticker.upper(),
        url=NASDAQ_HISTORICAL_URL.format(
            ticker=ticker.upper(),
            start=history.dates[0].isoformat(),
            end=history.dates[-1].isoformat(),
            limit=4000,
        ) if history.dates else None,
        reference=f"{ticker.upper()} · {len(history.dates)} sesiones · SHA-256 {digest}",
        data_type=DataType.SHARE_PRICE,
        publication_date=history.dates[-1] if history.dates else None,
        retrieval_date=history.fetch.retrieved_at.date(),
        currency="USD",
        extraction_method="fixture local de una descarga real (nasdaq api historical)",
        verification_state=VerificationState.PENDING,
        origin=DataOrigin.EXTERNAL_UNVERIFIED,
        notes=(
            f"Copia local: file://{Path(path).as_posix()} · SHA-256 del fichero: {digest}"
        ),
        limitations=list(history.limitations),
        hash=digest,
    )
    return history


def financials_from_fixture(path: Path, *, ticker: str) -> NasdaqFinancials:
    """Carga el estado de resultados guardado como fixture local, con su procedencia."""

    raw = Path(path).read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    digest = hashlib.sha256(raw).hexdigest()
    table = parse_financials(payload, ticker=ticker)
    table.limitations = list(LIMITATIONS) + [
        f"Copia local congelada desde {Path(path).name}; su SHA-256 es {digest}.",
    ]
    table.fetch = FetchRecord(
        url=f"file://{Path(path).as_posix()}",
        retrieved_at=datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc),
        status=200,
        bytes_received=len(raw),
        sha256=digest,
        from_cache=True,
    )
    table.source = DataSource(
        id=f"fixture-nasdaq-financials-{ticker.lower()}",
        name=f"Fixture local de estado de resultados Nasdaq · {ticker.upper()}",
        entity=ticker.upper(),
        url=NASDAQ_FINANCIALS_URL.format(ticker=ticker.upper()),
        reference=f"{ticker.upper()} · {len(table.period_endings)} años · SHA-256 {digest}",
        data_type=DataType.INCOME_STATEMENT,
        publication_date=table.period_endings[-1] if table.period_endings else None,
        retrieval_date=table.fetch.retrieved_at.date(),
        currency="USD",
        extraction_method="fixture local de una descarga real (nasdaq api financials)",
        verification_state=VerificationState.PENDING,
        origin=DataOrigin.EXTERNAL_UNVERIFIED,
        notes=(
            f"Copia local: file://{Path(path).as_posix()} · SHA-256 del fichero: {digest}"
        ),
        limitations=list(table.limitations),
        hash=digest,
    )
    return table
