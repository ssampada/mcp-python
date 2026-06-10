"""Redis-backed response cache for read-only MCP tool calls.

When REDIS_URL is unset or Redis is unreachable, the cache silently degrades
to a no-op — the server stays functional, just without caching.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from .logging import logger

try:
    from redis import asyncio as redis_asyncio
except ImportError:
    redis_asyncio = None


_READ_ONLY_PREFIXES = ("get_", "list_", "search_", "query_")
_READ_ONLY_EXACT = {"natural_language_search"}


def is_cacheable(tool_name: str) -> bool:
    if tool_name in _READ_ONLY_EXACT:
        return True
    return any(tool_name.startswith(p) for p in _READ_ONLY_PREFIXES)


def _make_key(tool_name: str, args: dict[str, Any], user_token: str | None) -> str:
    payload = json.dumps(args, sort_keys=True, default=str)
    user_scope = hashlib.sha256(user_token.encode()).hexdigest()[:16] if user_token else "shared"
    digest = hashlib.sha256(payload.encode()).hexdigest()[:32]
    return f"snmcp:tool:{user_scope}:{tool_name}:{digest}"


class ToolResponseCache:
    """Thin async wrapper around redis.asyncio with graceful fallback."""

    def __init__(self, url: str | None, ttl_seconds: int = 60) -> None:
        self._ttl = ttl_seconds
        self._client: Any | None = None
        self._disabled = not url or redis_asyncio is None
        if self._disabled:
            return
        try:
            self._client = redis_asyncio.from_url(url, decode_responses=True)
        except Exception as e:
            logger.warning(f"Redis init failed, cache disabled: {e}")
            self._disabled = True

    @property
    def enabled(self) -> bool:
        return not self._disabled

    async def get(self, tool_name: str, args: dict[str, Any], user_token: str | None) -> Any | None:
        if self._disabled or not self._client:
            return None
        try:
            raw = await self._client.get(_make_key(tool_name, args, user_token))
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.warning(f"Redis GET failed for {tool_name}: {e}")
            return None

    async def set(self, tool_name: str, args: dict[str, Any], user_token: str | None, value: Any) -> None:
        if self._disabled or not self._client:
            return
        try:
            await self._client.setex(
                _make_key(tool_name, args, user_token),
                self._ttl,
                json.dumps(value, default=str),
            )
        except Exception as e:
            logger.warning(f"Redis SET failed for {tool_name}: {e}")

    async def close(self) -> None:
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass


def build_cache_from_env() -> ToolResponseCache:
    url = os.getenv("REDIS_URL")
    ttl = int(os.getenv("CACHE_TTL_SECONDS", "60"))
    cache = ToolResponseCache(url, ttl)
    if cache.enabled:
        logger.info(f"Response cache enabled (Redis @ {url}, TTL {ttl}s)")
    else:
        logger.info("Response cache disabled (REDIS_URL unset or redis client unavailable)")
    return cache
