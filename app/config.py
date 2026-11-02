"""Configuración del backend, leída íntegramente de variables de entorno.

Reglas de diseño:

- Ningún secreto se escribe en el código ni se registra en logs.
- Los valores por defecto permiten arrancar en desarrollo con SQLite y sin IA.
- Las claves de proveedores de IA solo existen en el proceso del servidor.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_json(name: str) -> Dict[str, object]:
    raw = os.environ.get(name)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Precios orientativos por millón de tokens (entrada, salida). Se pueden sobrescribir
# con NEXO_AI_PRICES para no tener que tocar código si cambian las tarifas.
DEFAULT_PRICES: Dict[str, Dict[str, float]] = {
    "openai:gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "openai:gpt-4o": {"input": 2.50, "output": 10.00},
    "anthropic:claude-3-5-haiku": {"input": 0.80, "output": 4.00},
    "anthropic:claude-3-7-sonnet": {"input": 3.00, "output": 15.00},
    "google:gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "google:gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "local:local": {"input": 0.0, "output": 0.0},
    "fake:fake-1": {"input": 0.0, "output": 0.0},
}


@dataclass(frozen=True)
class ProviderConfig:
    """Un proveedor disponible en el proceso (nunca expuesto al navegador)."""

    name: str
    kind: str  # openai | anthropic | gemini | local | fake
    api_key: str = ""
    base_url: str = ""
    models: List[str] = field(default_factory=list)

    @property
    def configured(self) -> bool:
        if self.kind in {"local", "fake"}:
            return bool(self.base_url) or self.kind == "fake"
        return bool(self.api_key)

    def public_view(self) -> Dict[str, object]:
        """Vista sin secretos: lo único que puede llegar al frontend."""
        return {
            "name": self.name,
            "kind": self.kind,
            "configured": self.configured,
            "models": list(self.models),
        }


@dataclass(frozen=True)
class Settings:
    app_name: str = "Nexo Invest AI"
    app_version: str = "2.0.0"
    api_prefix: str = "/api/v1"
    environment: str = "development"

    database_url: str = ""
    auto_create_schema: bool = True
    sql_echo: bool = False

    session_ttl_hours: int = 72
    allow_registration: bool = True
    cors_origins: List[str] = field(default_factory=list)

    rate_limit_per_minute: int = 120
    research_jobs_per_hour: int = 10
    max_concurrent_jobs_per_user: int = 2

    default_job_budget_usd: float = 0.50
    max_job_budget_usd: float = 5.00
    monthly_budget_usd: float = 10.00
    job_timeout_seconds: int = 900
    job_max_attempts: int = 2
    worker_threads: int = 2

    ai_enabled: bool = True
    ai_default_profile: str = "standard"
    providers: List[ProviderConfig] = field(default_factory=list)
    ai_prices: Dict[str, Dict[str, float]] = field(default_factory=dict)
    ai_request_timeout: float = 60.0

    sec_contact: str = ""
    sec_cache_dir: str = ""
    static_dir: str = ""

    # Documentos privados de la cartera real (nunca dentro de un directorio público).
    documents_dir: str = ""
    max_upload_bytes: int = 10 * 1024 * 1024
    max_import_rows: int = 2000

    # Fase 5: recopilación automática de datos de mercado.
    # Ningún proveedor exige clave por defecto; si un proveedor futuro necesita
    # una, su clave vive solo en el proceso del servidor, nunca en el navegador.
    fx_provider: str = "frankfurter"
    fx_secondary_provider: str = "erapi"
    prices_provider: str = "stockanalysis"
    data_sync_pairs: str = "USD/EUR,EUR/USD,USD/BOB"
    data_http_timeout_seconds: float = 20.0
    data_http_retries: int = 2
    data_backoff_seconds: float = 0.6
    data_fx_latest_ttl_minutes: int = 60
    data_fx_history_ttl_hours: int = 20
    data_prices_ttl_hours: int = 20
    data_stale_after_days: int = 5
    data_fx_divergence_threshold: float = 0.03
    # 0 mantiene el planificador apagado; las sincronizaciones manuales siguen
    # disponibles. Así no se genera tráfico externo sin que lo actives.
    data_sync_interval_minutes: int = 0
    data_max_sync_per_run: int = 25

    @property
    def database_dsn(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{DEFAULT_PROJECT_ROOT / 'var' / 'nexo.db'}"

    @property
    def is_sqlite(self) -> bool:
        return self.database_dsn.startswith("sqlite")

    def provider(self, name: str) -> Optional[ProviderConfig]:
        for provider in self.providers:
            if provider.name == name:
                return provider
        return None

    def available_models(self) -> List[Dict[str, str]]:
        models: List[Dict[str, str]] = []
        for provider in self.providers:
            if not provider.configured:
                continue
            for model in provider.models:
                models.append({"provider": provider.name, "model": model})
        return models

    def price_for(self, provider: str, model: str) -> Dict[str, float]:
        key = f"{provider}:{model}"
        if key in self.ai_prices:
            return self.ai_prices[key]
        if key in DEFAULT_PRICES:
            return DEFAULT_PRICES[key]
        kind = provider.split(":")[0]
        return DEFAULT_PRICES.get(f"{kind}:{model}", {"input": 0.0, "output": 0.0})


def _build_providers() -> List[ProviderConfig]:
    providers: List[ProviderConfig] = []
    openai_key = _env("NEXO_AI_OPENAI_KEY") or _env("OPENAI_API_KEY")
    if openai_key:
        providers.append(
            ProviderConfig(
                name="openai",
                kind="openai",
                api_key=openai_key,
                base_url=_env("NEXO_AI_OPENAI_BASE_URL", "https://api.openai.com/v1"),
                models=[
                    m
                    for m in (
                        _env("NEXO_AI_OPENAI_MODEL", "gpt-4o-mini"),
                        _env("NEXO_AI_OPENAI_MODEL_STRONG", "gpt-4o"),
                    )
                    if m
                ],
            )
        )
    anthropic_key = _env("NEXO_AI_ANTHROPIC_KEY") or _env("ANTHROPIC_API_KEY")
    if anthropic_key:
        providers.append(
            ProviderConfig(
                name="anthropic",
                kind="anthropic",
                api_key=anthropic_key,
                base_url=_env("NEXO_AI_ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
                models=[_env("NEXO_AI_ANTHROPIC_MODEL", "claude-3-5-haiku")],
            )
        )
    gemini_key = _env("NEXO_AI_GEMINI_KEY") or _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY")
    if gemini_key:
        providers.append(
            ProviderConfig(
                name="google",
                kind="gemini",
                api_key=gemini_key,
                base_url=_env(
                    "NEXO_AI_GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
                ),
                models=[_env("NEXO_AI_GEMINI_MODEL", "gemini-2.0-flash")],
            )
        )
    local_base = _env("NEXO_AI_LOCAL_BASE_URL")
    if local_base:
        providers.append(
            ProviderConfig(
                name="local",
                kind="local",
                base_url=local_base,
                models=[_env("NEXO_AI_LOCAL_MODEL", "local")],
            )
        )
    if _env_bool("NEXO_AI_FAKE_PROVIDER"):
        providers.append(
            ProviderConfig(
                name="fake",
                kind="fake",
                base_url="fake://",
                models=[_env("NEXO_AI_FAKE_MODEL", "fake-1")],
            )
        )
    return providers


def load_settings() -> Settings:
    providers = _build_providers()
    ai_disabled = _env_bool("NEXO_AI_DISABLED")
    prices = dict(DEFAULT_PRICES)
    prices.update(_env_json("NEXO_AI_PRICES"))  # type: ignore[arg-type]
    origins = [o.strip() for o in _env("NEXO_CORS_ORIGINS", "*").split(",") if o.strip()]
    return Settings(
        environment=_env("NEXO_ENV", "development"),
        database_url=_env("DATABASE_URL") or _env("NEXO_DATABASE_URL"),
        auto_create_schema=_env_bool("NEXO_AUTO_CREATE_SCHEMA", True),
        sql_echo=_env_bool("NEXO_SQL_ECHO", False),
        session_ttl_hours=_env_int("NEXO_SESSION_TTL_HOURS", 72),
        allow_registration=_env_bool("NEXO_ALLOW_REGISTRATION", True),
        cors_origins=origins or ["*"],
        rate_limit_per_minute=_env_int("NEXO_RATE_LIMIT_PER_MINUTE", 120),
        research_jobs_per_hour=_env_int("NEXO_JOBS_PER_HOUR", 10),
        max_concurrent_jobs_per_user=_env_int("NEXO_MAX_CONCURRENT_JOBS", 2),
        default_job_budget_usd=_env_float("NEXO_DEFAULT_JOB_BUDGET_USD", 0.50),
        max_job_budget_usd=_env_float("NEXO_MAX_JOB_BUDGET_USD", 5.00),
        monthly_budget_usd=_env_float("NEXO_MONTHLY_BUDGET_USD", 10.00),
        job_timeout_seconds=_env_int("NEXO_JOB_TIMEOUT_SECONDS", 900),
        job_max_attempts=_env_int("NEXO_JOB_MAX_ATTEMPTS", 2),
        worker_threads=_env_int("NEXO_WORKER_THREADS", 2),
        ai_enabled=(not ai_disabled) and bool(providers),
        ai_default_profile=_env("NEXO_AI_PROFILE", "standard"),
        providers=providers,
        ai_prices=prices,
        ai_request_timeout=_env_float("NEXO_AI_TIMEOUT_SECONDS", 60.0),
        sec_contact=_env("NEXO_SEC_CONTACT"),
        sec_cache_dir=_env("NEXO_SEC_CACHE_DIR", str(DEFAULT_PROJECT_ROOT / ".sec_cache")),
        static_dir=_env("NEXO_STATIC_DIR", str(DEFAULT_PROJECT_ROOT / "web" / "dist")),
        documents_dir=_env(
            "NEXO_DOCUMENTS_DIR", str(DEFAULT_PROJECT_ROOT / "var" / "documents")
        ),
        max_upload_bytes=_env_int("NEXO_MAX_UPLOAD_BYTES", 10 * 1024 * 1024),
        max_import_rows=_env_int("NEXO_MAX_IMPORT_ROWS", 2000),
        fx_provider=_env("NEXO_FX_PROVIDER", "frankfurter"),
        fx_secondary_provider=_env("NEXO_FX_SECONDARY_PROVIDER", "erapi"),
        prices_provider=_env("NEXO_PRICES_PROVIDER", "stockanalysis"),
        data_sync_pairs=_env("NEXO_DATA_SYNC_PAIRS", "USD/EUR,EUR/USD,USD/BOB"),
        data_http_timeout_seconds=_env_float("NEXO_DATA_TIMEOUT_SECONDS", 20.0),
        data_http_retries=_env_int("NEXO_DATA_RETRIES", 2),
        data_backoff_seconds=_env_float("NEXO_DATA_BACKOFF_SECONDS", 0.6),
        data_fx_latest_ttl_minutes=_env_int("NEXO_DATA_FX_LATEST_TTL_MINUTES", 60),
        data_fx_history_ttl_hours=_env_int("NEXO_DATA_FX_HISTORY_TTL_HOURS", 20),
        data_prices_ttl_hours=_env_int("NEXO_DATA_PRICES_TTL_HOURS", 20),
        data_stale_after_days=_env_int("NEXO_DATA_STALE_AFTER_DAYS", 5),
        data_fx_divergence_threshold=_env_float("NEXO_DATA_FX_DIVERGENCE_THRESHOLD", 0.03),
        data_sync_interval_minutes=_env_int("NEXO_DATA_SYNC_INTERVAL_MINUTES", 0),
        data_max_sync_per_run=_env_int("NEXO_DATA_MAX_SYNC_PER_RUN", 25),
    )
