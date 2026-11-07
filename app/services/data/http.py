"""Cliente HTTP de proveedores con timeout, reintentos y backoff.

Reglas:

- Ningún proveedor habla directamente con la red desde un adaptador: todo pasa
  por `HttpFetcher`, que centraliza timeout, reintentos acotados, backoff
  exponencial y la traducción de errores a excepciones tipadas.
- El número de peticiones se lleva en el propio objeto para poder registrarlo
  en cada `ProviderRun`.
- Los secretos de proveedores (si algún día hace falta alguno) se inyectan como
  cabeceras desde la configuración del servidor; nunca llegan al frontend ni a
  los logs.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Mapping, Optional

import httpx

from app.services.data.base import (
    ProviderDataError,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class HttpFetcher:
    """Envuelve `httpx.Client` con política de errores y reintentos."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        timeout: float = 20.0,
        retries: int = 2,
        backoff: float = 0.6,
        sleep: Callable[[float], None] = time.sleep,
        user_agent: str = "NexoInvestAI/2.0 (datos de mercado; contacto configurable)",
    ) -> None:
        self._client = client
        self.timeout = timeout
        self.retries = max(0, int(retries))
        self.backoff = max(0.0, float(backoff))
        self._sleep = sleep
        self.user_agent = user_agent
        self.request_count = 0

    def reset_counter(self) -> None:
        self.request_count = 0

    def get(
        self,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        accept: str = "application/json",
    ) -> httpx.Response:
        """GET con reintentos acotados. Devuelve la respuesta si el status es 2xx."""
        merged_headers = {"User-Agent": self.user_agent, "Accept": accept}
        if headers:
            merged_headers.update(headers)

        attempts = self.retries + 1
        last_error: Optional[Exception] = None
        for attempt in range(attempts):
            if attempt > 0 and self.backoff > 0:
                # Backoff exponencial: 1x, 2x, 4x… con un tope razonable.
                self._sleep(min(self.backoff * (2 ** (attempt - 1)), 30.0))
            try:
                self.request_count += 1
                response = self._client.get(
                    url, params=params, headers=merged_headers, timeout=self.timeout
                )
            except httpx.TimeoutException:
                last_error = ProviderTimeout(f"Tiempo agotado consultando {url}")
                continue
            except httpx.TransportError as exc:
                last_error = ProviderUnavailable(f"Error de red consultando {url}: {exc}")
                continue

            status = response.status_code
            if 200 <= status < 300:
                return response
            if status in RETRYABLE_STATUS:
                last_error = (
                    ProviderRateLimited(f"Proveedor limitando peticiones (429) en {url}")
                    if status == 429
                    else ProviderUnavailable(f"Proveedor no disponible ({status}) en {url}")
                )
                continue
            snippet = response.text[:180].replace("\n", " ")
            raise ProviderDataError(
                f"Respuesta inesperada {status} de {url}: {snippet}"
            )

        if isinstance(last_error, ProviderRateLimited):
            raise last_error
        if isinstance(last_error, ProviderTimeout):
            raise last_error
        if isinstance(last_error, ProviderUnavailable):
            raise last_error
        raise ProviderUnavailable(f"No se pudo consultar {url}")

    def get_json(
        self,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        response = self.get(url, params=params, headers=headers)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderDataError(
                f"Respuesta no válida de {url}: no es JSON"  # noqa: TRY003
            ) from exc

    def get_text(
        self,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        accept: str = "text/csv, text/plain, */*",
    ) -> str:
        return self.get(url, params=params, headers=headers, accept=accept).text
