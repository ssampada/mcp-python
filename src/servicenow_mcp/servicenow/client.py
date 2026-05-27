from __future__ import annotations

import asyncio
import random
import re
import time
import base64
from enum import Enum
from typing import Any

import httpx

from .types import ServiceNowConfig, QueryRecordsParams, QueryRecordsResponse
from ..utils.errors import ServiceNowError
from ..utils.logging import logger
from ..utils.request_context import request_bearer_token


# ── Circuit Breaker ─────────────────────────────────────────────────────

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(ServiceNowError):
    def __init__(self, until: float) -> None:
        remaining = max(0, until - time.monotonic())
        super().__init__(
            f"Circuit breaker is OPEN — retry after {remaining:.0f}s",
            "CIRCUIT_OPEN",
        )


class CircuitBreaker:
    """Thread-safe circuit breaker for shared ServiceNow instances."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    async def _maybe_transition_to_half_open(self) -> None:
        if (
            self._state == CircuitState.OPEN
            and time.monotonic() - self._last_failure_time >= self._recovery_timeout
        ):
            logger.info("Circuit breaker transitioning OPEN → HALF_OPEN")
            self._state = CircuitState.HALF_OPEN
            self._half_open_calls = 0

    async def before_request(self) -> None:
        async with self._lock:
            await self._maybe_transition_to_half_open()

            if self._state == CircuitState.OPEN:
                raise CircuitBreakerOpen(
                    self._last_failure_time + self._recovery_timeout
                )

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self._half_open_max_calls:
                    raise CircuitBreakerOpen(
                        self._last_failure_time + self._recovery_timeout
                    )
                self._half_open_calls += 1

    async def record_success(self) -> None:
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                logger.info("Circuit breaker transitioning HALF_OPEN → CLOSED")
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_calls = 0

    async def record_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                logger.warning("Circuit breaker transitioning HALF_OPEN → OPEN")
                self._state = CircuitState.OPEN
            elif self._failure_count >= self._failure_threshold:
                logger.warning(
                    f"Circuit breaker OPEN after {self._failure_count} consecutive failures"
                )
                self._state = CircuitState.OPEN


def _validate_table_name(table: str) -> str:
    if not table or not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", table):
        raise ServiceNowError(
            f'Invalid table name: "{table}". Must contain only letters, numbers, and underscores.',
            "VALIDATION_ERROR",
        )
    return table


def _validate_sys_id(sys_id: str) -> str:
    if not sys_id or not re.match(r"^[0-9a-fA-F]{32}$", sys_id):
        raise ServiceNowError(
            f'Invalid sys_id: "{sys_id}". Must be a 32-character hex string.',
            "VALIDATION_ERROR",
        )
    return sys_id


class ServiceNowClient:
    """Async HTTP client for the ServiceNow REST API."""

    def __init__(self, config: ServiceNowConfig) -> None:
        self.base_url = config.instance_url.rstrip("/")
        self.auth_method = config.auth_method
        self._basic = config.basic
        self._oauth = config.oauth
        self._bearer = config.bearer
        self._max_retries = config.max_retries
        self._retry_delay = config.retry_delay_ms / 1000.0
        self._timeout = config.request_timeout_s

        self._access_token: str | None = None
        self._token_expiry: float = 0.0

        self._http = httpx.AsyncClient(timeout=self._timeout)

        self._circuit = CircuitBreaker(
            failure_threshold=config.cb_failure_threshold,
            recovery_timeout=config.cb_recovery_timeout_s,
            half_open_max_calls=config.cb_half_open_max_calls,
        )

    # ── Authentication ──────────────────────────────────────────────────

    async def _authenticate(self) -> None:
        if self.auth_method in ("basic", "bearer", "passthrough"):
            return  # basic/bearer/passthrough auth is sent inline per-request

        # Reuse valid OAuth token
        if self._access_token and time.time() < self._token_expiry:
            return

        if not self._oauth:
            raise ServiceNowError("OAuth config is required for oauth auth method", "AUTHENTICATION_FAILED")

        token_url = f"{self.base_url}/oauth_token.do"
        data = {
            "grant_type": "password",
            "client_id": self._oauth.client_id,
            "client_secret": self._oauth.client_secret,
            "username": self._oauth.username,
            "password": self._oauth.password,
        }

        resp = await self._http.post(token_url, data=data)
        if resp.status_code != 200:
            raise ServiceNowError(f"OAuth failed: {resp.status_code} {resp.text}", "AUTHENTICATION_FAILED")

        token_data = resp.json()
        self._access_token = token_data["access_token"]
        self._token_expiry = time.time() + token_data["expires_in"] * 0.9

    def _auth_headers(self) -> dict[str, str]:
        per_request_token = request_bearer_token.get()
        if per_request_token:
            return {"Authorization": f"Bearer {per_request_token}"}

        if self.auth_method == "passthrough":
            raise ServiceNowError(
                "No Authorization header on request. Each user must provide their own ServiceNow bearer token.",
                "AUTHENTICATION_FAILED",
            )
        if self.auth_method == "basic" and self._basic:
            creds = base64.b64encode(
                f"{self._basic.username}:{self._basic.password}".encode()
            ).decode()
            return {"Authorization": f"Basic {creds}"}
        elif self.auth_method == "bearer" and self._bearer:
            return {"Authorization": f"Bearer {self._bearer.token}"}
        elif self._access_token:
            return {"Authorization": f"Bearer {self._access_token}"}
        raise ServiceNowError("No valid auth credentials", "AUTHENTICATION_FAILED")

    # ── Low-level request with retries + circuit breaker ─────────────────

    _NON_RETRYABLE = frozenset({"AUTHENTICATION_FAILED", "INVALID_REQUEST", "NOT_FOUND", "INSUFFICIENT_PRIVILEGES"})

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        # Circuit breaker gate — fast-fail when the instance is unreachable
        await self._circuit.before_request()

        last_error: Exception | None = None
        extra_headers = kwargs.pop("headers", {})

        for attempt in range(self._max_retries + 1):
            try:
                await self._authenticate()
                headers = {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    **self._auth_headers(),
                    **extra_headers,
                }
                resp = await self._http.request(method, url, headers=headers, **kwargs)

                # ── Rate-limit handling (429) ───────────────────────────
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else self._retry_delay * (2 ** attempt)
                    logger.warning(f"Rate-limited (429), backing off {delay:.1f}s (attempt {attempt + 1})")
                    await asyncio.sleep(delay)
                    continue

                if resp.status_code >= 400:
                    code_map = {401: "AUTHENTICATION_FAILED", 403: "INSUFFICIENT_PRIVILEGES",
                                404: "NOT_FOUND", 400: "INVALID_REQUEST"}
                    error_code = code_map.get(resp.status_code, "API_ERROR")
                    try:
                        msg = resp.json().get("error", {}).get("message", resp.text)
                    except Exception:
                        msg = resp.text
                    raise ServiceNowError(f"HTTP {resp.status_code}: {msg}", error_code)

                # Success — record it for the circuit breaker
                await self._circuit.record_success()

                if resp.status_code == 204:
                    return None
                return resp.json()

            except ServiceNowError as e:
                if e.code in self._NON_RETRYABLE:
                    raise
                last_error = e
                await self._circuit.record_failure()
            except httpx.TimeoutException as e:
                last_error = e
                await self._circuit.record_failure()
            except Exception as e:
                last_error = e
                await self._circuit.record_failure()

            if attempt < self._max_retries:
                # Exponential backoff with full jitter to spread concurrent callers
                base_delay = self._retry_delay * (2 ** attempt)
                delay = random.uniform(0, base_delay)
                logger.warning(f"Request failed, retrying in {delay:.1f}s (attempt {attempt + 1}/{self._max_retries})")
                await asyncio.sleep(delay)

        raise last_error or ServiceNowError("Request failed after retries", "NETWORK_ERROR")

    # ── CRUD Operations ─────────────────────────────────────────────────

    async def query_records(self, params: QueryRecordsParams) -> QueryRecordsResponse:
        _validate_table_name(params.table)
        qp: dict[str, str] = {}
        if params.query:
            qp["sysparm_query"] = params.query
        if params.fields:
            qp["sysparm_fields"] = params.fields
        qp["sysparm_limit"] = str(min(params.limit, 1000))
        if params.offset is not None:
            qp["sysparm_offset"] = str(params.offset)
        if params.order_by:
            order_clause = (
                f"ORDERBY{params.order_by[1:]}^ORDERBYDESC"
                if params.order_by.startswith("-")
                else f"ORDERBY{params.order_by}"
            )
            qp["sysparm_query"] = f"{qp.get('sysparm_query', '')}^{order_clause}".lstrip("^")

        url = f"{self.base_url}/api/now/table/{params.table}"
        logger.info(f"Querying table: {params.table}")
        data = await self._request("GET", url, params=qp)
        records = data.get("result", [])
        return QueryRecordsResponse(count=len(records), records=records)

    async def get_record(self, table: str, sys_id: str, fields: str | None = None) -> dict:
        _validate_table_name(table)
        _validate_sys_id(sys_id)
        qp: dict[str, str] = {}
        if fields:
            qp["sysparm_fields"] = fields
        url = f"{self.base_url}/api/now/table/{table}/{sys_id}"
        data = await self._request("GET", url, params=qp)
        return data["result"]

    async def create_record(self, table: str, data: dict) -> dict:
        _validate_table_name(table)
        url = f"{self.base_url}/api/now/table/{table}"
        logger.info(f"Creating record in {table}")
        resp = await self._request("POST", url, json=data)
        return resp["result"]

    async def update_record(self, table: str, sys_id: str, data: dict) -> dict:
        _validate_table_name(table)
        _validate_sys_id(sys_id)
        url = f"{self.base_url}/api/now/table/{table}/{sys_id}"
        logger.info(f"Updating record {sys_id} in {table}")
        resp = await self._request("PATCH", url, json=data)
        return resp["result"]

    async def delete_record(self, table: str, sys_id: str) -> None:
        _validate_table_name(table)
        _validate_sys_id(sys_id)
        url = f"{self.base_url}/api/now/table/{table}/{sys_id}"
        logger.info(f"Deleting record {sys_id} from {table}")
        await self._request("DELETE", url)

    async def get_user(self, identifier: str) -> dict:
        if re.match(r"^[0-9a-fA-F]{32}$", identifier):
            return await self.get_record("sys_user", identifier)
        query = f"user_name={identifier}^ORemail={identifier}"
        url = f"{self.base_url}/api/now/table/sys_user"
        data = await self._request("GET", url, params={"sysparm_query": query, "sysparm_limit": "1"})
        if not data["result"]:
            raise ServiceNowError(f"User not found: {identifier}", "NOT_FOUND")
        return data["result"][0]

    async def search_cmdb_ci(self, query: str | None = None, limit: int = 10) -> QueryRecordsResponse:
        qp: dict[str, str] = {"sysparm_limit": str(min(limit, 100))}
        if query:
            qp["sysparm_query"] = query
        url = f"{self.base_url}/api/now/table/cmdb_ci"
        data = await self._request("GET", url, params=qp)
        records = data.get("result", [])
        return QueryRecordsResponse(count=len(records), records=records)

    async def run_aggregate(self, table: str, group_by: str, query: str | None = None) -> Any:
        qp: dict[str, str] = {"sysparm_group_by": group_by, "sysparm_count": "true"}
        if query:
            qp["sysparm_query"] = query
        url = f"{self.base_url}/api/now/stats/{table}"
        data = await self._request("GET", url, params=qp)
        return data.get("result", [])

    async def close(self) -> None:
        await self._http.aclose()
