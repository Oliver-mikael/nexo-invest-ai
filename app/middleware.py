"""Límites HTTP anteriores al parseo de cuerpos multipart o JSON."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Rechaza cuerpos grandes antes de almacenarlos o procesarlos por completo."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max(0, max_bytes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_lengths = [
            value for name, value in scope.get("headers", []) if name.lower() == b"content-length"
        ]
        if len(content_lengths) > 1:
            await self._reject(scope, receive, send, 400, "invalid_content_length")
            return
        if content_lengths:
            raw_length = content_lengths[0].strip()
            if not raw_length.isdigit():
                await self._reject(scope, receive, send, 400, "invalid_content_length")
                return
            if int(raw_length) > self.max_bytes:
                await self._reject(scope, receive, send, 413, "request_too_large")
                return

        received_bytes = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_bytes:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await self._reject(scope, receive, send, 413, "request_too_large")

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        code: str,
    ) -> None:
        message = (
            "El cuerpo de la solicitud supera el límite permitido."
            if status_code == 413
            else "La cabecera Content-Length no es válida."
        )
        response = JSONResponse(
            status_code=status_code,
            content={"error": {"code": code, "message": message, "details": {}}},
        )
        await response(scope, receive, send)
