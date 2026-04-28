"""Tool router — aggregates all domain modules and applies role-based packaging."""
from __future__ import annotations
import os
from typing import Any

from ..servicenow.client import ServiceNowClient
from ..utils.errors import ServiceNowError

from . import core, incident  # Add more: change, problem, knowledge, catalog, ...

# Each module exposes TOOL_DEFINITIONS and execute()
_MODULES = [core, incident]

# Role-based packages (same as TypeScript version)
PACKAGE_TOOL_NAMES: dict[str, list[str]] = {
    "service_desk": [
        "query_records", "get_record", "get_table_schema",
        "create_incident", "get_incident", "update_incident",
        "resolve_incident", "close_incident", "natural_language_search",
    ],
    "change_coordinator": [
        "query_records", "get_record",
        # add change-specific tools when you create change.py
    ],
    # Add more packages as you add modules...
}


def get_tools() -> list[dict]:
    all_tools = []
    for mod in _MODULES:
        all_tools.extend(mod.TOOL_DEFINITIONS)

    package_name = os.getenv("MCP_TOOL_PACKAGE", "full").lower()
    if package_name == "full":
        return all_tools

    allowed = PACKAGE_TOOL_NAMES.get(package_name)
    if not allowed:
        return all_tools

    allowed_set = set(allowed)
    return [t for t in all_tools if t["name"] in allowed_set]


async def execute_tool(client: ServiceNowClient, name: str, args: dict[str, Any]) -> Any:
    for mod in _MODULES:
        result = await mod.execute(client, name, args)
        if result is not None:
            return result
    raise ServiceNowError(f"Unknown tool: {name}", "UNKNOWN_TOOL")
