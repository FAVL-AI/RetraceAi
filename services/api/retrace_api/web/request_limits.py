"""A ceiling on the request body, applied before anything reads it (RX-42, RX-51).

TWO DEFECTS MADE THIS A MIDDLEWARE RATHER THAN A HELPER.

RX-53 needs a digest of the request body before a handler runs, so the body has
to be read early. Reading it in a dependency is where both problems were:

1. **Every multipart route raised.** FastAPI parses a form BEFORE it solves
   dependencies, and Starlette's form parser consumes the request stream without
   caching the bytes. A dependency that then called ``Request.body()`` hit
   ``RuntimeError: Stream consumed`` - so ``POST .../uploads`` and
   ``POST .../evidence/imports``, the only two multipart routes, could not
   succeed at all. An unhandled ``RuntimeError`` is a 500, so the failure looked
   like a server fault rather than the wiring mistake it was.
2. **The read was unbounded.** ``Request.body()`` buffers the whole payload with
   no ceiling, which defeated the streaming cap in
   :func:`retrace_api.web.admission.read_capped`: by the time any admission rule
   saw the upload, the bytes were already resident. The documented protection
   ("the cap is applied to the stream so an oversized upload is abandoned part
   way") was not reachable, and an authenticated member could spend the
   process's memory with one request.

Both are fixed by reading the body in ASGI middleware, *outside* the router, and
replaying it downstream. The replay is the part that makes form parsing work
again: the application is handed a fresh ``receive`` that yields the buffered
body, so Starlette's parser sees an unconsumed stream.

WHY THE REFUSAL IS WRITTEN HERE AND NOT RAISED.

An exception raised in middleware that sits outside the application never
reaches the application's exception handlers, so this sends the response itself.
It is built from :meth:`ApiRefusal.envelope`, the same method the handler uses,
so there is one envelope shape and not two.

WHY SAFE METHODS ARE PASSED THROUGH UNTOUCHED.

A ``GET`` has no body worth digesting, and buffering one would add a read to
every read-only request. The pass-through is also what keeps the CORS preflight
working, which carries no body by definition.
"""

from __future__ import annotations

import json
from typing import Any, Final

from retrace_api.web.errors import RequestBodyTooLarge

__all__ = ["BODY_SCOPE_KEY", "BODY_UNBUFFERED_MESSAGE", "RequestBodyCeiling"]

#: Where the buffered body is left for the dependency to read. A scope key
#: rather than an attribute on the request: middleware and the application build
#: their own ``Request`` objects over one shared scope, so an attribute set on
#: one is invisible to the other - which is exactly how the original defect
#: hid.
BODY_SCOPE_KEY: Final = "retrace.request_body"

#: Raised when the ceiling middleware is absent. A programming error, not a
#: caller error, so it is loud: the alternative is a handler silently digesting
#: an empty body and two different requests sharing an idempotency key.
BODY_UNBUFFERED_MESSAGE: Final = (
    "the request body was not buffered; RequestBodyCeiling is not installed in front "
    "of this application. Build it with retrace_api.web.app.create_app()"
)

#: Methods whose body is not buffered.
_PASS_THROUGH_METHODS: Final[frozenset[str]] = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class RequestBodyCeiling:
    """Buffer and replay the request body, refusing anything over ``limit``."""

    def __init__(self, app: Any, *, limit: int) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        self._app = app
        self._limit = limit

    @property
    def limit(self) -> int:
        return self._limit

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or str(scope.get("method", "")).upper() in (
            _PASS_THROUGH_METHODS
        ):
            await self._app(scope, receive, send)
            return
        declared = _declared_length(scope)
        if declared is not None and declared > self._limit:
            await _send_refusal(
                send,
                RequestBodyTooLarge(
                    f"the request declares {declared} bytes, over the {self._limit} byte "
                    "ceiling; nothing was read",
                    remedy=f"send at most {self._limit} bytes, or raise "
                    "max_request_body_bytes",
                ),
            )
            return
        chunks: list[bytes] = []
        total = 0
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                # The client went away mid-body. Nothing is handed on: a partial
                # body digested as a whole one would make two different requests
                # share an idempotency key.
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self._limit:
                await _send_refusal(
                    send,
                    RequestBodyTooLarge(
                        f"the request body passed the {self._limit} byte ceiling while "
                        "being read and was abandoned; no part of it reached a handler",
                        remedy=f"send at most {self._limit} bytes, or raise "
                        "max_request_body_bytes",
                    ),
                )
                return
            chunks.append(chunk)
            more = bool(message.get("more_body", False))
        body = b"".join(chunks)
        scope[BODY_SCOPE_KEY] = body
        await self._app(scope, _replay(body), send)


def _declared_length(scope: Any) -> int | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _replay(body: bytes) -> Any:
    """A ``receive`` that yields ``body`` once, then reports a disconnect.

    The disconnect rather than a second empty body: a parser that kept asking
    would otherwise loop, and a client that has already sent its whole body has
    nothing further to send.
    """
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


async def _send_refusal(send: Any, refusal: RequestBodyTooLarge) -> None:
    payload = json.dumps(refusal.envelope()).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": refusal.status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})
