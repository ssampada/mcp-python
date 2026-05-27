"""OAuth 2.0 Authorization Server that proxies to ServiceNow.

End users see ServiceNow's login page — no bearer tokens to understand.
The MCP client (GitHub Copilot) drives the OAuth flow automatically.

Flow:
  1. MCP client discovers /.well-known/oauth-authorization-server
  2. Client redirects user to /authorize → we redirect to ServiceNow login
  3. User logs in with their normal ServiceNow credentials
  4. ServiceNow redirects back to /oauth/callback with an auth code
  5. We exchange that code for a ServiceNow token (server-side, keeps client_secret safe)
  6. We issue our own auth code and redirect back to the MCP client
  7. Client calls /token to get the ServiceNow access token
  8. Client sends that token on every MCP request — BearerPassthroughMiddleware forwards it
"""
from __future__ import annotations

import hashlib
import base64
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode, parse_qs

import httpx

from .logging import logger


class _AuthStore:
    """In-memory store for OAuth state and auth codes."""

    def __init__(self, ttl: int = 600, max_entries: int = 10_000) -> None:
        self._ttl = ttl
        self._max = max_entries
        self._pending: dict[str, dict] = {}
        self._codes: dict[str, dict] = {}

    def store_pending(self, state: str, data: dict) -> None:
        self._cleanup()
        data["created_at"] = time.time()
        self._pending[state] = data

    def pop_pending(self, state: str) -> dict | None:
        self._cleanup()
        return self._pending.pop(state, None)

    def store_code(self, code: str, data: dict) -> None:
        self._cleanup()
        data["created_at"] = time.time()
        self._codes[code] = data

    def pop_code(self, code: str) -> dict | None:
        self._cleanup()
        return self._codes.pop(code, None)

    def _cleanup(self) -> None:
        now = time.time()
        self._pending = {
            k: v for k, v in self._pending.items()
            if now - v["created_at"] < self._ttl
        }
        self._codes = {
            k: v for k, v in self._codes.items()
            if now - v["created_at"] < self._ttl
        }


def _verify_pkce(code_verifier: str, code_challenge: str, method: str) -> bool:
    if method == "S256":
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return secrets.compare_digest(computed, code_challenge)
    if method == "plain":
        return secrets.compare_digest(code_verifier, code_challenge)
    return False


class OAuthProxyMiddleware:
    """ASGI middleware: OAuth 2.0 Authorization Server that delegates to ServiceNow."""

    def __init__(
        self,
        app: Any,
        instance_url: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        self.app = app
        self.instance_url = instance_url.rstrip("/")
        self.sn_client_id = client_id
        self.sn_client_secret = client_secret
        self._store = _AuthStore()

    def _base_url(self, scope: dict) -> str:
        host = "localhost:8000"
        scheme = "http"
        for name, value in scope.get("headers", []):
            if name == b"host":
                host = value.decode()
            elif name == b"x-forwarded-proto":
                scheme = value.decode()
        return f"{scheme}://{host}"

    def _query_params(self, scope: dict) -> dict[str, str]:
        qs = scope.get("query_string", b"").decode()
        return {k: v[0] for k, v in parse_qs(qs).items()}

    async def _read_body(self, receive: Any) -> bytes:
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body", False):
                break
        return body

    async def _send_json(self, send: Any, status: int, data: dict, extra_headers: list | None = None) -> None:
        body = json.dumps(data).encode()
        headers: list[list[bytes]] = [
            [b"content-type", b"application/json"],
            [b"content-length", str(len(body)).encode()],
        ]
        if extra_headers:
            headers.extend(extra_headers)
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def _send_redirect(self, send: Any, url: str) -> None:
        await send({
            "type": "http.response.start",
            "status": 302,
            "headers": [[b"location", url.encode()], [b"content-length", b"0"]],
        })
        await send({"type": "http.response.body", "body": b""})

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        handlers = {
            ("GET", "/.well-known/oauth-authorization-server"): self._metadata,
            ("POST", "/register"): self._register,
            ("GET", "/authorize"): self._authorize,
            ("GET", "/oauth/callback"): self._callback,
            ("POST", "/token"): self._token,
        }

        handler = handlers.get((method, path))
        if handler:
            await handler(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    # ── GET /.well-known/oauth-authorization-server ────────────────────

    async def _metadata(self, scope: dict, receive: Any, send: Any) -> None:
        base = self._base_url(scope)
        await self._send_json(send, 200, {
            "issuer": base,
            "authorization_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token",
            "registration_endpoint": f"{base}/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
        }, [[b"cache-control", b"public, max-age=3600"]])

    # ── POST /register  (Dynamic Client Registration) ─────────────────

    async def _register(self, scope: dict, receive: Any, send: Any) -> None:
        body = await self._read_body(receive)
        try:
            req = json.loads(body) if body else {}
        except json.JSONDecodeError:
            req = {}

        await self._send_json(send, 201, {
            "client_id": secrets.token_urlsafe(32),
            "client_name": req.get("client_name", "MCP Client"),
            "redirect_uris": req.get("redirect_uris", []),
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        })

    # ── GET /authorize ─────────────────────────────────────────────────

    async def _authorize(self, scope: dict, receive: Any, send: Any) -> None:
        params = self._query_params(scope)
        base = self._base_url(scope)

        client_redirect = params.get("redirect_uri", "")
        if not client_redirect:
            await self._send_json(send, 400, {"error": "redirect_uri is required"})
            return

        internal_state = secrets.token_urlsafe(32)
        self._store.store_pending(internal_state, {
            "client_redirect_uri": client_redirect,
            "client_state": params.get("state", ""),
            "code_challenge": params.get("code_challenge", ""),
            "code_challenge_method": params.get("code_challenge_method", "S256"),
        })

        sn_params = urlencode({
            "response_type": "code",
            "client_id": self.sn_client_id,
            "redirect_uri": f"{base}/oauth/callback",
            "state": internal_state,
        })
        await self._send_redirect(send, f"{self.instance_url}/oauth_auth.do?{sn_params}")

    # ── GET /oauth/callback  (ServiceNow redirects here) ──────────────

    async def _callback(self, scope: dict, receive: Any, send: Any) -> None:
        params = self._query_params(scope)
        base = self._base_url(scope)

        if "error" in params:
            logger.error(f"ServiceNow OAuth error: {params.get('error_description', params['error'])}")
            await self._send_json(send, 400, {
                "error": params["error"],
                "error_description": params.get("error_description", ""),
            })
            return

        pending = self._store.pop_pending(params.get("state", ""))
        if not pending:
            await self._send_json(send, 400, {"error": "invalid_state", "error_description": "Unknown or expired OAuth state"})
            return

        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(f"{self.instance_url}/oauth_token.do", data={
                "grant_type": "authorization_code",
                "code": params.get("code", ""),
                "client_id": self.sn_client_id,
                "client_secret": self.sn_client_secret,
                "redirect_uri": f"{base}/oauth/callback",
            })

        if resp.status_code != 200:
            logger.error(f"ServiceNow token exchange failed: {resp.status_code}")
            await self._send_json(send, 502, {"error": "token_exchange_failed"})
            return

        sn_token = resp.json()

        our_code = secrets.token_urlsafe(48)
        self._store.store_code(our_code, {
            "access_token": sn_token["access_token"],
            "refresh_token": sn_token.get("refresh_token", ""),
            "token_type": "Bearer",
            "expires_in": sn_token.get("expires_in", 1800),
            "code_challenge": pending.get("code_challenge", ""),
            "code_challenge_method": pending.get("code_challenge_method", "S256"),
        })

        redirect_params: dict[str, str] = {"code": our_code}
        if pending["client_state"]:
            redirect_params["state"] = pending["client_state"]

        sep = "&" if "?" in pending["client_redirect_uri"] else "?"
        await self._send_redirect(send, f"{pending['client_redirect_uri']}{sep}{urlencode(redirect_params)}")

    # ── POST /token ────────────────────────────────────────────────────

    async def _token(self, scope: dict, receive: Any, send: Any) -> None:
        body = await self._read_body(receive)
        params = {k: v[0] for k, v in parse_qs(body.decode()).items()}
        grant_type = params.get("grant_type", "")

        if grant_type == "authorization_code":
            await self._exchange_code(params, send)
        elif grant_type == "refresh_token":
            await self._refresh(params, send)
        else:
            await self._send_json(send, 400, {"error": "unsupported_grant_type"})

    async def _exchange_code(self, params: dict[str, str], send: Any) -> None:
        token_data = self._store.pop_code(params.get("code", ""))
        if not token_data:
            await self._send_json(send, 400, {
                "error": "invalid_grant",
                "error_description": "Invalid or expired authorization code",
            })
            return

        code_challenge = token_data.pop("code_challenge", "")
        code_challenge_method = token_data.pop("code_challenge_method", "S256")
        token_data.pop("created_at", None)

        if code_challenge:
            verifier = params.get("code_verifier", "")
            if not verifier or not _verify_pkce(verifier, code_challenge, code_challenge_method):
                await self._send_json(send, 400, {
                    "error": "invalid_grant",
                    "error_description": "PKCE verification failed",
                })
                return

        await self._send_json(send, 200, token_data)

    async def _refresh(self, params: dict[str, str], send: Any) -> None:
        refresh_token = params.get("refresh_token", "")
        if not refresh_token:
            await self._send_json(send, 400, {"error": "invalid_request"})
            return

        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(f"{self.instance_url}/oauth_token.do", data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.sn_client_id,
                "client_secret": self.sn_client_secret,
            })

        if resp.status_code != 200:
            await self._send_json(send, 400, {"error": "invalid_grant", "error_description": "Refresh failed"})
            return

        await self._send_json(send, 200, resp.json())
