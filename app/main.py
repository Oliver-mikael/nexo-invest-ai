"""Aplicación FastAPI de Nexo Invest AI.

Arranque:

    uvicorn app.main:app --host 0.0.0.0 --port 8000

El backend sirve la API en `/api/v1`, la documentación OpenAPI en `/docs` y, si
existe `web/dist`, la aplicación web (PWA) en `/`. Las rutas del cliente que no
sean ficheros se resuelven a `index.html`.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.ai.orchestrator import AIOrchestrator
from app.config import Settings, load_settings
from app.db import configure, init_db
from app.errors import install_error_handlers
from app.services.engine import EngineService
from app.services.jobs import JobRunner
from app.services.prices import PriceProvider, default_provider

logger = logging.getLogger("nexo.app")

DESCRIPTION = """
API de Nexo Invest AI: motor financiero verificable, investigaciones con IA
auditadas y cartera simulada.

- Las cifras financieras proceden de SEC EDGAR y del motor DCF; la IA nunca las
  genera.
- Cada afirmación de IA se contrasta con el expediente y las cifras sin respaldo se
  marcan en el informe.
- No emite recomendaciones de inversión ni ejecuta operaciones reales.
"""


def create_app(
    settings: Optional[Settings] = None,
    *,
    engine: Optional[EngineService] = None,
    orchestrator: Optional[AIOrchestrator] = None,
    price_provider: Optional[PriceProvider] = None,
    start_workers: bool = True,
) -> FastAPI:
    resolved = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure(resolved)
        init_db()
        app.state.settings = resolved
        app.state.engine = engine or EngineService(resolved)
        app.state.orchestrator = orchestrator or AIOrchestrator(resolved)
        app.state.prices = price_provider or default_provider(
            "yahoo", resolved.sec_cache_dir
        )
        runner = JobRunner(
            resolved,
            app.state.engine,
            app.state.orchestrator,
        )
        app.state.jobs = runner
        if start_workers:
            runner.start()
        logger.info(
            "Nexo Invest AI %s iniciado (entorno=%s, ia=%s)",
            resolved.app_version,
            resolved.environment,
            bool(app.state.orchestrator.available),
        )
        try:
            yield
        finally:
            runner.shutdown()

    application = FastAPI(
        title="Nexo Invest AI",
        version=resolved.app_version,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "Nexo Invest AI"},
        license_info={"name": "MIT"},
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins or ["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )
    install_error_handlers(application)
    application.include_router(api_router)

    static_dir = Path(resolved.static_dir)
    if static_dir.is_dir():
        assets = static_dir / "assets"
        if assets.is_dir():
            application.mount("/assets", StaticFiles(directory=assets), name="assets")

        @application.get("/{path:path}", include_in_schema=False)
        async def spa(path: str, request: Request) -> Any:  # noqa: ANN401
            if path.startswith("api/") or path in {"docs", "openapi.json", "redoc"}:
                return JSONResponse(status_code=404, content={"error": {"code": "not_found"}})
            candidate = static_dir / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            index = static_dir / "index.html"
            if index.is_file():
                return FileResponse(index)
            return JSONResponse(status_code=404, content={"error": {"code": "not_found"}})

    return application


app = create_app()
