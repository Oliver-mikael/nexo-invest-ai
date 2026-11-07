"""Proceso worker independiente (Fase 6).

El backend web no debe ser el único que ejecuta trabajos: este módulo
arranca las colas persistentes (`ResearchJob` y `ProviderRun`) y el
planificador en un proceso propio:

    python3 -m app.worker

Con esto las sincronizaciones de datos, recuperaciones y chequeos de
alertas continúan aunque la API se reinicie o no exista todavía. En una
instancia puede ejecutarse en su lugar el backend con `NEXO_WORKER_EMBEDDED`
(los arranques del API ya los levantan); en varias réplicas, redis/una cola
compartida será el siguiente paso documentado (DECISIONS, decisión 62).
"""

from __future__ import annotations

import logging
import signal
from threading import Event

from app.config import load_settings
from app.db import configure, init_db
from app.services.data.runner import DataSyncRunner
from app.services.data.sync import DataSyncService
from app.services.engine import EngineService
from app.services.jobs import JobRunner
from app.services.reference import seed_markets
from app.services.scheduler import SchedulerService
from app.ai.orchestrator import AIOrchestrator

logger = logging.getLogger("nexo.worker")
_stop = Event()


def _handle_signal(signum, _frame) -> None:  # noqa: ANN001 — firmas de signal
    logger.info("Worker recibe señal %s: apagado ordenado.", signum)
    _stop.set()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    configure(settings)
    init_db()
    seed_markets()
    engine = EngineService(settings)
    orchestrator = AIOrchestrator(settings)
    data_service = DataSyncService(settings)

    research = JobRunner(settings, engine, orchestrator)
    data = DataSyncRunner(settings, data_service)
    scheduler = SchedulerService(settings)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    research.start()
    data.start()
    scheduler.start()
    logger.info(
        "Worker de Nexo Invest AI operación (ia=%s, planificador_alertas=%s).",
        bool(orchestrator.available),
        scheduler.interval_minutes,
    )
    try:
        _stop.wait()
    finally:
        scheduler.shutdown()
        data.shutdown()
        data_service.close()
        research.shutdown()
        logger.info("Worker detenido.")


if __name__ == "__main__":
    main()
