"""Fase 5: automatización — cola de datos, recuperación y planificador (sin red).

`DataSyncRunner` se prueba con un servicio falso que registra las llamadas:
así se valida el encolado anti-duplicados, la recuperación de ejecuciones
interrumpidas y el planificador, sin abrir ninguna conexión externa.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select

from app.db import session_scope
from app.models import ProviderRun, utcnow
from app.services.data.runner import DataSyncRunner, task_key_for
from tests.platform.conftest import auth_headers, register


class FakeDataService:
    """Servicio falso: registra llamadas y termina el run como el real."""

    def __init__(self, gate: Optional[threading.Event] = None) -> None:
        self.gate = gate
        self.calls: List[Tuple[str, str]] = []

    def _finish(self, run, status: str = "success") -> None:
        if run is None:
            return
        with session_scope() as session:
            row = session.get(ProviderRun, run.id)
            if row is not None and row.status in {"queued", "running"}:
                row.status = status
                row.finished_at = utcnow()
                row.items_stored = 1

    def _wait_gate(self) -> None:
        if self.gate is not None:
            assert self.gate.wait(timeout=5.0), "gate no liberado"

    def sync_fx(self, base: str, quotes, *, run=None, **kwargs) -> Dict[str, object]:
        self.calls.append(("fx", base))
        self._wait_gate()
        self._finish(run)
        return {"status": "success"}

    def sync_prices(self, instrument_uid: str, *, run=None, **kwargs) -> Dict[str, object]:
        self.calls.append(("prices", instrument_uid))
        self._wait_gate()
        self._finish(run)
        return {"status": "success"}

    def sync_fundamentals(self, instrument_uid: str, *, run=None, **kwargs) -> Dict[str, object]:
        self.calls.append(("fundamentals", instrument_uid))
        self._wait_gate()
        self._finish(run)
        return {"status": "success"}


def _wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condición no alcanzada a tiempo")


def _run_status(run_id: int) -> Optional[str]:
    with session_scope() as session:
        run = session.get(ProviderRun, run_id)
        return run.status if run is not None else None


FX_REQUEST: Dict[str, object] = {
    "type": "fx",
    "provider": "frankfurter",
    "base": "USD",
    "quotes": ["BOB"],
}


def test_task_key_is_stable_and_distinct():
    same = task_key_for(dict(FX_REQUEST))
    assert same == task_key_for(dict(FX_REQUEST))
    other = task_key_for({**FX_REQUEST, "quotes": ["EUR"]})
    assert same != other
    prices = task_key_for({"type": "prices", "provider": "stockanalysis",
                           "instrument_uid": "abc", "start": None, "end": None})
    assert prices != same


def test_enqueue_deduplicates_in_flight_work(client, settings):
    """Dos encolados idénticos comparten run: una sola llamada al servicio."""
    gate = threading.Event()
    fake = FakeDataService(gate)
    runner = DataSyncRunner(settings, fake)
    runner.start()
    try:
        first = runner.enqueue(dict(FX_REQUEST))
        second = runner.enqueue(dict(FX_REQUEST))
        assert first == second

        gate.set()
        _wait_until(lambda: len(fake.calls) == 1)
        _wait_until(lambda: _run_status(first) in {"success", "failed"})
        time.sleep(0.05)  # margen para un segundo dispatch que no debe existir

        assert fake.calls == [("fx", "USD")]
        with session_scope() as session:
            runs = session.execute(select(ProviderRun)).scalars().all()
            assert len(runs) == 1
            assert runs[0].status == "success"
    finally:
        gate.set()
        runner.shutdown()


def test_interrupted_run_is_requeued_and_completed(client, settings):
    """Un run `running` interrumpido se reencola y termina al arrancar."""
    fake = FakeDataService()
    with session_scope() as session:
        run = ProviderRun(
            provider="frankfurter",
            category="fx",
            task_key="fx:frankfurter:USD:BOB:*:*:-",
            status="running",
            attempts=1,
            details={"request": dict(FX_REQUEST)},
        )
        session.add(run)
        session.flush()
        run_id = run.id

    runner = DataSyncRunner(settings, fake)
    runner.start()
    try:
        _wait_until(lambda: _run_status(run_id) == "success")
        assert fake.calls == [("fx", "USD")]
        with session_scope() as session:
            stored = session.get(ProviderRun, run_id)
            assert stored is not None
            assert stored.error == ""  # sin errores residuales
    finally:
        runner.shutdown()


def test_recover_marks_exhausted_runs_failed(client, settings):
    with session_scope() as session:
        pending = ProviderRun(
            provider="frankfurter", category="fx", task_key="fx:pending",
            status="running", attempts=0, details={"request": dict(FX_REQUEST)},
        )
        exhausted = ProviderRun(
            provider="stockanalysis", category="prices", task_key="prices:old",
            status="running", attempts=settings.job_max_attempts,
            details={"request": {"type": "prices", "instrument_uid": "x"}},
        )
        session.add_all([pending, exhausted])
        session.flush()
        pending_id, exhausted_id = pending.id, exhausted.id

    runner = DataSyncRunner(settings, FakeDataService())  # sin arrancar hilos
    requeued = runner.recover_interrupted()

    assert pending_id in requeued
    assert exhausted_id not in requeued
    assert _run_status(pending_id) == "queued"
    assert _run_status(exhausted_id) == "failed"
    with session_scope() as session:
        failed = session.get(ProviderRun, exhausted_id)
        assert failed is not None
        assert "reintentos" in failed.error


def test_scheduler_disabled_by_default(client, settings):
    """Sin intervalo configurado no hay tráfico externo automático."""
    assert settings.data_sync_interval_minutes == 0
    runner = DataSyncRunner(settings, FakeDataService())
    runner.start()
    try:
        assert runner._scheduler is None  # ningún hilo de planificación
    finally:
        runner.shutdown()


def test_scheduled_requests_cover_configured_pairs_and_auto_sync(client, settings):
    token = register(client)["access_token"]
    headers = auth_headers(token)
    response = client.post(
        "/api/v1/instruments", headers=headers,
        json={"symbol": "AAPL", "name": "Apple", "market_code": "XNAS",
              "currency": "USD", "cik": 320193},
    )
    assert response.status_code == 201, response.text
    uid = response.json()["uid"]
    client.post(
        f"/api/v1/data/instruments/{uid}/auto-sync", headers=headers,
        json={"enabled": True},
    )

    runner = DataSyncRunner(settings, FakeDataService())
    requests = runner.scheduled_requests()

    fx_pairs = {
        (r["provider"], r["base"], quote)
        for r in requests if r["type"] == "fx"
        for quote in r["quotes"]
    }
    assert ("frankfurter", "USD", "EUR") in fx_pairs
    assert ("frankfurter", "EUR", "USD") in fx_pairs
    assert ("erapi", "USD", "BOB") in fx_pairs  # segunda fuente para divergencias

    prices = [r for r in requests if r["type"] == "prices"]
    assert [r["instrument_uid"] for r in prices] == [uid]
    fundamentals = [r for r in requests if r["type"] == "fundamentals"]
    assert [r["instrument_uid"] for r in fundamentals] == [uid]  # tiene CIK

    # Instrumentos sin auto-sync no generan trabajo automático
    client.post(
        f"/api/v1/data/instruments/{uid}/auto-sync", headers=headers,
        json={"enabled": False},
    )
    runner_after = DataSyncRunner(settings, FakeDataService())
    assert [r for r in runner_after.scheduled_requests() if r["type"] == "prices"] == []


def test_enqueue_without_running_executor_fails_loudly(client, settings):
    """Sin executor activo el run no queda colgado: se marca con error."""
    runner = DataSyncRunner(settings, FakeDataService())  # start() no llamado
    run_id = runner.enqueue(dict(FX_REQUEST))
    assert _run_status(run_id) == "failed"
    with session_scope() as session:
        run = session.get(ProviderRun, run_id)
        assert run is not None
        assert "ejecutor" in run.error
