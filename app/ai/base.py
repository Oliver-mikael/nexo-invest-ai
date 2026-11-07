"""Interfaz común de proveedores de IA.

Cualquier proveedor (OpenAI, Anthropic, Gemini, servidor local compatible con la API
de OpenAI o el proveedor simulado de pruebas) implementa `LLMProvider.complete`.
El orquestador solo conoce esta interfaz: cambiar de proveedor no toca el pipeline.

Ningún proveedor recibe claves desde el navegador: se construyen en el servidor a
partir de variables de entorno y nunca se incluyen en mensajes de error ni en logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence, runtime_checkable


class ProviderError(RuntimeError):
    """Fallo del proveedor. El mensaje nunca contiene la clave ni el prompt."""


class BudgetExceeded(RuntimeError):
    """El trabajo superó el presupuesto configurado."""


@dataclass(frozen=True)
class Message:
    role: str  # system | user | assistant
    content: str

    def as_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResponse:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""
    provider: str = ""
    cost_usd: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelChoice:
    provider: str
    model: str


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    kind: str

    def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
    ) -> LLMResponse: ...


def estimate_cost(tokens_in: int, tokens_out: int, price: Dict[str, float]) -> float:
    return round(
        tokens_in / 1_000_000 * float(price.get("input", 0.0))
        + tokens_out / 1_000_000 * float(price.get("output", 0.0)),
        6,
    )


def short_error(exc: BaseException, limit: int = 240) -> str:
    """Mensaje apto para logs y para el cliente: tipo + descripción acotada."""
    prefix = f"{type(exc).__name__}: "
    budget = max(1, limit - len(prefix))
    text = str(exc).strip().replace("\n", " ")
    if len(text) > budget:
        text = text[: max(0, budget - 3)] + "..."
    return f"{prefix}{text}" if text else type(exc).__name__


def clamp_messages(messages: List[Message]) -> List[Message]:
    return [m for m in messages if m.content and m.content.strip()]


def total_chars(messages: Sequence[Message]) -> int:
    return sum(len(m.content) for m in messages)


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    calls: int = 0

    def add(self, response: LLMResponse) -> None:
        self.tokens_in += response.tokens_in
        self.tokens_out += response.tokens_out
        self.cost_usd = round(self.cost_usd + response.cost_usd, 6)
        self.calls += 1

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "calls": self.calls,
        }


def model_label(choice: ModelChoice) -> str:
    return f"{choice.provider}:{choice.model}"


def optional_str(value: Optional[Any]) -> str:
    return "" if value is None else str(value)
