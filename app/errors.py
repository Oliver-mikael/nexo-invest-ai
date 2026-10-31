"""Errores uniformes de la API.

Formato único para cualquier fallo:

    {"error": {"code": "not_found", "message": "...", "details": {}}}

Los mensajes internos (trazas, SQL, claves) nunca llegan al cliente.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("nexo.api")


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def error_body(code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = []
        for item in exc.errors()[:20]:
            fields.append(
                {
                    "field": ".".join(str(part) for part in item.get("loc", [])[1:]) or "body",
                    "message": item.get("msg", "valor no válido"),
                }
            )
        return JSONResponse(
            status_code=422,
            content=error_body(
                "validation_error",
                "Alguna entrada no es válida.",
                {"fields": fields},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            429: "rate_limited",
        }.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Error no controlado en %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=error_body(
                "internal_error",
                "Error interno del servidor. El incidente quedó registrado.",
            ),
        )
