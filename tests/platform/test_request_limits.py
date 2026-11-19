"""Límite global del cuerpo HTTP antes del parseo de la aplicación."""

from __future__ import annotations

import asyncio
import json

import pytest
from starlette.responses import JSONResponse

from app.middleware import RequestBodyLimitMiddleware


def test_oversized_content_length_is_rejected_before_app_is_called():
    sent = []
    app_called = False

    async def receive():
        raise AssertionError("oversized body should be rejected without reading it")

    async def send(message):
        sent.append(message)

    async def app(scope, app_receive, app_send):
        nonlocal app_called
        app_called = True

    middleware = RequestBodyLimitMiddleware(app, max_bytes=64)
    scope = {
        "type": "http",
        "headers": [(b"content-length", b"65")],
    }
    asyncio.run(middleware(scope, receive, send))

    response_start = next(message for message in sent if message["type"] == "http.response.start")
    response_body = next(message for message in sent if message["type"] == "http.response.body")
    assert not app_called
    assert response_start["status"] == 413
    assert json.loads(response_body["body"])["error"]["code"] == "request_too_large"



@pytest.mark.parametrize(
    "headers",
    [
        [(b"content-length", b"not-a-number")],
        [(b"content-length", b"1"), (b"content-length", b"1")],
    ],
)
def test_invalid_or_duplicate_content_length_is_rejected(headers):
    sent = []

    async def receive():
        raise AssertionError("invalid Content-Length should be rejected without reading")

    async def app(_scope, _receive, _send):
        raise AssertionError("invalid Content-Length should not reach the application")

    async def send(message):
        sent.append(message)

    middleware = RequestBodyLimitMiddleware(app, max_bytes=64)
    asyncio.run(middleware({"type": "http", "headers": headers}, receive, send))

    response_start = next(message for message in sent if message["type"] == "http.response.start")
    response_body = next(message for message in sent if message["type"] == "http.response.body")
    assert response_start["status"] == 400
    assert json.loads(response_body["body"])["error"]["code"] == "invalid_content_length"


def test_content_length_exactly_at_limit_is_forwarded():
    body = b"x" * 64
    messages = [{"type": "http.request", "body": body, "more_body": False}]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    async def app(scope, app_receive, app_send):
        message = await app_receive()
        await JSONResponse({"size": len(message["body"]) })(scope, app_receive, app_send)

    middleware = RequestBodyLimitMiddleware(app, max_bytes=len(body))
    scope = {"type": "http", "headers": [(b"content-length", str(len(body)).encode())]}
    asyncio.run(middleware(scope, receive, send))

    response_start = next(message for message in sent if message["type"] == "http.response.start")
    response_body = next(message for message in sent if message["type"] == "http.response.body")
    assert response_start["status"] == 200
    assert json.loads(response_body["body"]) == {"size": len(body)}


def test_chunked_body_is_counted_and_rejected_when_it_crosses_the_limit():
    messages = [
        {"type": "http.request", "body": b"1234", "more_body": True},
        {"type": "http.request", "body": b"5678", "more_body": True},
        {"type": "http.request", "body": b"9", "more_body": False},
    ]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    async def app(scope, app_receive, app_send):
        body = bytearray()
        while True:
            message = await app_receive()
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await JSONResponse({"size": len(body)})(scope, app_receive, app_send)

    middleware = RequestBodyLimitMiddleware(app, max_bytes=8)
    asyncio.run(middleware({"type": "http", "headers": []}, receive, send))

    response_start = next(message for message in sent if message["type"] == "http.response.start")
    response_body = next(message for message in sent if message["type"] == "http.response.body")
    assert response_start["status"] == 413
    assert json.loads(response_body["body"])["error"]["code"] == "request_too_large"
