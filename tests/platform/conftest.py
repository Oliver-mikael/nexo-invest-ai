"""Fixtures de la plataforma web.

Todas las pruebas usan:

- una base de datos SQLite temporal por prueba;
- el fixture real de companyfacts de Apple ya usado por la suite del motor;
- un proveedor de IA simulado (nunca se llama a un proveedor de pago);
- precios estáticos para la cartera.

No hay red en ninguna prueba de este directorio.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Dict, Sequence

import pytest
from fastapi.testclient import TestClient

from app.ai.base import Message
from app.ai.orchestrator import AIOrchestrator
from app.ai.providers import FakeProvider
from app.config import ProviderConfig, Settings, load_settings
from app.main import create_app
from app.security import reset_rate_limiter
from app.services.engine import EngineService
from app.services.prices import StaticPriceProvider
from nexo_invest.data.sec_edgar import (
    SecEdgarResult,
    build_registry_from_companyfacts,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "sec_companyfacts_aapl_subset.json"


def apple_result() -> SecEdgarResult:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return build_registry_from_companyfacts(payload, cik=320193, fetch_records=[])


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    base = load_settings()
    return dataclasses.replace(
        base,
        database_url=f"sqlite:///{tmp_path / 'nexo-test.db'}",
        auto_create_schema=True,
        environment="test",
        sec_contact="test@nexo.invalid",
        sec_cache_dir=str(tmp_path / "sec-cache"),
        static_dir=str(tmp_path / "no-static"),
        allow_registration=True,
        providers=[
            ProviderConfig(
                name="fake",
                kind="fake",
                base_url="fake://",
                models=["fake-1"],
            )
        ],
        ai_prices={"fake:fake-1": {"input": 0.0, "output": 0.0}},
        worker_threads=1,
        job_timeout_seconds=60,
        monthly_budget_usd=10.0,
        rate_limit_per_minute=1000,
        research_jobs_per_hour=100,
    )


@pytest.fixture()
def engine(settings: Settings) -> EngineService:
    return EngineService(settings, loader=lambda ticker: apple_result())


def role_responder(messages: Sequence[Message], model: str) -> str:
    """Respuesta JSON válida para cualquier rol, con una cifra sin respaldo a propósito.

    El 987.654.321 no existe en el expediente: el auditor determinista debe marcarlo.
    """

    user = " ".join(m.content for m in messages if m.role == "user")
    if "AUDITOR DE EVIDENCIA" in user:
        return json.dumps(
            {
                "summary": "Auditoría completada",
                "sections": {
                    "issues": [
                        {
                            "claim": "cifra inventada 987.654.321",
                            "problem": "no está en el expediente",
                            "severity": "alta",
                            "evidence_id": "metric:revenue",
                        }
                    ],
                    "contradictions": [],
                    "missing_data": ["precio de mercado verificado"],
                },
                "claims": [
                    {
                        "text": "La cifra 987.654.321 no tiene respaldo en el expediente",
                        "kind": "fact",
                        "evidence_ids": ["metric:revenue"],
                    }
                ],
                "sources": [],
            }
        )
    if "CONTRARIO" in user:
        return json.dumps(
            {
                "summary": "Riesgos de concentración y valoración exigente",
                "sections": {
                    "counter_thesis": "La valoración depende de supuestos de crecimiento no observados.",
                    "ignored_risks": ["Concentración de ingresos"],
                    "red_flags": ["Crecimiento del flujo no verificado"],
                },
                "claims": [
                    {
                        "text": "El valor por acción depende de la tasa de descuento elegida",
                        "kind": "interpretation",
                        "evidence_ids": ["valuation:base"],
                    }
                ],
                "sources": [],
            }
        )
    if "COORDINADOR" in user:
        return json.dumps(
            {
                "summary": "Tesis prudente con desacuerdo sobre el crecimiento",
                "sections": {
                    "thesis": "Calidad financiera sólida; valoración sensible a supuestos.",
                    "conclusion": "Sin precio de mercado verificado no hay margen de seguridad.",
                    "disagreements": [
                        "El analista financiero ve crecimiento estable; el contrario lo considera no verificado."
                    ],
                    "invalidation_conditions": ["Caída del margen bruto por debajo del 30%"],
                    "confidence": "media",
                },
                "claims": [],
                "sources": [],
            }
        )
    if "ANALISTA FINANCIERO" in user:
        return json.dumps(
            {
                "summary": "Márgenes elevados y deuda neta controlada",
                "sections": {
                    "quality": "Calidad alta según los indicadores del expediente.",
                    "growth": "Crecimiento moderado.",
                    "margins": "Margen bruto elevado.",
                    "cash_flow": "Conversión de caja sólida.",
                    "debt": "Deuda neta manejable.",
                    "profitability": "ROIC por encima del coste estimado.",
                    "valuation": "Valoración sensible al descuento.",
                },
                "claims": [
                    {
                        "text": "El margen bruto supera el 40%",
                        "kind": "fact",
                        "evidence_ids": ["metric:gross_margin"],
                    }
                ],
                "sources": [],
            }
        )
    if "INVESTIGADOR EMPRESARIAL" in user:
        return json.dumps(
            {
                "summary": "Negocio de productos con ecosistema integrado",
                "sections": {
                    "business_model": "Venta de hardware y servicios.",
                    "products": ["Productos de consumo", "Servicios"],
                    "market": "Mercado global de tecnología de consumo.",
                    "competitors": ["Competidores no verificados en el expediente"],
                    "moat": "Ecosistema y marca (interpretación).",
                    "strategy": "Integración vertical.",
                    "news": "No disponible sin fuente externa verificada.",
                    "catalysts": ["Ciclo de renovación de producto (interpretación)"],
                },
                "claims": [],
                "sources": [],
            }
        )
    return '{"summary": "rol no reconocido", "sections": {}, "claims": [], "sources": []}'


@pytest.fixture()
def orchestrator(settings: Settings) -> AIOrchestrator:
    provider = FakeProvider(responder=role_responder)
    return AIOrchestrator(settings, {"fake": provider})


@pytest.fixture()
def prices() -> StaticPriceProvider:
    return StaticPriceProvider({"AAPL": 230.0, "SPY": 500.0, "MSFT": 400.0})


@pytest.fixture()
def client(settings: Settings, engine: EngineService, orchestrator: AIOrchestrator, prices: StaticPriceProvider):
    reset_rate_limiter()
    app = create_app(
        settings,
        engine=engine,
        orchestrator=orchestrator,
        price_provider=prices,
        start_workers=True,
    )
    with TestClient(app) as test_client:
        test_client.app_state = app.state  # type: ignore[attr-defined]
        yield test_client


def register(client: TestClient, email: str = "analista@nexo.invalid", password: str = "clave-segura-123") -> Dict[str, Any]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": "Analista"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
