"""Incident management tools — full ITSM lifecycle."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

from ..servicenow.client import ServiceNowClient
from ..utils.errors import ServiceNowError
from ..utils.permissions import require_write


TOOL_DEFINITIONS = [
    {
        "name": "create_incident",
        "description": "Create a new incident (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "short_description": {"type": "string", "description": "Brief description"},
                "urgency": {"type": "number", "description": "1=High, 2=Medium, 3=Low"},
                "impact": {"type": "number", "description": "1=High, 2=Medium, 3=Low"},
                "description": {"type": "string"},
                "assignment_group": {"type": "string"},
                "caller_id": {"type": "string"},
                "category": {"type": "string"},
            },
            "required": ["short_description"],
        },
    },
    {
        "name": "get_incident",
        "description": "Get incident by number (INC0012345) or sys_id",
        "inputSchema": {
            "type": "object",
            "properties": {
                "number_or_sysid": {"type": "string", "description": "Incident number or sys_id"},
            },
            "required": ["number_or_sysid"],
        },
    },
    {
        "name": "update_incident",
        "description": "Update fields on an incident (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id": {"type": "string"},
                "fields": {"type": "object", "description": "Key-value pairs to update"},
            },
            "required": ["sys_id", "fields"],
        },
    },
    {
        "name": "resolve_incident",
        "description": "Resolve an incident (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id": {"type": "string"},
                "resolution_code": {"type": "string"},
                "resolution_notes": {"type": "string"},
            },
            "required": ["sys_id", "resolution_code", "resolution_notes"],
        },
    },
    {
        "name": "close_incident",
        "description": "Close a resolved incident (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {"sys_id": {"type": "string"}},
            "required": ["sys_id"],
        },
    },
]


async def execute(client: ServiceNowClient, name: str, args: dict[str, Any]) -> Any | None:
    import re

    if name == "create_incident":
        require_write()
        if not args.get("short_description"):
            raise ServiceNowError("short_description is required", "INVALID_REQUEST")
        result = await client.create_record("incident", args)
        return {**result, "summary": f"Created incident {result.get('number', result.get('sys_id'))}"}

    elif name == "get_incident":
        identifier = args.get("number_or_sysid", "")
        if re.match(r"^[0-9a-fA-F]{32}$", identifier):
            return await client.get_record("incident", identifier)
        from ..servicenow.types import QueryRecordsParams
        resp = await client.query_records(
            QueryRecordsParams(table="incident", query=f"number={identifier}", limit=1)
        )
        if resp.count == 0:
            raise ServiceNowError(f"Incident not found: {identifier}", "NOT_FOUND")
        return resp.records[0]

    elif name == "update_incident":
        require_write()
        return await client.update_record("incident", args["sys_id"], args["fields"])

    elif name == "resolve_incident":
        require_write()
        return await client.update_record("incident", args["sys_id"], {
            "state": "6",
            "close_code": args["resolution_code"],
            "close_notes": args["resolution_notes"],
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        })

    elif name == "close_incident":
        require_write()
        return await client.update_record("incident", args["sys_id"], {"state": "7"})

    return None  # Not handled by this module
