"""Orquestador multi-IA independiente del proveedor.

Selecciona el modelo por rol y perfil, impone presupuesto, aplica tiempos máximos y
reintentos, y devuelve resultados parciales cuando algo falla: un proveedor caído no
invalida la investigación, se degrada y queda registrado.

Perfiles:

- `basic`: sin IA. El informe se construye solo con el motor y la procedencia.
- `standard`: cinco roles con el modelo económico disponible.
- `deep`: cinco roles, con los modelos fuertes en análisis y coordinación.

El orquestador nunca inventa cifras: entrega el expediente y valida después con
`app.ai.audit` las cifras que aparecen en el texto.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app.ai.base import (
    BudgetExceeded,
    LLMProvider,
    Message,
    ModelChoice,
    ProviderError,
    Usage,
    model_label,
    short_error,
)
from app.ai.prompts import ROLE_LABELS, build_context, build_messages
from app.config import Settings, load_settings

PROFILE_ROLES: Dict[str, Tuple[str, ...]] = {
    "basic": (),
    "standard": (
        "business_researcher",
        "financial_analyst",
        "contrarian_analyst",
        "evidence_auditor",
        "coordinator",
    ),
    "deep": (
        "business_researcher",
        "financial_analyst",
        "contrarian_analyst",
        "evidence_auditor",
        "coordinator",
    ),
}

STRONG_ROLES = {"coordinator", "financial_analyst"}

ROLE_MAX_TOKENS: Dict[str, int] = {
    "business_researcher": 900,
    "financial_analyst": 900,
    "contrarian_analyst": 800,
    "evidence_auditor": 700,
    "coordinator": 900,
}

ROLE_TIMEOUTS: Dict[str, float] = {
    "business_researcher": 45.0,
    "financial_analyst": 45.0,
    "contrarian_analyst": 45.0,
    "evidence_auditor": 40.0,
    "coordinator": 50.0,
}


@dataclass
class RoleResult:
    role: str
    label: str
    status: str = "pending"  # completed | failed | skipped
    provider: str = ""
    model: str = ""
    output: Dict[str, Any] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    error: str = ""
    attempts: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "label": self.label,
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "output": self.output,
            "usage": self.usage.as_dict(),
            "error": self.error,
            "attempts": self.attempts,
        }


@dataclass
class OrchestrationResult:
    profile: str
    roles: List[RoleResult] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    budget_usd: float = 0.0
    stopped_reason: str = ""
    context_chars: int = 0

    @property
    def completed(self) -> List[RoleResult]:
        return [r for r in self.roles if r.status == "completed"]

    def by_role(self, role: str) -> Optional[RoleResult]:
        for result in self.roles:
            if result.role == role:
                return result
        return None

    def outputs(self) -> Dict[str, Dict[str, Any]]:
        return {r.role: r.output for r in self.roles if r.status == "completed"}

    def as_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile,
            "roles": [r.as_dict() for r in self.roles],
            "usage": self.usage.as_dict(),
            "budget_usd": self.budget_usd,
            "stopped_reason": self.stopped_reason,
        }


def extract_json(text: str) -> Dict[str, Any]:
    """Extrae el primer objeto JSON del texto; tolera bloques markdown."""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("la respuesta no contiene un objeto JSON")
    candidate = cleaned[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON inválido: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("la respuesta JSON no es un objeto")
    return parsed


def normalize_output(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza la estructura esperada sin rechazar contenido adicional útil."""
    sections = parsed.get("sections")
    if not isinstance(sections, dict):
        sections = {}
    claims = parsed.get("claims")
    if not isinstance(claims, list):
        claims = []
    normalized_claims: List[Dict[str, Any]] = []
    for claim in claims[:40]:
        if isinstance(claim, str):
            normalized_claims.append({"text": claim, "kind": "interpretation", "evidence_ids": []})
        elif isinstance(claim, dict):
            normalized_claims.append(
                {
                    "text": str(claim.get("text", ""))[:2000],
                    "kind": str(claim.get("kind", "interpretation")),
                    "evidence_ids": [str(x) for x in claim.get("evidence_ids", []) if x][:10],
                }
            )
    sources = parsed.get("sources")
    normalized_sources: List[Dict[str, str]] = []
    if isinstance(sources, list):
        for source in sources[:20]:
            if isinstance(source, dict):
                normalized_sources.append(
                    {
                        "title": str(source.get("title", ""))[:200],
                        "url": str(source.get("url", ""))[:500],
                    }
                )
    return {
        "summary": str(parsed.get("summary", ""))[:2000],
        "sections": {str(k)[:80]: v for k, v in list(sections.items())[:20]},
        "claims": normalized_claims,
        "sources": normalized_sources,
    }


class AIOrchestrator:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        providers: Optional[Dict[str, LLMProvider]] = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings or load_settings()
        self.providers: Dict[str, LLMProvider] = providers or {}
        self._sleep = sleep

    # -- disponibilidad y selección de modelos ---------------------------------

    @property
    def available(self) -> bool:
        return bool(self.providers)

    def available_models(self) -> List[ModelChoice]:
        models: List[ModelChoice] = []
        for provider in self.settings.providers:
            if provider.name not in self.providers:
                continue
            for model in provider.models:
                models.append(ModelChoice(provider=provider.name, model=model))
        return models

    def choose_models(
        self, profile: str, *, preferred_provider: str = ""
    ) -> Dict[str, ModelChoice]:
        profile = profile if profile in PROFILE_ROLES else "standard"
        models = self.available_models()
        if not models:
            return {}
        preferred = [m for m in models if m.provider == preferred_provider] or models
        cheap = preferred[0]
        strong = preferred[-1] if profile == "deep" else cheap
        choices: Dict[str, ModelChoice] = {}
        for role in PROFILE_ROLES.get(profile, ()):
            choices[role] = strong if (profile == "deep" and role in STRONG_ROLES) else cheap
        return choices

    def plan(self, profile: str, *, preferred_provider: str = "") -> Dict[str, Any]:
        profile = profile if profile in PROFILE_ROLES else "standard"
        if not self.available:
            return {"profile": "basic", "roles": [], "reason": "sin proveedores configurados"}
        choices = self.choose_models(profile, preferred_provider=preferred_provider)
        return {
            "profile": profile,
            "roles": [
                {"role": role, "label": ROLE_LABELS[role], "model": model_label(choice)}
                for role, choice in choices.items()
            ],
            "estimated_max_cost_usd": round(
                sum(
                    ROLE_MAX_TOKENS[role] / 1_000_000
                    * float(
                        self.settings.price_for(choice.provider, choice.model).get("output", 0.0)
                    )
                    + 4_000 / 1_000_000
                    * float(
                        self.settings.price_for(choice.provider, choice.model).get("input", 0.0)
                    )
                    for role, choice in choices.items()
                ),
                4,
            ),
        }

    # -- ejecución --------------------------------------------------------------

    def run(
        self,
        *,
        profile: str,
        identity: Dict[str, Any],
        ledger: Sequence[Dict[str, Any]],
        valuation: Dict[str, Any],
        provenance: Dict[str, Any],
        previous: Sequence[Dict[str, Any]] = (),
        budget_usd: float,
        preferred_provider: str = "",
        on_step: Optional[Callable[[RoleResult], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> OrchestrationResult:
        profile = profile if profile in PROFILE_ROLES else "standard"
        result = OrchestrationResult(profile=profile, budget_usd=budget_usd)
        roles = PROFILE_ROLES.get(profile, ())
        if not roles:
            result.stopped_reason = "perfil básico: sin llamadas a modelos"
            return result
        choices = self.choose_models(profile, preferred_provider=preferred_provider)
        if not choices:
            result.stopped_reason = "sin modelos disponibles"
            return result

        context = build_context(
            identity=identity,
            ledger=ledger,
            valuation=valuation,
            provenance=provenance,
            previous=previous,
        )
        result.context_chars = len(context)

        for role in roles:
            choice = choices[role]
            role_result = RoleResult(
                role=role, label=ROLE_LABELS[role], provider=choice.provider, model=choice.model
            )
            if should_cancel and should_cancel():
                role_result.status = "skipped"
                role_result.error = "cancelado por el usuario"
                result.roles.append(role_result)
                result.stopped_reason = "cancelado"
                break
            if result.usage.cost_usd >= budget_usd:
                role_result.status = "skipped"
                role_result.error = "presupuesto agotado"
                result.roles.append(role_result)
                result.stopped_reason = "presupuesto agotado"
                break

            extra = self._context_for(role, result)
            try:
                self._execute(role, role_result, choice, context, extra, budget_usd, result.usage)
            except BudgetExceeded:
                role_result.status = "skipped"
                role_result.error = "presupuesto agotado"
                result.stopped_reason = "presupuesto agotado"
            except Exception as exc:  # el pipeline continúa con el resto de roles
                role_result.status = "failed"
                role_result.error = short_error(exc)
            result.roles.append(role_result)
            if on_step is not None:
                on_step(role_result)
            if result.stopped_reason == "presupuesto agotado":
                break

        result.usage = Usage(
            tokens_in=sum(r.usage.tokens_in for r in result.roles),
            tokens_out=sum(r.usage.tokens_out for r in result.roles),
            cost_usd=round(sum(r.usage.cost_usd for r in result.roles), 6),
            calls=sum(r.usage.calls for r in result.roles),
        )
        return result

    def _context_for(self, role: str, partial: OrchestrationResult) -> str:
        if role != "coordinator":
            return ""
        summaries = {
            r.role: {
                "summary": r.output.get("summary", ""),
                "sections": r.output.get("sections", {}),
                "claims": r.output.get("claims", [])[:10],
            }
            for r in partial.roles
            if r.status == "completed"
        }
        return json.dumps(summaries, ensure_ascii=False, default=str)[:12000]

    def _execute(
        self,
        role: str,
        role_result: RoleResult,
        choice: ModelChoice,
        context: str,
        extra: str,
        budget_usd: float,
        usage: Usage,
    ) -> None:
        provider = self.providers.get(choice.provider)
        if provider is None:
            raise ProviderError(f"proveedor no disponible: {choice.provider}")
        max_tokens = ROLE_MAX_TOKENS.get(role, 800)
        timeout = min(ROLE_TIMEOUTS.get(role, 45.0), self.settings.ai_request_timeout)
        messages = [Message(**m) for m in build_messages(role, context, extra=extra)]
        last_error: Optional[BaseException] = None
        for attempt in range(1, 3):
            role_result.attempts = attempt
            if usage.cost_usd >= budget_usd:
                raise BudgetExceeded("presupuesto agotado")
            try:
                response = provider.complete(
                    messages,
                    model=choice.model,
                    max_tokens=max_tokens,
                    temperature=0.2,
                    timeout=timeout,
                )
            except ProviderError as exc:
                last_error = exc
                if attempt < 2:
                    self._sleep(0.4 * attempt)
                    continue
                raise
            usage.add(response)
            role_result.usage.add(response)
            # La llamada ya se pagó: se conserva su resultado y el bucle de `run`
            # detiene los roles siguientes si el presupuesto quedó agotado.
            try:
                parsed = extract_json(response.text)
            except ValueError as exc:
                last_error = exc
                if attempt < 2:
                    messages = messages + [
                        Message(
                            role="user",
                            content="La respuesta anterior no era JSON válido. Devuelve solo el objeto JSON.",
                        )
                    ]
                    continue
                raise
            role_result.output = normalize_output(parsed)
            role_result.status = "completed"
            return
        raise ProviderError(short_error(last_error or ProviderError("sin respuesta")))
