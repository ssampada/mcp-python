"""Problem Management tools. Read: Tier 0. Write: Tier 1."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
import re
from ..servicenow.client import ServiceNowClient
from ..servicenow.types import QueryRecordsParams
from ..utils.errors import ServiceNowError
from ..utils.permissions import require_write

TOOL_DEFINITIONS = [
    {"name": "create_problem", "description": "Create a new problem record (requires WRITE_ENABLED=true)",
     "inputSchema": {"type": "object", "properties": {
         "short_description": {"type": "string"}, "description": {"type": "string"},
         "assignment_group": {"type": "string"}, "priority": {"type": "number", "description": "1-4"}},
         "required": ["short_description"]}},
    {"name": "get_problem", "description": "Get problem by number (PRB...) or sys_id",
     "inputSchema": {"type": "object", "properties": {"number_or_sysid": {"type": "string"}}, "required": ["number_or_sysid"]}},
    {"name": "update_problem", "description": "Update problem fields (requires WRITE_ENABLED=true)",
     "inputSchema": {"type": "object", "properties": {"sys_id": {"type": "string"}, "fields": {"type": "object"}}, "required": ["sys_id", "fields"]}},
    {"name": "resolve_problem", "description": "Resolve a problem with root cause (requires WRITE_ENABLED=true)",
     "inputSchema": {"type": "object", "properties": {
         "sys_id": {"type": "string"}, "root_cause": {"type": "string"}, "resolution_notes": {"type": "string"}},
         "required": ["sys_id", "root_cause", "resolution_notes"]}},
]

async def execute(client: ServiceNowClient, name: str, args: dict[str, Any]) -> Any | None:
    if name == "create_problem":
        require_write()
        if not args.get("short_description"): raise ServiceNowError("short_description is required", "INVALID_REQUEST")
        result = await client.create_record("problem", args)
        return {**result, "summary": f"Created problem {result.get('number', result.get('sys_id'))}"}
    elif name == "get_problem":
        ident = args["number_or_sysid"]
        if re.match(r"^[0-9a-fA-F]{32}$", ident): return await client.get_record("problem", ident)
        resp = await client.query_records(QueryRecordsParams(table="problem", query=f"number={ident}^ORsys_id={ident}", limit=1))
        if resp.count == 0: raise ServiceNowError(f"Problem not found: {ident}", "NOT_FOUND")
        return resp.records[0]
    elif name == "update_problem":
        require_write()
        return await client.update_record("problem", args["sys_id"], args["fields"])
    elif name == "resolve_problem":
        require_write()
        return await client.update_record("problem", args["sys_id"], {
            "state": "107", "cause_notes": args["root_cause"], "fix_notes": args["resolution_notes"],
            "resolved_at": datetime.now(timezone.utc).isoformat()})
    return None
