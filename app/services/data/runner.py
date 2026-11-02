"""Ejecución asíncrona y programada de las recopilaciones de datos.

Auditoría previa (Etapa A): la plataforma ya tiene `JobRunner`, una cola
persistente basada en `ThreadPoolExecutor` **acoplada a `ResearchJob`** (ticker,
presupuesto IA, pasos de investigación). Reutilizarla literalmente obligaría a
mezclar trabajos de IA con datos de mercado y a refactorizar la cola existente.

Decisión documentada (ver DECISIONS.md):

- **No se incorpora Redis/RQ/Celery/Dramatiq.** No hay coste ni complejidad que
  lo justifique en una instancia.
- Se añade `DataSyncRunner`, que reutiliza el mismo patrón probado (hilos +
  estado en base de datos + recuperación tras reinicio) sin tocar la cola de
  investigación. Ambos runners viven en el proceso y pueden migrarse juntos a un
  broker real cuando haya varias instancias.
- Protección contra ejecuciones duplicadas por `task_key` con estado activo
  (límite documentado: carrera entre procesos distintos; se cerrará con índice
  único parcial cuando haya varias instancias).
- Recuperación: un run `running` interrumpido se reencola si le quedan
  intentos; si no, se marca `failed`. Ningún run queda colgado.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import select

from app.config import Settings, load_settings
from app.db import session_scope
from app.models import Instrument, ProviderRun, utcnow
from app.services.data.base import DataError, ProviderNotConfigured
from app.services.data.sync import DataSyncService, parse_pairs

RequestDict = Dict[str, object]


def task_key_for(request: RequestDict) -> str:
    """Clave de unicidad de ejecución, derivada del contenido del trabajo."""
    kind = request.get("type", "?")
    if kind == "fx":
        quotes = ",".join(sorted(str(q).upper() for q in request.get("quotes", []) or []))
        providers = ",".join(sorted(str(p).upper() for p in request.get("providers", []) or []))
        return (
            f"fx:{request.get('provider')}:{str(request.get('base')).upper()}:{quotes}:"
            f"{request.get('start') or '*'}:{request.get('end') or '*'}:{providers or '-'}"
        )
    if kind == "prices":
        return (
            f"prices:{request.get('provider')}:{request.get('instrument_uid')}:"
            f"{request.get('start') or '*'}:{request.get('end') or '*'}"
        )
    if kind == "fundamentals":
        return f"fundamentals:{request.get('provider') or 'sec'}:{request.get('instrument_uid')}"
    return f"{kind}:{request}"


class DataSyncRunner:
    """Cola ligera de recopilaciones con estado persistente y planificador."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        service: Optional[DataSyncService] = None,
        *,
        max_workers: int = 1,
    ) -> None:
        self.settings = settings or load_settings()
        self.service = service or DataSyncService(self.settings)
        self._max_workers = max(1, max_workers)
        self._executor: Optional[ThreadPoolExecutor] = None
        self._futures: Dict[int, Future] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._scheduler: Optional[threading.Thread] = None

    # -- ciclo de vida ----------------------------------------------------------

    def start(self) -> None:
        if self._executor is not None:
            return
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers, thread_name_prefix="nexo-data"
        )
        for run_id in self.recover_interrupted():
            self._submit(run_id)
        if self.settings.data_sync_interval_minutes > 0:
            self._scheduler = threading.Thread(
                target=self._scheduler_loop, name="nexo-data-scheduler", daemon=True
            )
            self._scheduler.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._scheduler is not None:
            self._scheduler.join(timeout=2.0)
            self._scheduler = None
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=False)
            self._executor = None

    # -- encolado --------------------------------------------------------------

    def enqueue(self, request: RequestDict) -> int:
        """Crea el run persistente y lo encola; devuelve su id.

        Si ya hay una ejecución activa con la misma clave devuelve la existente:
        no se disparan peticiones duplicadas al proveedor.
        """
        key = task_key_for(request)
        with session_scope() as session:
            active = session.execute(
                select(ProviderRun).where(
                    ProviderRun.task_key == key,
                    ProviderRun.status.in_(["queued", "running"]),
                ).limit(1)
            ).scalar_one_or_none()
            if active is not None:
                return active.id
            provider = str(request.get("provider") or self.settings.fx_provider)
            category = str(request.get("type") or "fx")
            run = ProviderRun(
                provider=provider,
                category=category if category in {"fx", "prices", "fundamentals", "news"} else "fx",
                task_key=key,
                status="queued",
                details={"request": request},
            )
            session.add(run)
            session.flush()
            run_id = run.id
        self._submit(run_id)
        return run_id

    def _submit(self, run_id: int) -> None:
        with self._lock:
            if self._executor is None:
                # Sin workers activos (entorno de prueba): se marca y salta.
                with session_scope() as session:
                    run = session.get(ProviderRun, run_id)
                    if run is not None and run.status == "queued":
                        run.status = "failed"
                        run.error = "No hay ejecutor de datos activo."
                        run.finished_at = utcnow()
                return
            existing = self._futures.get(run_id)
            if existing is not None and not existing.done():
                return
            self._futures[run_id] = self._executor.submit(self._process, run_id)

    # -- recuperación -----------------------------------------------------------

    def recover_interrupted(self) -> List[int]:
        requeue: List[int] = []
        max_attempts = max(1, self.settings.job_max_attempts)
        with session_scope() as session:
            rows = (
                session.execute(
                    select(ProviderRun).where(ProviderRun.status.in_(["queued", "running"]))
                ).scalars().all()
            )
            for run in rows:
                if run.status == "queued":
                    requeue.append(run.id)
                    continue
                if run.attempts >= max_attempts:
                    run.status = "failed"
                    run.error = "Ejecución interrumpida y agotados los reintentos."
                    run.finished_at = utcnow()
                    continue
                run.attempts += 1
                run.status = "queued"
                run.error = "Recuperado tras reinicio."
                requeue.append(run.id)
        return requeue

    # -- ejecución --------------------------------------------------------------

    def _process(self, run_id: int) -> None:
        request: Optional[RequestDict] = None
        with session_scope() as session:
            run = session.get(ProviderRun, run_id)
            if run is None or run.status not in {"queued", "running"}:
                return
            request = dict((run.details or {}).get("request") or {})
            run.status = "running"
            run.started_at = utcnow()
            run.attempts = max(1, run.attempts)
            run.error = ""
            session.flush()
            run_ref = run
        try:
            self._dispatch(request or {}, run_ref)
        except (DataError, ProviderNotConfigured) as exc:
            self._fail(run_id, str(exc))
        except Exception as exc:  # noqa: BLE001 — ningún run queda colgado
            self._fail(run_id, f"{type(exc).__name__}: {exc}")

    def _dispatch(self, request: RequestDict, run) -> None:  # run: ProviderRun (detached)
        kind = request.get("type")
        force = bool(request.get("force"))
        if kind == "fx":
            start = _parse_optional_date(request.get("start"))
            end = _parse_optional_date(request.get("end"))
            self.service.sync_fx(
                str(request.get("base") or ""),
                [str(q) for q in (request.get("quotes") or [])],
                start=start,
                end=end,
                providers=[str(p) for p in (request.get("providers") or [])] or None,
                provider_name=str(request.get("provider")) if request.get("provider") else None,
                force=force,
                run=run,
            )
            return
        if kind == "prices":
            self.service.sync_prices(
                str(request.get("instrument_uid") or ""),
                start=_parse_optional_date(request.get("start")),
                end=_parse_optional_date(request.get("end")),
                provider_name=str(request.get("provider")) if request.get("provider") else None,
                force=force,
                run=run,
            )
            return
        if kind == "fundamentals":
            self.service.sync_fundamentals(
                str(request.get("instrument_uid") or ""), force=force, run=run
            )
            return
        raise DataError(f"Tipo de trabajo de datos desconocido: {kind!r}")

    def _fail(self, run_id: int, message: str) -> None:
        with session_scope() as session:
            run = session.get(ProviderRun, run_id)
            if run is None:
                return
            if run.status in {"failed", "success", "partial", "skipped", "cached"}:
                return
            run.status = "failed"
            run.error = message[:4000]
            run.finished_at = utcnow()

    # -- planificador -----------------------------------------------------------

    def scheduled_requests(self) -> List[RequestDict]:
        """Trabajos programados: divisas configuradas + instrumentos con auto-sync."""
        requests: List[RequestDict] = []
        by_base: Dict[str, List[str]] = {}
        for base, quote in parse_pairs(self.settings.data_sync_pairs):
            by_base.setdefault(base, []).append(quote)
        for base, quotes in by_base.items():
            requests.append({
                "type": "fx",
                "provider": self.settings.fx_provider,
                "base": base,
                "quotes": quotes,
            })
            requests.append({
                "type": "fx",
                "provider": self.settings.fx_secondary_provider,
                "base": base,
                "quotes": quotes,
            })
        with session_scope() as session:
            instruments = (
                session.execute(
                    select(Instrument).where(
                        Instrument.auto_sync_prices.is_(True), Instrument.status == "active"
                    ).limit(self.settings.data_max_sync_per_run)
                ).scalars().all()
            )
            for instrument in instruments:
                requests.append({
                    "type": "prices",
                    "provider": self.settings.prices_provider,
                    "instrument_uid": instrument.uid,
                    "start": date.today().isoformat(),
                })
                if instrument.cik is not None:
                    requests.append({
                        "type": "fundamentals",
                        "provider": "sec",
                        "instrument_uid": instrument.uid,
                    })
        return requests[: self.settings.data_max_sync_per_run]

    def _scheduler_loop(self) -> None:
        interval = max(1, self.settings.data_sync_interval_minutes) * 60
        while not self._stop.wait(interval):
            try:
                for request in self.scheduled_requests():
                    if self._stop.is_set():
                        break
                    self.enqueue(request)
            except Exception as exc:  # noqa: BLE001 — el planizador no debe morir
                with session_scope() as session:
                    session.add(
                        ProviderRun(
                            provider="scheduler",
                            category="fx",
                            task_key=f"scheduler:error:{utcnow().isoformat()}",
                            status="failed",
                            error=f"{type(exc).__name__}: {exc}",
                            finished_at=datetime.now(timezone.utc),
                        )
                    )


def _parse_optional_date(value: object) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])
