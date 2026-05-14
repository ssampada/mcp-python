from typing import Any

from .request_context import request_bearer_token


class BearerPassthroughMiddleware:
    """Pure-ASGI middleware: lifts the Authorization header from every incoming
    HTTP/WebSocket request and stores the bearer token in a context variable.

    ServiceNowClient reads this var per-request, so each developer's Claude
    instance can forward its own service-account token to the shared server.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            for name, value in scope.get("headers", []):
                if name.lower() == b"authorization":
                    token = value.decode()
                    if token.lower().startswith("bearer "):
                        request_bearer_token.set(token[7:])
                    break
        await self.app(scope, receive, send)
