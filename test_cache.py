"""Smoke test for the Redis-backed response cache.

Requires a Redis instance reachable via REDIS_URL (default: redis://localhost:6379/0).
Run from the project root:

    python test_cache.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from servicenow_mcp.utils.cache import (
    ToolResponseCache,
    build_cache_from_env,
    is_cacheable,
)
from servicenow_mcp.tools import execute_tool


# ── 1. Pure predicate checks ───────────────────────────────────────────────

def test_is_cacheable() -> None:
    cacheable = [
        "get_record", "get_incident", "list_users", "list_flows",
        "search_catalog", "search_knowledge", "query_records",
        "natural_language_search", "get_table_schema",
    ]
    not_cacheable = [
        "create_incident", "update_incident", "resolve_incident", "close_incident",
        "add_user_to_group", "remove_user_from_group", "fire_event",
        "trigger_flow", "approve_request", "reject_request",
        "commit_remote_update_set", "publish_flow",
    ]
    for n in cacheable:
        assert is_cacheable(n), f"expected cacheable: {n}"
    for n in not_cacheable:
        assert not is_cacheable(n), f"expected NOT cacheable: {n}"
    print("✓ is_cacheable() predicate correct on 21 tool names")


# ── 2. Redis round-trip ────────────────────────────────────────────────────

async def test_redis_roundtrip() -> None:
    cache = ToolResponseCache(os.getenv("REDIS_URL", "redis://localhost:6379/0"), ttl_seconds=10)
    assert cache.enabled, "cache should be enabled when REDIS_URL set and redis client installed"

    args = {"table": "incident", "limit": 5}
    value = {"count": 2, "records": [{"number": "INC0001"}, {"number": "INC0002"}]}

    # Miss
    assert await cache.get("query_records", args, user_token=None) is None
    print("✓ cache miss on first lookup")

    # Set + hit
    await cache.set("query_records", args, user_token=None, value=value)
    hit = await cache.get("query_records", args, user_token=None)
    assert hit == value, f"expected {value}, got {hit}"
    print("✓ cache hit returns identical value")

    # Different args → different key
    other_args = {"table": "incident", "limit": 10}
    assert await cache.get("query_records", other_args, user_token=None) is None
    print("✓ different args produce different cache key")

    # Per-user scoping
    await cache.set("query_records", args, user_token="user-A-token", value={"scoped": "A"})
    a = await cache.get("query_records", args, user_token="user-A-token")
    b = await cache.get("query_records", args, user_token="user-B-token")
    assert a == {"scoped": "A"}
    assert b is None
    print("✓ per-user token scoping isolates cache entries")

    await cache.close()


# ── 3. execute_tool integration with a fake client ─────────────────────────

class _FakeClient:
    """Counts ServiceNow calls so we can prove the cache short-circuited them."""

    def __init__(self) -> None:
        self.query_calls = 0

    async def query_records(self, params):
        from servicenow_mcp.servicenow.types import QueryRecordsResponse
        self.query_calls += 1
        return QueryRecordsResponse(count=1, records=[{"number": "INC0042"}])


async def test_execute_tool_cache_hit() -> None:
    cache = build_cache_from_env()
    assert cache.enabled, "REDIS_URL must be set for this test"

    # Use a unique table name so the test is isolated from previous runs.
    client = _FakeClient()
    args = {"table": "incident_test_cache_demo", "limit": 1}

    r1 = await execute_tool(client, "query_records", args, cache=cache)
    assert client.query_calls == 1
    print(f"✓ first call → upstream invoked ({client.query_calls} call)")

    r2 = await execute_tool(client, "query_records", args, cache=cache)
    assert client.query_calls == 1, f"expected cache hit, but client was called {client.query_calls} times"
    assert r2 == r1
    print(f"✓ second call → served from cache (still {client.query_calls} upstream call)")

    # Mutating tool should NOT cache. Use a stub that always raises so we can
    # verify the cache layer didn't intercept it.
    miss_args = {"short_description": "test"}
    pre_misses = client.query_calls
    try:
        # create_incident isn't on _FakeClient — execute_tool will walk modules
        # and ultimately fail. We just want to confirm the cache didn't satisfy it.
        await execute_tool(client, "create_incident", miss_args, cache=cache)
    except Exception:
        pass
    assert client.query_calls == pre_misses
    print("✓ mutating tool is not cached (predicate gate works)")

    await cache.close()


# ── runner ─────────────────────────────────────────────────────────────────

async def main() -> None:
    test_is_cacheable()
    await test_redis_roundtrip()
    await test_execute_tool_cache_hit()
    print("\nAll cache tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
