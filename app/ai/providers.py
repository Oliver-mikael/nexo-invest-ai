"""Adaptadores de proveedores de IA.

Cada adaptador traduce la interfaz común a la API concreta. Todos:

- reciben la clave solo en el constructor del servidor;
- aplican un tiempo máximo por petición;
- devuelven el texto y el consumo real de tokens;
- convierten cualquier fallo en `ProviderError` sin filtrar la clave ni el prompt
  (los mensajes se acotan a 240 caracteres y no incluyen cabeceras).
"""

from __future__ import annotations

from typing import Callable, Dict, Optional, Sequence

import httpx

from app.ai.base import (
    LLMResponse,
    Message,
    ProviderError,
    estimate_cost,
    short_error,
)


class _HttpProvider:
    name = "http"
    kind = "http"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        price: Dict[str, float],
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.price = price
        self._client = client

    def _post(self, url: str, *, headers: Dict[str, str], payload: Dict[str, object], timeout: float) -> dict:
        try:
            if self._client is not None:
                response = self._client.post(url, headers=headers, json=payload, timeout=timeout)
            else:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(f"tiempo de espera agotado ({timeout:.0f}s)") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(short_error(exc)) from exc
        if response.status_code >= 400:
            raise ProviderError(
                f"HTTP {response.status_code} de {self.name}: {_safe_body(response.text)}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("respuesta no es JSON válido") from exc
        if not isinstance(data, dict):
            raise ProviderError("respuesta con estructura inesperada")
        return data


def _safe_body(text: str) -> str:
    cleaned = " ".join(text.split())
    return cleaned[:180]


class OpenAICompatibleProvider(_HttpProvider):
    """OpenAI y cualquier servidor compatible (`/chat/completions`)."""

    name = "openai"
    kind = "openai"

    def __init__(self, *, api_key: str, base_url: str, price: Dict[str, float], name: str = "openai", client: Optional[httpx.Client] = None) -> None:
        super().__init__(api_key=api_key, base_url=base_url, price=price, client=client)
        self.name = name

    def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
    ) -> LLMResponse:
        payload = {
            "model": model,
            "messages": [m.as_dict() for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        data = self._post(f"{self.base_url}/chat/completions", headers=headers, payload=payload, timeout=timeout)
        try:
            text = str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("respuesta sin contenido de texto") from exc
        usage = data.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens") or 0)
        tokens_out = int(usage.get("completion_tokens") or 0)
        return LLMResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=model,
            provider=self.name,
            cost_usd=estimate_cost(tokens_in, tokens_out, self.price),
        )


class AnthropicProvider(_HttpProvider):
    name = "anthropic"
    kind = "anthropic"

    def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
    ) -> LLMResponse:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        conversation = [
            {"role": "assistant" if m.role == "assistant" else "user", "content": m.content}
            for m in messages
            if m.role != "system"
        ]
        payload: Dict[str, object] = {
            "model": model,
            "messages": conversation,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        data = self._post(f"{self.base_url}/v1/messages", headers=headers, payload=payload, timeout=timeout)
        blocks = data.get("content") or []
        text = "".join(
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        if not text:
            raise ProviderError("respuesta sin contenido de texto")
        usage = data.get("usage") or {}
        tokens_in = int(usage.get("input_tokens") or 0)
        tokens_out = int(usage.get("output_tokens") or 0)
        return LLMResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=model,
            provider=self.name,
            cost_usd=estimate_cost(tokens_in, tokens_out, self.price),
        )


class GeminiProvider(_HttpProvider):
    name = "google"
    kind = "gemini"

    def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
    ) -> LLMResponse:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        contents = [
            {
                "role": "model" if m.role == "assistant" else "user",
                "parts": [{"text": m.content}],
            }
            for m in messages
            if m.role != "system"
        ]
        payload: Dict[str, object] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        url = f"{self.base_url}/models/{model}:generateContent?key={self.api_key}"
        data = self._post(url, headers={"Content-Type": "application/json"}, payload=payload, timeout=timeout)
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(str(part.get("text", "")) for part in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("respuesta sin contenido de texto") from exc
        if not text:
            raise ProviderError("respuesta sin contenido de texto")
        usage = data.get("usageMetadata") or {}
        tokens_in = int(usage.get("promptTokenCount") or 0)
        tokens_out = int(usage.get("candidatesTokenCount") or 0)
        return LLMResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=model,
            provider=self.name,
            cost_usd=estimate_cost(tokens_in, tokens_out, self.price),
        )


class FakeProvider:
    """Proveedor determinista para pruebas y para el modo sin claves.

    No hace red. El texto lo produce `responder(messages, model)`; por defecto
    devuelve un JSON mínimo válido para que el pipeline pueda completarse.
    """

    name = "fake"
    kind = "fake"

    def __init__(
        self,
        *,
        responder: Optional[Callable[[Sequence[Message], str], str]] = None,
        price: Optional[Dict[str, float]] = None,
    ) -> None:
        self.responder = responder or (lambda messages, model: '{"summary": "sin contenido"}')
        self.price = price or {"input": 0.0, "output": 0.0}
        self.calls: list[Dict[str, object]] = []
        self.should_fail = False

    def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
    ) -> LLMResponse:
        self.calls.append(
            {
                "model": model,
                "max_tokens": max_tokens,
                "chars": sum(len(m.content) for m in messages),
            }
        )
        if self.should_fail:
            raise ProviderError("fallo simulado del proveedor")
        text = self.responder(messages, model)
        tokens_in = sum(len(m.content) for m in messages) // 4
        tokens_out = len(text) // 4
        return LLMResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=model,
            provider=self.name,
            cost_usd=estimate_cost(tokens_in, tokens_out, self.price),
        )


def build_provider(
    kind: str,
    *,
    api_key: str,
    base_url: str,
    price: Dict[str, float],
    name: str,
    client: Optional[httpx.Client] = None,
) -> "_HttpProvider":
    if kind == "openai":
        return OpenAICompatibleProvider(api_key=api_key, base_url=base_url, price=price, name=name, client=client)
    if kind == "anthropic":
        return AnthropicProvider(api_key=api_key, base_url=base_url, price=price, client=client)
    if kind == "gemini":
        return GeminiProvider(api_key=api_key, base_url=base_url, price=price, client=client)
    if kind == "local":
        return OpenAICompatibleProvider(api_key=api_key or "local", base_url=base_url, price=price, name=name, client=client)
    raise ProviderError(f"tipo de proveedor no soportado: {kind}")
