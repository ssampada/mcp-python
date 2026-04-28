from __future__ import annotations

import re
import time
import base64
from typing import Any

import httpx

from .types import ServiceNowConfig, QueryRecordsParams, QueryRecordsResponse
from ..utils.errors import ServiceNowError
from ..utils.logging import logger


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
        self._max_retries = config.max_retries
        self._retry_delay = config.retry_delay_ms / 1000.0
        self._timeout = config.request_timeout_s

        self._access_token: str | None = None
        self._token_expiry: float = 0.0

        self._http = httpx.AsyncClient(timeout=self._timeout)

    # ── Authentication ──────────────────────────────────────────────────

    async def _authenticate(self) -> None:
        if self.auth_method == "basic":
            return  # basic auth is sent inline per-request

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
        if self.auth_method == "basic" and self._basic:
            creds = base64.b64encode(
                f"{self._basic.username}:{self._basic.password}".encode()
            ).decode()
            return {"Authorization": f"Basic {creds}"}
        elif self._access_token:
            return {"Authorization": f"Bearer {self._access_token}"}
        raise ServiceNowError("No valid auth credentials", "AUTHENTICATION_FAILED")

    # ── Low-level request with retries ──────────────────────────────────

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                await self._authenticate()
                headers = {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    **self._auth_headers(),
                    **kwargs.pop("headers", {}),
                }
                resp = await self._http.request(method, url, headers=headers, **kwargs)

                if resp.status_code >= 400:
                    code_map = {401: "AUTHENTICATION_FAILED", 403: "INSUFFICIENT_PRIVILEGES",
                                404: "NOT_FOUND", 400: "INVALID_REQUEST"}
                    error_code = code_map.get(resp.status_code, "API_ERROR")
                    try:
                        msg = resp.json().get("error", {}).get("message", resp.text)
                    except Exception:
                        msg = resp.text
                    raise ServiceNowError(f"HTTP {resp.status_code}: {msg}", error_code)

                if resp.status_code == 204:
                    return None
                return resp.json()

            except ServiceNowError as e:
                if e.code in ("AUTHENTICATION_FAILED", "INVALID_REQUEST", "NOT_FOUND"):
                    raise
                last_error = e
            except Exception as e:
                last_error = e

            if attempt < self._max_retries:
                delay = self._retry_delay * (2 ** attempt)
                logger.warning(f"Request failed, retrying in {delay:.1f}s (attempt {attempt + 1})")
                import asyncio
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
