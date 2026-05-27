from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class BasicAuthConfig(BaseModel):
    username: str
    password: str


class OAuthConfig(BaseModel):
    client_id: str
    client_secret: str
    username: str
    password: str


class BearerTokenConfig(BaseModel):
    token: str


class ServiceNowConfig(BaseModel):
    instance_url: str
    auth_method: Literal["basic", "oauth", "bearer", "passthrough"] = "basic"
    basic: BasicAuthConfig | None = None
    oauth: OAuthConfig | None = None
    bearer: BearerTokenConfig | None = None
    max_retries: int = 3
    retry_delay_ms: int = 1000
    request_timeout_s: int = 30
    # Circuit breaker settings
    cb_failure_threshold: int = 5
    cb_recovery_timeout_s: int = 30
    cb_half_open_max_calls: int = 1


class QueryRecordsParams(BaseModel):
    table: str
    query: str | None = None
    fields: str | None = None
    limit: int = 10
    offset: int | None = None
    order_by: str | None = None


class QueryRecordsResponse(BaseModel):
    count: int
    records: list[dict]
