"""Planificador persistente de chequeos periódicos (Fase 6).

Complementa a `DataSyncRunner` (planificador de recopilaciones) con el
chequeo del motor de alertas. Su estado vive en la base de datos
(`system_state`), no en memoria: la reversión tras un reinicio usa la
última marca guardada, no el momento del arranque del proceso.

Naturaleza del trabajo programado:

- Alertas: **sin tráfico externo**. Evalúa reglas sobre los datos ya
  almacenados; si no hay datos nuevos, no hay nuevas alertas.
- No ejecuta ni sugiere operaciones: las alertas son informativas.

La programación de datos sigue en `DataSyncRunner` con su propia
interrupción (`data_sync_interval_minutes`), para no entrelazar dos
dominios que el operador puede querer en horarios distintos.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from sqlalchemy import select

from app.config import Settings, load_settings
from app.db import session_scope
from app.models import SystemState, utcnow
from app.services.alerts import AlertEngine

logger = logging.getLogger("nexo.scheduler")

ALERT_STATE_KEY = "scheduler.alerts"


class SchedulerService:
    """Hilo liviano que revisa alertas cada `alert_check_interval_minutes`."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or load_settings()
        self.engine = AlertEngine(self.settings)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # -- ciclo de vida ----------------------------------------------------------

    @property
    def interval_minutes(self) -> int:
        return max(0, self.settings.alert_check_interval_minutes)

    def start(self) -> None:
        if self._thread is not None:
            return
        if self.interval_minutes == 0:
            logger.info("Planificador de alertas apagado (intervalo 0).")
            return
        interval = max(30, self.interval_minutes * 60)  # nunca menos de 30 s
        self._thread = threading.Thread(
            target=self._loop, args=(interval,), name="nexo-scheduler", daemon=True
        )
        self._thread.start()
        logger.info("Planificador de alertas activo cada %s minutos.", self.interval_minutes)

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self, interval_seconds: int) -> None:
        while not self._stop.wait(interval_seconds):
            try:
                new = self.check_now()
                if new:
                    logger.info("Alertas nuevas tras el chequeo programado: %s", len(new))
            except Exception:  # noqa: BLE001 — el planificador no debe morir
                logger.exception("El chequeo programado de alertas falló.")

    # -- estado persistente -----------------------------------------------------

    @staticmethod
    def state(session) -> Dict[str, Any]:
        """Última marca persistida (o vacía si nunca se ha ejecutado)."""
        row = session.execute(
            select(SystemState).where(SystemState.key == ALERT_STATE_KEY)
        ).scalar_one_or_none()
        return dict(row.value or {}) if row is not None else {}

    @staticmethod
    def _save_state(session, payload: Dict[str, Any]) -> None:
        row = session.execute(
            select(SystemState).where(SystemState.key == ALERT_STATE_KEY)
        ).scalar_one_or_none()
        if row is None:
            session.add(SystemState(key=ALERT_STATE_KEY, value=payload))
        else:
            row.value = payload
            row.updated_at = utcnow()

    # -- operaciones ------------------------------------------------------------

    def check_now(self) -> list:
        """Evalúa alertas ahora y registra la marca persistida."""
        with session_scope() as session:
            started = utcnow()
            events = self.engine.evaluate_all(session)
            self._save_state(
                session,
                {
                    "last_run_at": started.isoformat(),
                    "finished_at": utcnow().isoformat(),
                    "new_events": len(events),
                    "interval_minutes": self.interval_minutes,
                    "trigger": "scheduler",
                },
            )
            return events

    def check_in_session(self, session) -> list:
        """Igual que `check_now` usando la sesión de la petición (API)."""
        started = utcnow()
        events = self.engine.evaluate_all(session)
        self._save_state(
            session,
            {
                "last_run_at": started.isoformat(),
                "finished_at": utcnow().isoformat(),
                "new_events": len(events),
                "interval_minutes": self.interval_minutes,
                "trigger": "manual",
            },
        )
        return events
