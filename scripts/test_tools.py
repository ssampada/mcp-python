#!/usr/bin/env python3
"""Comprehensive tool test runner — exercises all servicenow_mcp tools against a live instance.

Usage:
    python scripts/test_tools.py [--package <name>]

Only read-only (Tier 0) tools are tested by default since WRITE_ENABLED=false.
Set WRITE_ENABLED=true in .env to also run write-tier tests.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from servicenow_mcp.servicenow.client import ServiceNowClient
from servicenow_mcp.servicenow.types import (
    ServiceNowConfig,
    BasicAuthConfig,
    OAuthConfig,
    BearerTokenConfig,
)
from servicenow_mcp.tools import execute_tool, get_tools


# ── ANSI colours ─────────────────────────────────────────────────────────────
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
RESET = "\033[0m"

PASS = f"{GREEN}PASS{RESET}"
FAIL = f"{RED}FAIL{RESET}"
SKIP = f"{YELLOW}SKIP{RESET}"


# ── Build client from env ─────────────────────────────────────────────────────
def build_client() -> ServiceNowClient:
    instance_url = os.environ.get("SERVICENOW_INSTANCE_URL", "")
    if not instance_url:
        print(f"{RED}SERVICENOW_INSTANCE_URL is not set. Check your .env file.{RESET}")
        sys.exit(1)

    auth_method = os.getenv("SERVICENOW_AUTH_METHOD", "basic")
    basic = oauth = bearer = None

    if auth_method == "basic":
        basic = BasicAuthConfig(
            username=os.environ.get("SERVICENOW_BASIC_USERNAME", ""),
            password=os.environ.get("SERVICENOW_BASIC_PASSWORD", ""),
        )
    elif auth_method == "bearer":
        bearer = BearerTokenConfig(token=os.environ.get("SERVICENOW_BEARER_TOKEN", ""))
    else:
        oauth = OAuthConfig(
            client_id=os.environ.get("SERVICENOW_OAUTH_CLIENT_ID", ""),
            client_secret=os.environ.get("SERVICENOW_OAUTH_CLIENT_SECRET", ""),
            username=os.environ.get("SERVICENOW_OAUTH_USERNAME", ""),
            password=os.environ.get("SERVICENOW_OAUTH_PASSWORD", ""),
        )

    config = ServiceNowConfig(
        instance_url=instance_url,
        auth_method=auth_method,
        basic=basic,
        oauth=oauth,
        bearer=bearer,
    )
    return ServiceNowClient(config)


# ── Test cases ────────────────────────────────────────────────────────────────
# Each entry: (tool_name, args_dict, requires_write, requires_scripting, skip_reason)
# We dynamically fill some sys_ids during the run (see _collect_live_ids).

_WRITE = os.getenv("WRITE_ENABLED", "false").lower() == "true"
_SCRIPT = os.getenv("SCRIPTING_ENABLED", "false").lower() == "true"

# Placeholders filled after first live queries
_IDS: dict[str, str] = {}


def _w(tool: str, args: dict, note: str = "") -> tuple:
    return (tool, args, True, False, note or "WRITE_ENABLED=false")


def _s(tool: str, args: dict, note: str = "") -> tuple:
    return (tool, args, False, True, note or "SCRIPTING_ENABLED=false")


TEST_CASES: list[tuple[str, dict, bool, bool, str]] = [
    # ── Core ──────────────────────────────────────────────────────────────
    ("query_records", {"table": "incident", "limit": 3}, False, False, ""),
    ("query_records", {"table": "sys_user", "query": "active=true", "limit": 2}, False, False, ""),
    ("get_table_schema", {"table": "incident"}, False, False, ""),
    ("get_table_schema", {"table": "change_request"}, False, False, ""),
    ("natural_language_search", {"query": "network outage", "limit": 3}, False, False, ""),
    # get_record filled dynamically after incident query

    # ── Incident ──────────────────────────────────────────────────────────
    # get_incident, update_incident, resolve_incident, close_incident filled dynamically
    _w("create_incident", {"short_description": "MCP test incident — safe to close", "urgency": 3, "impact": 3}),

    # ── Problem ───────────────────────────────────────────────────────────
    ("query_records", {"table": "problem", "limit": 2}, False, False, ""),
    _w("create_problem", {"short_description": "MCP test problem — safe to close"}),

    # ── Change ────────────────────────────────────────────────────────────
    ("query_records", {"table": "change_request", "limit": 2}, False, False, ""),

    # ── Task ─────────────────────────────────────────────────────────────
    ("query_records", {"table": "task", "limit": 2}, False, False, ""),

    # ── Catalog ───────────────────────────────────────────────────────────
    ("list_catalog_items", {}, False, False, ""),
    ("search_catalog", {"query": "laptop"}, False, False, ""),
    ("list_approvals", {}, False, False, ""),
    ("get_my_approvals", {}, False, False, ""),
    ("list_active_slas", {}, False, False, ""),
    _w("create_catalog_item", {"name": "MCP Test Item", "short_description": "test item from MCP runner"}),

    # ── Knowledge ─────────────────────────────────────────────────────────
    ("list_knowledge_bases", {}, False, False, ""),
    ("search_knowledge", {"query": "password reset"}, False, False, ""),
    # create_knowledge_article filled dynamically (needs kb sys_id)

    # ── User & Groups ─────────────────────────────────────────────────────
    ("list_users", {"limit": 5}, False, False, ""),
    ("list_groups", {"limit": 5}, False, False, ""),
    _w("create_user", {"user_name": "mcp_test_user", "email": "mcp_test@example.com", "first_name": "MCP", "last_name": "Test"}),

    # ── Flow Designer ─────────────────────────────────────────────────────
    ("list_flows", {"limit": 5}, False, False, ""),
    ("list_subflows", {"limit": 5}, False, False, ""),
    ("list_action_instances", {"limit": 5}, False, False, ""),
    ("list_process_automations", {"limit": 5}, False, False, ""),
    # get_flow, list_flow_executions, get_flow_error_log filled dynamically

    # ── Integration ───────────────────────────────────────────────────────
    ("list_rest_messages", {"limit": 5}, False, False, ""),
    ("list_transform_maps", {"limit": 5}, False, False, ""),
    ("list_import_sets", {"limit": 5}, False, False, ""),
    ("list_data_sources", {"limit": 5}, False, False, ""),
    ("list_event_registry", {"limit": 5}, False, False, ""),
    ("list_event_log", {"limit": 5}, False, False, ""),
    ("list_oauth_applications", {"limit": 5}, False, False, ""),
    ("list_credential_aliases", {"limit": 5}, False, False, ""),

    # ── Scripting ─────────────────────────────────────────────────────────
    ("list_business_rules", {"limit": 5}, False, False, ""),
    ("list_script_includes", {"limit": 5}, False, False, ""),
    ("list_client_scripts", {"limit": 5}, False, False, ""),
    ("list_changesets", {"limit": 5}, False, False, ""),
    ("list_ui_policies", {"limit": 5}, False, False, ""),
    ("list_ui_actions", {"limit": 5}, False, False, ""),
    ("list_acls", {"limit": 5}, False, False, ""),
    _s("create_business_rule", {
        "name": "MCP Test Rule",
        "table": "incident",
        "when": "before",
        "script": "// test",
    }),
]


async def _collect_live_ids(client: ServiceNowClient) -> None:
    """Pre-fetch a few sys_ids so dynamic tests can use them."""
    from servicenow_mcp.servicenow.types import QueryRecordsParams

    # Incident
    r = await client.query_records(QueryRecordsParams(table="incident", limit=1, fields="sys_id,number"))
    if r.records:
        rec = r.records[0]
        _IDS["incident_sys_id"] = rec.get("sys_id", {})
        if isinstance(_IDS["incident_sys_id"], dict):
            _IDS["incident_sys_id"] = _IDS["incident_sys_id"].get("value", "")
        _IDS["incident_number"] = rec.get("number", {})
        if isinstance(_IDS["incident_number"], dict):
            _IDS["incident_number"] = _IDS["incident_number"].get("value", "")

    # Flow
    r = await client.query_records(QueryRecordsParams(table="sys_hub_flow", limit=1, fields="sys_id,name"))
    if r.records:
        val = r.records[0].get("sys_id", {})
        _IDS["flow_sys_id"] = val.get("value", val) if isinstance(val, dict) else val

    # Knowledge base
    r = await client.query_records(QueryRecordsParams(table="kb_knowledge_base", limit=1, fields="sys_id"))
    if r.records:
        val = r.records[0].get("sys_id", {})
        _IDS["kb_sys_id"] = val.get("value", val) if isinstance(val, dict) else val


def _build_dynamic_tests() -> list[tuple[str, dict, bool, bool, str]]:
    """Build test cases that depend on live IDs fetched above."""
    cases = []

    if _IDS.get("incident_sys_id"):
        cases.append(("get_record", {"table": "incident", "sys_id": _IDS["incident_sys_id"]}, False, False, ""))
        cases.append(("get_incident", {"number_or_sysid": _IDS.get("incident_number", _IDS["incident_sys_id"])}, False, False, ""))
        cases.append(_w("update_incident", {"sys_id": _IDS["incident_sys_id"], "fields": {"description": "updated by MCP test"}}))
        cases.append(_w("resolve_incident", {"sys_id": _IDS["incident_sys_id"], "resolution_code": "Solved (Permanently)", "resolution_notes": "test resolution"}))
        cases.append(_w("close_incident", {"sys_id": _IDS["incident_sys_id"]}))

    if _IDS.get("kb_sys_id"):
        cases.append(_w("create_knowledge_article", {
            "short_description": "MCP test article",
            "text": "<p>Test article body</p>",
            "knowledge_base_sys_id": _IDS["kb_sys_id"],
        }))

    if _IDS.get("flow_sys_id"):
        cases.append(("get_flow", {"name_or_sysid": _IDS["flow_sys_id"]}, False, False, ""))
        cases.append(("list_flow_executions", {"flow_sys_id": _IDS["flow_sys_id"], "limit": 5}, False, False, ""))
        cases.append(("get_flow_error_log", {"flow_sys_id": _IDS["flow_sys_id"], "days": 7, "limit": 5}, False, False, ""))

    return cases


async def run_test(
    client: ServiceNowClient,
    tool_name: str,
    args: dict,
    requires_write: bool,
    requires_scripting: bool,
    skip_reason: str,
) -> tuple[str, str, float]:
    """Returns (status, detail, elapsed_ms)."""
    if requires_scripting and not _SCRIPT:
        return "skip", f"requires SCRIPTING_ENABLED=true ({skip_reason})", 0.0
    if requires_write and not _WRITE:
        return "skip", f"requires WRITE_ENABLED=true ({skip_reason})", 0.0

    t0 = time.perf_counter()
    try:
        result = await execute_tool(client, tool_name, args)
        elapsed = (time.perf_counter() - t0) * 1000

        # Basic response validation
        if result is None:
            return "fail", "tool returned None (expected a result dict or string)", elapsed

        detail = ""
        if isinstance(result, dict):
            # Show count or first key
            if "count" in result:
                detail = f"count={result['count']}"
            elif "records" in result:
                detail = f"records={len(result['records'])}"
            elif "summary" in result:
                detail = result["summary"][:80]
            else:
                detail = f"keys={list(result.keys())[:5]}"
        elif isinstance(result, str):
            detail = result[:80]

        return "pass", detail, elapsed

    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        return "fail", str(e)[:120], elapsed


async def main() -> None:
    print(f"\n{BOLD}{CYAN}ServiceNow MCP Tool Test Runner{RESET}")
    print(f"Instance : {os.getenv('SERVICENOW_INSTANCE_URL')}")
    print(f"Auth     : {os.getenv('SERVICENOW_AUTH_METHOD', 'basic')}")
    print(f"Write    : {'enabled' if _WRITE else 'disabled (set WRITE_ENABLED=true to enable)'}")
    print(f"Scripting: {'enabled' if _SCRIPT else 'disabled'}")
    print()

    client = build_client()

    # Pre-fetch IDs for dynamic tests
    print(f"{CYAN}Pre-fetching live record IDs…{RESET}")
    try:
        await _collect_live_ids(client)
        print(f"  incident: {_IDS.get('incident_number', 'not found')}")
        print(f"  flow    : {_IDS.get('flow_sys_id', 'not found')}")
        print(f"  kb      : {_IDS.get('kb_sys_id', 'not found')}")
    except Exception as e:
        print(f"  {YELLOW}Warning: could not pre-fetch IDs: {e}{RESET}")
    print()

    # Build full test list
    all_tests = list(TEST_CASES) + _build_dynamic_tests()

    # Only run tests for tools actually registered (respects MCP_TOOL_PACKAGE)
    registered_names = {t["name"] for t in get_tools()}

    col_w = 38
    header = f"{'Tool':<{col_w}} {'Result':<8} {'Detail':<55} {'ms':>6}"
    print(f"{BOLD}{header}{RESET}")
    print("-" * (col_w + 8 + 55 + 8))

    passed = failed = skipped = 0

    for tool_name, args, req_write, req_script, skip_reason in all_tests:
        if tool_name not in registered_names and not tool_name.startswith("query_records") and not tool_name.startswith("get_record"):
            # query_records and get_record are always registered; others might not be
            if tool_name not in registered_names:
                print(f"{tool_name:<{col_w}} {SKIP:<8} not in MCP_TOOL_PACKAGE")
                skipped += 1
                continue

        status, detail, elapsed = await run_test(client, tool_name, args, req_write, req_script, skip_reason)

        if status == "pass":
            badge = PASS
            passed += 1
        elif status == "skip":
            badge = SKIP
            skipped += 1
        else:
            badge = FAIL
            failed += 1

        ms_str = f"{elapsed:.0f}" if elapsed else ""
        print(f"{tool_name:<{col_w}} {badge:<8} {detail:<55} {ms_str:>6}")

    await client.close()

    print()
    print("-" * (col_w + 8 + 55 + 8))
    total = passed + failed + skipped
    print(
        f"{BOLD}Results: "
        f"{GREEN}{passed} passed{RESET}  "
        f"{RED}{failed} failed{RESET}  "
        f"{YELLOW}{skipped} skipped{RESET}  "
        f"({total} total){RESET}"
    )
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
