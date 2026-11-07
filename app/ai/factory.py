"""Construcción del orquestador a partir de la configuración del servidor."""

from __future__ import annotations

from typing import Callable, Dict, Optional, Sequence

from app.ai.base import LLMProvider, Message
from app.ai.orchestrator import AIOrchestrator
from app.ai.providers import FakeProvider, build_provider
from app.config import Settings, load_settings


def build_providers(settings: Settings) -> Dict[str, LLMProvider]:
    providers: Dict[str, LLMProvider] = {}
    for config in settings.providers:
        if not config.configured:
            continue
        if config.kind == "fake":
            first_model = config.models[0] if config.models else "fake-1"
            providers[config.name] = FakeProvider(
                price=settings.price_for(config.name, first_model)
            )
            continue
        try:
            providers[config.name] = build_provider(
                config.kind,
                api_key=config.api_key,
                base_url=config.base_url or "",
                price=settings.price_for(config.name, config.models[0] if config.models else ""),
                name=config.name,
            )
        except Exception:  # un proveedor mal configurado no debe tumbar la app
            continue
    return providers


def build_orchestrator(
    settings: Optional[Settings] = None,
    *,
    fake_responder: Optional[Callable[[Sequence[Message], str], str]] = None,
) -> AIOrchestrator:
    settings = settings or load_settings()
    providers = build_providers(settings)
    if fake_responder is not None:
        providers["fake"] = FakeProvider(responder=fake_responder)
    return AIOrchestrator(settings, providers)
