"""Agregación de routers de la API v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    auth,
    companies,
    documents,
    imports,
    marketdata,
    markets,
    portfolio,
    real,
    reports,
    research,
    settings,
    system,
    theses,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(companies.router)
api_router.include_router(markets.router)
api_router.include_router(marketdata.router)
api_router.include_router(alerts.router)
api_router.include_router(theses.router)
api_router.include_router(theses.board_router)
api_router.include_router(real.router)
api_router.include_router(imports.router)
api_router.include_router(documents.router)
api_router.include_router(research.router)
api_router.include_router(reports.router)
api_router.include_router(portfolio.router)
api_router.include_router(settings.router)
