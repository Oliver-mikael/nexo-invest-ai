"""Servicio de sincronización: trae datos de proveedores y los persiste.

Principios que implementa la Fase 5:

- Una respuesta incompleta o errónea **nunca** sobrescribe datos válidos: las
  filas existentes solo cambian con `force=True` y dejan constancia de anomalía.
- Los tipos históricos guardados se usan tal cual; la valoración no reutiliza
  el tipo actual para operaciones antiguas (eso lo garantiza el motor contable).
- Cada ejecución deja un `ProviderRun` con peticiones, registros leídos,
  aceptados, descartados y anomalías detectadas.
- Divergencias anormales entre proveedores para el mismo par y fecha se
  registran; los dos valores se conservan con su fuente (no se unifica la tasa).
- Duplicados se detectan por la restricción única de cada tabla: misma clave →
  mismo valor o se marca anomalía, jamás se duplica.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, load_settings
from app.db import get_session_factory, session_scope
from app.models import (
    DataCache,
    FundamentalFact,
    FxRate,
    Instrument,
    Market,
    ProviderRun,
    Quote,
    utcnow,
)
from app.services.data.base import (
    DataError,
    FxObservation,
    FundamentalObservation,
    PriceBar,
    ProviderDataError,
    ProviderNotConfigured,
)
from app.services.data.http import HttpFetcher
from app.services.data.providers import (
    ExchangeRateApiProvider,
    FrankfurterProvider,
    SecFundamentalsProvider,
    StockAnalysisProvider,
)

JSONDict = Dict[str, Any]


def parse_pairs(raw: str) -> List[Tuple[str, str]]:
    """`"USD/EUR,EUR/USD"` -> `[("USD","EUR"), ("EUR","USD")]`."""
    pairs: List[Tuple[str, str]] = []
    for chunk in (raw or "").split(","):
        piece = chunk.strip().upper()
        if not piece or "/" not in piece:
            continue
        base, quote = piece.split("/", 1)
        base, quote = base.strip(), quote.strip()
        if len(base) == 3 and len(quote) == 3 and base != quote:
            pairs.append((base, quote))
    return pairs


def _jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


class DataSyncService:
    """Orquesta adaptadores, caché y persistencia de datos de mercado."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        client: Optional[httpx.Client] = None,
        fetcher: Optional[HttpFetcher] = None,
        session_factory: Optional[Callable[[], Session]] = None,
        sleep: Callable[[float], None] = time.sleep,
        fx_provider: Optional[FrankfurterProvider] = None,
        fx_secondary: Optional[ExchangeRateApiProvider] = None,
        prices_provider: Optional[StockAnalysisProvider] = None,
        fundamentals_provider: Optional[SecFundamentalsProvider] = None,
    ) -> None:
        self.settings = settings or load_settings()
        self._client = client
        self._owns_client = client is None
        self.fetcher = fetcher or HttpFetcher(
            self._http_client(),
            timeout=self.settings.data_http_timeout_seconds,
            retries=self.settings.data_http_retries,
            backoff=self.settings.data_backoff_seconds,
            sleep=sleep,
        )
        self._session_factory = session_factory or get_session_factory
        self._fx = fx_provider or FrankfurterProvider(self.fetcher)
        self._fx_secondary = fx_secondary or ExchangeRateApiProvider(self.fetcher)
        self._prices = prices_provider or StockAnalysisProvider(self.fetcher)
        self._fundamentals = fundamentals_provider
        self._closed = False

    def close(self) -> None:
        if not self._closed and self._owns_client and self._client is not None:
            self._client.close()
            self._closed = True

    def _http_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(follow_redirects=True)
        return self._client

    # -- runs y caché -----------------------------------------------------------

    def _start_run(
        self, session: Session, provider: str, category: str, task_key: str, request: JSONDict
    ) -> ProviderRun:
        active = session.execute(
            select(ProviderRun)
            .where(
                ProviderRun.task_key == task_key,
                ProviderRun.status.in_(["queued", "running"]),
            )
            .limit(1)
        ).scalar_one_or_none()
        if active is not None:
            raise DataError(
                f"Ya hay una ejecución en curso para '{task_key}' (run #{active.id})."
            )
        run = ProviderRun(
            provider=provider,
            category=category,
            task_key=task_key,
            status="running",
            details={"request": _jsonable(request)},
        )
        session.add(run)
        session.flush()
        return run

    def _finish_run(
        self,
        session: Session,
        run: ProviderRun,
        *,
        status: str,
        error: str = "",
        details: Optional[JSONDict] = None,
    ) -> None:
        run.status = status
        run.error = error[:4000]
        run.finished_at = utcnow()
        run.request_count = self.fetcher.request_count
        if details:
            merged = dict(run.details or {})
            merged.update(details)
            run.details = _jsonable(merged)
        session.commit()

    def _cache_get(self, session: Session, key: str) -> Optional[JSONDict]:
        row = session.execute(
            select(DataCache).where(DataCache.cache_key == key)
        ).scalar_one_or_none()
        if row is None:
            return None
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            return None
        return dict(row.payload or {})

    def _cache_set(
        self, session: Session, key: str, *, provider: str, category: str, subject: str,
        payload: JSONDict, ttl_seconds: int,
    ) -> None:
        now = datetime.now(timezone.utc)
        row = session.execute(
            select(DataCache).where(DataCache.cache_key == key)
        ).scalar_one_or_none()
        if row is None:
            row = DataCache(
                cache_key=key, provider=provider, category=category, subject=subject,
                payload=payload, fetched_at=now, expires_at=now + timedelta(seconds=ttl_seconds),
            )
            session.add(row)
        else:
            row.payload = payload
            row.fetched_at = now
            row.expires_at = now + timedelta(seconds=ttl_seconds)
        session.flush()

    # -- divisas ----------------------------------------------------------------

    def sync_fx(
        self,
        base: str,
        quotes: Sequence[str],
        *,
        start: Optional[date] = None,
        end: Optional[date] = None,
        providers: Optional[Sequence[str]] = None,
        provider_name: Optional[str] = None,
        force: bool = False,
        run: Optional[ProviderRun] = None,
    ) -> JSONDict:
        name = (provider_name or self.settings.fx_provider).lower()
        if name in {self._fx_secondary.name, "exchange-rate-api", "er-api"}:
            adapter: Any = self._fx_secondary
        elif name == self._fx.name:
            adapter = self._fx
        else:
            raise ProviderNotConfigured(f"No hay proveedor de divisas '{name}' configurado.")
        provider_name = adapter.name

        base = base.strip().upper()
        wanted = [q.strip().upper() for q in quotes if q.strip()]
        if base in wanted:
            wanted = [q for q in wanted if q != base]
        if not wanted:
            raise ProviderDataError("Debe solicitarse al menos una cotización distinta de la base.")

        task_key = (
            f"fx:{provider_name}:{base}:{','.join(sorted(wanted))}:"
            f"{start.isoformat() if start else '*'}:{end.isoformat() if end else '*'}:"
            f"{','.join(p.upper() for p in providers) if providers else '-'}"
        )
        request: JSONDict = {
            "type": "fx",
            "provider": provider_name,
            "base": base,
            "quotes": list(wanted),
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "providers": [p.upper() for p in providers] if providers else None,
            "force": force,
        }
        if not adapter.supports_history and (start is not None or end is not None):
            raise ProviderDataError(
                f"{provider_name} solo ofrece tasas actuales; no admite rangos históricos."
            )

        cache_key = f"fx:{task_key}"
        ttl = (
            self.settings.data_fx_latest_ttl_minutes * 60
            if start is None
            else self.settings.data_fx_history_ttl_hours * 3600
        )

        self.fetcher.reset_counter()
        with session_scope() as session:
            if run is None:
                started = self._start_run(session, provider_name, "fx", task_key, request)
            else:
                started = session.get(ProviderRun, run.id)
                assert started is not None
                started.details = {**(started.details or {}), "request": _jsonable(request)}
            started.status = "running"
            started.attempts = max(1, started.attempts)
            session.flush()
            run_id = started.id

            if not force:
                cached = self._cache_get(session, cache_key)
                if cached is not None:
                    self._finish_run(
                        session, started, status="cached",
                        details={"reason": "caché vigente; no se repitió la petición",
                                 "items_fetched": len(cached.get("observations", []))},
                    )
                    return {"run_id": run_id, "status": "cached", **cached}

        anomalies: List[JSONDict] = []
        stored = updated = skipped = fetched = 0
        try:
            if adapter is self._fx_secondary:
                observations = adapter.fetch(base, wanted)
            else:
                observations = adapter.fetch(
                    base, wanted, start=start, end=end,
                    providers=[p.upper() for p in providers] if providers else None,
                )
            fetched = len(observations)
        except DataError as exc:
            with session_scope() as session:
                failed_run = session.get(ProviderRun, run_id)
                if failed_run is not None:
                    self._finish_run(session, failed_run, status="failed", error=str(exc))
            return {"run_id": run_id, "status": "failed", "error": str(exc)}

        today = date.today()
        accepted: List[FxObservation] = []
        for obs in observations:
            if obs.base_currency != base or obs.quote_currency not in wanted:
                continue  # el proveedor no debe traer pares no pedidos
            if obs.as_of > today:
                anomalies.append({
                    "kind": "fecha_futura",
                    "pair": f"{obs.base_currency}/{obs.quote_currency}",
                    "as_of": obs.as_of.isoformat(),
                })
                skipped += 1
                continue
            accepted.append(obs)

        with session_scope() as session:
            active_run = session.get(ProviderRun, run_id)
            assert active_run is not None
            for obs in accepted:
                outcome = self._store_fx(session, obs, force=force, anomalies=anomalies)
                if outcome == "stored":
                    stored += 1
                elif outcome == "updated":
                    updated += 1
                else:
                    skipped += 1
            payload = {
                "observations": [_fx_public(obs) for obs in accepted],
                "fetched": fetched,
                "stored": stored,
                "updated": updated,
                "skipped": skipped,
                "anomalies": anomalies[:50],
                "provider": provider_name,
            }
            if fetched:
                self._cache_set(
                    session, cache_key, provider=provider_name, category="fx",
                    subject=f"{base}/{','.join(sorted(wanted))}",
                    payload=payload, ttl_seconds=ttl,
                )
            status = "success" if stored or updated else ("skipped" if not fetched else "partial")
            if anomalies and (stored or updated):
                status = "partial"
            self._finish_run(
                session, active_run, status=status,
                details={
                    "items_fetched": fetched,
                    "items_stored": stored + updated,
                    "items_skipped": skipped,
                    "anomalies": anomalies[:50],
                    "pairs": sorted({f"{o.base_currency}/{o.quote_currency}" for o in accepted}),
                    "data_as_of": max((o.as_of for o in accepted), default=None).isoformat()
                    if accepted else None,
                },
            )
        return {
            "run_id": run_id,
            "status": status,
            "provider": provider_name,
            "fetched": fetched,
            "stored": stored,
            "updated": updated,
            "skipped": skipped,
            "anomalies": anomalies[:50],
        }

    def _store_fx(
        self, session: Session, obs: FxObservation, *, force: bool, anomalies: List[JSONDict]
    ) -> str:
        source = obs.provenance.provider
        existing = session.execute(
            select(FxRate).where(
                FxRate.user_id.is_(None),
                FxRate.base_currency == obs.base_currency,
                FxRate.quote_currency == obs.quote_currency,
                FxRate.as_of == obs.as_of,
                FxRate.source == source,
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                FxRate(
                    user_id=None,
                    base_currency=obs.base_currency,
                    quote_currency=obs.quote_currency,
                    rate=obs.rate,
                    as_of=obs.as_of,
                    source=source,
                    quality=obs.provenance.quality,
                    kind=obs.provenance.kind or "market",
                )
            )
            session.flush()
            self._fx_divergence(session, obs, anomalies)
            return "stored"

        current = Decimal(existing.rate)
        if current == obs.rate:
            return "skipped"  # deduplicado: mismo valor
        if not force:
            anomalies.append({
                "kind": "valor_existente_distinto_sin_force",
                "pair": f"{obs.base_currency}/{obs.quote_currency}",
                "as_of": obs.as_of.isoformat(),
                "existing": str(current),
                "incoming": str(obs.rate),
                "source": source,
            })
            return "skipped"
        anomalies.append({
            "kind": "valor_historico_reemplazado",
            "pair": f"{obs.base_currency}/{obs.quote_currency}",
            "as_of": obs.as_of.isoformat(),
            "existing": str(current),
            "incoming": str(obs.rate),
            "source": source,
        })
        existing.rate = obs.rate
        existing.retrieved_at = obs.provenance.retrieved_at
        existing.quality = obs.provenance.quality
        existing.kind = obs.provenance.kind or existing.kind
        session.flush()
        return "updated"

    def _fx_divergence(
        self, session: Session, obs: FxObservation, anomalies: List[JSONDict]
    ) -> None:
        threshold = self.settings.data_fx_divergence_threshold
        if threshold <= 0:
            return
        others = session.execute(
            select(FxRate).where(
                FxRate.user_id.is_(None),
                FxRate.base_currency == obs.base_currency,
                FxRate.quote_currency == obs.quote_currency,
                FxRate.as_of == obs.as_of,
                FxRate.source != obs.provenance.provider,
            ).limit(10)
        ).scalars().all()
        for other in others:
            other_rate = Decimal(other.rate)
            if other_rate <= 0:
                continue
            delta = abs(obs.rate - other_rate) / other_rate
            if delta > Decimal(str(threshold)):
                anomalies.append({
                    "kind": "divergencia_entre_proveedores",
                    "pair": f"{obs.base_currency}/{obs.quote_currency}",
                    "as_of": obs.as_of.isoformat(),
                    "pct": str((delta * 100).quantize(Decimal("0.01"))),
                    "a": {"source": obs.provenance.provider, "rate": str(obs.rate)},
                    "b": {"source": other.source, "rate": str(other_rate)},
                })

    # -- precios ----------------------------------------------------------------

    def sync_prices(
        self,
        instrument_uid: str,
        *,
        start: Optional[date] = None,
        end: Optional[date] = None,
        provider_name: Optional[str] = None,
        force: bool = False,
        run: Optional[ProviderRun] = None,
    ) -> JSONDict:
        name = (provider_name or self.settings.prices_provider).lower()
        if name != self._prices.name:
            raise ProviderNotConfigured(f"No hay proveedor de precios '{name}' configurado.")

        with session_scope() as session:
            instrument = session.execute(
                select(Instrument).where(Instrument.uid == instrument_uid)
            ).scalar_one_or_none()
            if instrument is None:
                raise ProviderDataError(f"No existe el instrumento '{instrument_uid}'.")
            instrument_id = instrument.id
            symbol = instrument.symbol
            market_id = instrument.market_id
            currency = instrument.currency
            country = instrument.country_code
            market = session.get(Market, market_id)
            market_code = market.code if market else country

        task_key = f"prices:{name}:{instrument_uid}:{start.isoformat() if start else '*'}:{end.isoformat() if end else '*'}"
        request: JSONDict = {
            "type": "prices",
            "provider": name,
            "instrument_uid": instrument_uid,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "force": force,
        }
        cache_key = f"prices:{task_key}"
        ttl = self.settings.data_prices_ttl_hours * 3600

        self.fetcher.reset_counter()
        with session_scope() as session:
            if run is None:
                started = self._start_run(session, name, "prices", task_key, request)
            else:
                started = session.get(ProviderRun, run.id)
                assert started is not None
                started.details = {**(started.details or {}), "request": _jsonable(request)}
            started.status = "running"
            session.flush()
            run_id = started.id
            if not force:
                cached = self._cache_get(session, cache_key)
                if cached is not None:
                    self._finish_run(
                        session, started, status="cached",
                        details={"reason": "caché vigente; no se repitió la petición",
                                 "items_fetched": cached.get("fetched", 0)},
                    )
                    return {"run_id": run_id, "status": "cached", **cached}

        anomalies: List[JSONDict] = []
        stored = updated = skipped = 0
        try:
            bars = self._prices.fetch_history(
                symbol, market_code=market_code, country_code=country,
                start=start, end=end,
            )
        except DataError as exc:
            with session_scope() as session:
                failed_run = session.get(ProviderRun, run_id)
                if failed_run is not None:
                    self._finish_run(session, failed_run, status="failed", error=str(exc))
            return {"run_id": run_id, "status": "failed", "error": str(exc)}

        today = date.today()
        accepted: List[PriceBar] = []
        for bar in bars:
            if bar.as_of > today:
                anomalies.append({"kind": "fecha_futura", "as_of": bar.as_of.isoformat()})
                skipped += 1
                continue
            accepted.append(bar)

        with session_scope() as session:
            active_run = session.get(ProviderRun, run_id)
            assert active_run is not None
            for bar in accepted:
                outcome = self._store_bar(
                    session, instrument_id, bar, provider=name,
                    force=force, anomalies=anomalies, currency=currency,
                )
                if outcome == "stored":
                    stored += 1
                elif outcome == "updated":
                    updated += 1
                else:
                    skipped += 1

            latest = max((b.as_of for b in accepted), default=None)
            stale = bool(
                latest and (today - latest).days > self.settings.data_stale_after_days
            )
            payload = {
                "fetched": len(accepted),
                "stored": stored,
                "updated": updated,
                "skipped": skipped,
                "anomalies": anomalies[:50],
                "latest_as_of": latest.isoformat() if latest else None,
                "stale": stale,
                "instrument_uid": instrument_uid,
            }
            if accepted:
                self._cache_set(
                    session, cache_key, provider=name, category="prices",
                    subject=instrument_uid, payload=payload, ttl_seconds=ttl,
                )
            status = "success"
            if not accepted:
                status = "failed"
            elif anomalies:
                status = "partial"
            self._finish_run(
                session, active_run, status=status,
                details={
                    "items_fetched": len(accepted),
                    "items_stored": stored + updated,
                    "items_skipped": skipped,
                    "anomalies": anomalies[:50],
                    "latest_as_of": latest.isoformat() if latest else None,
                    "stale": stale,
                },
            )
        return {"run_id": run_id, "status": status, "provider": name, **payload}

    def _store_bar(
        self,
        session: Session,
        instrument_id: int,
        bar: PriceBar,
        *,
        provider: str,
        force: bool,
        anomalies: List[JSONDict],
        currency: str,
    ) -> str:
        outcomes = []
        for adjusted, price in (
            (False, bar.close),
            (True, bar.adjusted_close),
        ):
            if price is None:
                continue
            source = provider if not adjusted else f"{provider}:adj"
            existing = session.execute(
                select(Quote).where(
                    Quote.user_id.is_(None),
                    Quote.instrument_id == instrument_id,
                    Quote.as_of == bar.as_of,
                    Quote.source == source,
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    Quote(
                        user_id=None,
                        instrument_id=instrument_id,
                        price=price,
                        currency=currency,
                        as_of=bar.as_of,
                        source=source,
                        quality=bar.provenance.quality,
                        adjusted=adjusted,
                    )
                )
                session.flush()
                if not adjusted:
                    self._price_jump(session, instrument_id, bar, provider, anomalies)
                outcomes.append("stored")
                continue
            current = Decimal(existing.price)
            if current == price:
                outcomes.append("skipped")
                continue
            if not force:
                anomalies.append({
                    "kind": "cotizacion_existente_distinta_sin_force",
                    "as_of": bar.as_of.isoformat(),
                    "source": source,
                    "existing": str(current),
                    "incoming": str(price),
                })
                outcomes.append("skipped")
                continue
            anomalies.append({
                "kind": "cotizacion_reemplazada",
                "as_of": bar.as_of.isoformat(),
                "source": source,
                "existing": str(current),
                "incoming": str(price),
            })
            existing.price = price
            existing.retrieved_at = bar.provenance.retrieved_at
            existing.quality = bar.provenance.quality
            session.flush()
            outcomes.append("updated")
        if "updated" in outcomes:
            return "updated"
        if "stored" in outcomes:
            return "stored"
        return "skipped"

    def _price_jump(
        self, session: Session, instrument_id: int, bar: PriceBar, provider: str,
        anomalies: List[JSONDict],
    ) -> None:
        """Marca movimientos diarios extremos sin descartar el dato (splits reales existen)."""
        previous = session.execute(
            select(Quote)
            .where(
                Quote.user_id.is_(None),
                Quote.instrument_id == instrument_id,
                Quote.source == provider,  # cierre sin ajustar del mismo proveedor
                Quote.as_of < bar.as_of,
                Quote.adjusted.is_(False),
            )
            .order_by(Quote.as_of.desc())
            .limit(1)
        ).scalars().first()
        if previous is None:
            return
        prev = Decimal(previous.price)
        if prev <= 0:
            return
        change = abs((bar.close - prev) / prev)
        if change > Decimal("0.35"):
            anomalies.append({
                "kind": "variacion_diaria_extrema",
                "as_of": bar.as_of.isoformat(),
                "previous": str(prev),
                "close": str(bar.close),
                "pct": str((change * 100).quantize(Decimal("0.01"))),
                "note": "puede ser un split o un dato anómalo; revisar antes de usar",
            })

    # -- fundamentales ----------------------------------------------------------

    def sync_fundamentals(
        self,
        instrument_uid: str,
        *,
        force: bool = False,
        run: Optional[ProviderRun] = None,
        provider: Optional[SecFundamentalsProvider] = None,
    ) -> JSONDict:
        with session_scope() as session:
            instrument = session.execute(
                select(Instrument).where(Instrument.uid == instrument_uid)
            ).scalar_one_or_none()
            if instrument is None:
                raise ProviderDataError(f"No existe el instrumento '{instrument_uid}'.")
            instrument_id, cik, currency = instrument.id, instrument.cik, instrument.currency

        if cik is None:
            raise ProviderNotConfigured(
                "El instrumento no tiene CIK SEC: los fundamentales solo están "
                "disponibles para emisores con EDGAR (EE. UU.). No se sustituye por otra fuente."
            )
        adapter = provider or self._fundamentals
        if adapter is None:
            adapter = SecFundamentalsProvider(
                contact=self.settings.sec_contact,
                cache_dir=self.settings.sec_cache_dir,
            )
        task_key = f"fundamentals:sec:{instrument_uid}"
        request: JSONDict = {"type": "fundamentals", "instrument_uid": instrument_uid, "force": force}
        self.fetcher.reset_counter()
        with session_scope() as session:
            if run is None:
                started = self._start_run(session, adapter.name, "fundamentals", task_key, request)
            else:
                started = session.get(ProviderRun, run.id)
                assert started is not None
                started.details = {**(started.details or {}), "request": _jsonable(request)}
            started.status = "running"
            session.flush()
            run_id = started.id

        anomalies: List[JSONDict] = []
        try:
            observations = adapter.fetch(
                instrument_id=instrument_id, cik=cik, currency=currency
            )
        except DataError as exc:
            with session_scope() as session:
                failed_run = session.get(ProviderRun, run_id)
                if failed_run is not None:
                    self._finish_run(session, failed_run, status="failed", error=str(exc))
            return {"run_id": run_id, "status": "failed", "error": str(exc)}

        stored = updated = skipped = 0
        with session_scope() as session:
            active_run = session.get(ProviderRun, run_id)
            assert active_run is not None
            for obs in observations:
                outcome = self._store_fundamental(session, obs, force=force, anomalies=anomalies)
                if outcome == "stored":
                    stored += 1
                elif outcome == "updated":
                    updated += 1
                else:
                    skipped += 1
            status = "success" if stored or updated else "skipped"
            if anomalies:
                status = "partial"
            self._finish_run(
                session, active_run, status=status,
                details={
                    "items_fetched": len(observations),
                    "items_stored": stored + updated,
                    "items_skipped": skipped,
                    "anomalies": anomalies[:50],
                    "periods": [f"{o.period_type}:{o.fiscal_end.isoformat()}" for o in observations],
                    "request_count": adapter.last_request_count,
                },
            )
        return {
            "run_id": run_id,
            "status": status,
            "provider": adapter.name,
            "fetched": len(observations),
            "stored": stored,
            "updated": updated,
            "skipped": skipped,
            "anomalies": anomalies[:50],
        }

    def _store_fundamental(
        self,
        session: Session,
        obs: FundamentalObservation,
        *,
        force: bool,
        anomalies: List[JSONDict],
    ) -> str:
        existing = session.execute(
            select(FundamentalFact).where(
                FundamentalFact.instrument_id == obs.instrument_id,
                FundamentalFact.period_type == obs.period_type,
                FundamentalFact.fiscal_end == obs.fiscal_end,
                FundamentalFact.source == obs.source,
            )
        ).scalar_one_or_none()
        metrics = {k: v for k, v in obs.metrics.items() if v is not None}
        if existing is None:
            session.add(
                FundamentalFact(
                    instrument_id=obs.instrument_id,
                    period_type=obs.period_type,
                    fiscal_start=obs.fiscal_start,
                    fiscal_end=obs.fiscal_end,
                    reported_at=obs.reported_at,
                    currency=obs.currency,
                    source=obs.source,
                    quality=obs.provenance.quality,
                    retrieved_at=obs.provenance.retrieved_at,
                    **{k: metrics.get(k) for k in (
                        "revenue", "net_income", "ebitda", "eps_diluted",
                        "shares_outstanding", "total_debt", "cash", "free_cash_flow",
                    )},
                )
            )
            session.flush()
            return "stored"
        incoming = {
            "revenue": metrics.get("revenue"),
            "net_income": metrics.get("net_income"),
            "eps_diluted": metrics.get("eps_diluted"),
        }
        diffs: Dict[str, Any] = {}
        for key, value in incoming.items():
            if value is None:
                continue
            current = getattr(existing, key)
            if current is None:
                continue
            if Decimal(str(current)) != value:
                diffs[key] = {"existing": str(current), "incoming": str(value)}
        if not diffs:
            return "skipped"
        if not force:
            anomalies.append({
                "kind": "fundamento_existente_distinto_sin_force",
                "period_type": obs.period_type,
                "fiscal_end": obs.fiscal_end.isoformat(),
                "diffs": diffs,
            })
            return "skipped"
        for key, value in metrics.items():
            if value is not None:
                setattr(existing, key, value)
        existing.retrieved_at = obs.provenance.retrieved_at
        session.flush()
        anomalies.append({
            "kind": "fundamento_reemplazado",
            "period_type": obs.period_type,
            "fiscal_end": obs.fiscal_end.isoformat(),
            "diffs": diffs,
        })
        return "updated"


def _fx_public(obs: FxObservation) -> JSONDict:
    payload = {
        "base_currency": obs.base_currency,
        "quote_currency": obs.quote_currency,
        "rate": str(obs.rate),
        "as_of": obs.as_of.isoformat(),
    }
    payload.update(obs.provenance.public_view())
    return payload
