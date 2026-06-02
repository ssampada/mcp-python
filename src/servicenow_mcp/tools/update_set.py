"""Update Set management — full developer workflow for capturing and shipping
configuration changes between instances.

Tables touched:
  sys_update_set         — the update set container
  sys_update_xml         — individual record changes captured in a set
  sys_remote_update_set  — update sets retrieved from another instance
  sys_user_preference    — used to set/get the user's current update set
"""
from __future__ import annotations
import re
from typing import Any

from ..servicenow.client import ServiceNowClient
from ..servicenow.types import QueryRecordsParams
from ..utils.errors import ServiceNowError
from ..utils.permissions import require_write


_SYSID_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_CURRENT_PREF_NAME = "sys_update_set"


TOOL_DEFINITIONS = [
    # ── Read ──────────────────────────────────────────────────────────────────
    {
        "name": "list_update_sets",
        "description": "List update sets with optional state/application/name filters",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": 'Filter by state: "in progress", "complete", "ignore"'},
                "application": {"type": "string", "description": "Filter by application sys_id"},
                "name_contains": {"type": "string", "description": "Substring match on name"},
                "limit": {"type": "number", "description": "Max results (default: 25)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_update_set",
        "description": "Get an update set by sys_id or name, including a count of captured changes",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id_or_name": {"type": "string", "description": "Update set sys_id or name"},
            },
            "required": ["sys_id_or_name"],
        },
    },
    {
        "name": "list_update_set_changes",
        "description": "List the sys_update_xml records captured in a given update set",
        "inputSchema": {
            "type": "object",
            "properties": {
                "update_set_sys_id": {"type": "string"},
                "type": {"type": "string", "description": "Filter by record type (e.g. sys_script, sys_ui_policy)"},
                "limit": {"type": "number", "description": "Max results (default: 50)"},
            },
            "required": ["update_set_sys_id"],
        },
    },
    {
        "name": "get_current_update_set",
        "description": "Get the update set currently active for a user (reads sys_update_set preference)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_sys_id": {"type": "string", "description": "User sys_id (required — no implicit 'me')"},
            },
            "required": ["user_sys_id"],
        },
    },
    {
        "name": "list_remote_update_sets",
        "description": "List update sets retrieved from another instance (sys_remote_update_set)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "loaded | previewed | committed | ignore"},
                "limit": {"type": "number", "description": "Max results (default: 25)"},
            },
            "required": [],
        },
    },

    # ── Write ─────────────────────────────────────────────────────────────────
    {
        "name": "create_update_set",
        "description": "Create a new update set (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "application": {"type": "string", "description": "Scope/application sys_id (defaults to global)"},
                "release_date": {"type": "string", "description": "Optional release date (YYYY-MM-DD)"},
                "parent": {"type": "string", "description": "Parent update set sys_id (for batched/nested sets)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "update_update_set",
        "description": "Update fields on an update set (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id": {"type": "string"},
                "fields": {"type": "object", "description": "Key-value pairs (name, description, release_date, parent)"},
            },
            "required": ["sys_id", "fields"],
        },
    },
    {
        "name": "set_current_update_set",
        "description": "Set the active update set for a user via sys_user_preference (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_sys_id": {"type": "string"},
                "update_set_sys_id": {"type": "string"},
            },
            "required": ["user_sys_id", "update_set_sys_id"],
        },
    },
    {
        "name": "complete_update_set",
        "description": "Mark an update set complete (ready to export/migrate) (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {"sys_id": {"type": "string"}},
            "required": ["sys_id"],
        },
    },
    {
        "name": "reopen_update_set",
        "description": "Move a completed update set back to 'in progress' (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {"sys_id": {"type": "string"}},
            "required": ["sys_id"],
        },
    },
    {
        "name": "ignore_update_set",
        "description": "Mark an update set ignored — excludes it from exports (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {"sys_id": {"type": "string"}},
            "required": ["sys_id"],
        },
    },
    {
        "name": "move_change_to_update_set",
        "description": "Move a captured change (sys_update_xml) to a different update set (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "update_xml_sys_id": {"type": "string", "description": "sys_update_xml row sys_id"},
                "target_update_set_sys_id": {"type": "string"},
            },
            "required": ["update_xml_sys_id", "target_update_set_sys_id"],
        },
    },
    {
        "name": "preview_remote_update_set",
        "description": "Mark a remote update set as previewed. Note: the server's preview job is what actually computes problems — this transitions state only (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {"sys_id": {"type": "string"}},
            "required": ["sys_id"],
        },
    },
    {
        "name": "commit_remote_update_set",
        "description": "Commit a previewed remote update set into the local instance (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {"sys_id": {"type": "string"}},
            "required": ["sys_id"],
        },
    },
]


async def _resolve_update_set(client: ServiceNowClient, ident: str) -> dict:
    if _SYSID_RE.match(ident):
        return await client.get_record("sys_update_set", ident)
    resp = await client.query_records(QueryRecordsParams(
        table="sys_update_set", query=f"name={ident}", limit=1,
    ))
    if resp.count == 0:
        raise ServiceNowError(f"Update set not found: {ident}", "NOT_FOUND")
    return resp.records[0]


async def _set_state(client: ServiceNowClient, table: str, sys_id: str, state: str, label: str) -> dict:
    require_write()
    if not sys_id:
        raise ServiceNowError("sys_id is required", "INVALID_REQUEST")
    result = await client.update_record(table, sys_id, {"state": state})
    return {**result, "summary": f"{label} ({sys_id}) → state={state}"}


async def execute(client: ServiceNowClient, name: str, args: dict[str, Any]) -> Any | None:
    # ── Read ──────────────────────────────────────────────────────────────────
    if name == "list_update_sets":
        parts = []
        if args.get("state"):
            parts.append(f"state={args['state']}")
        if args.get("application"):
            parts.append(f"application={args['application']}")
        if args.get("name_contains"):
            parts.append(f"nameLIKE{args['name_contains']}")
        resp = await client.query_records(QueryRecordsParams(
            table="sys_update_set",
            query="^".join(parts),
            limit=args.get("limit", 25),
            fields="sys_id,name,state,description,application,parent,release_date,sys_updated_on,sys_created_by",
            order_by="-sys_updated_on",
        ))
        return {"count": resp.count, "update_sets": resp.records}

    elif name == "get_update_set":
        ident = args.get("sys_id_or_name")
        if not ident:
            raise ServiceNowError("sys_id_or_name is required", "INVALID_REQUEST")
        record = await _resolve_update_set(client, ident)
        changes = await client.query_records(QueryRecordsParams(
            table="sys_update_xml",
            query=f"update_set={record['sys_id']}",
            limit=1,
            fields="sys_id",
        ))
        return {**record, "change_count": changes.count}

    elif name == "list_update_set_changes":
        update_set_sys_id = args.get("update_set_sys_id")
        if not update_set_sys_id:
            raise ServiceNowError("update_set_sys_id is required", "INVALID_REQUEST")
        parts = [f"update_set={update_set_sys_id}"]
        if args.get("type"):
            parts.append(f"type={args['type']}")
        resp = await client.query_records(QueryRecordsParams(
            table="sys_update_xml",
            query="^".join(parts),
            limit=args.get("limit", 50),
            fields="sys_id,name,type,target_name,action,sys_updated_on,sys_updated_by",
            order_by="-sys_updated_on",
        ))
        return {"count": resp.count, "changes": resp.records}

    elif name == "get_current_update_set":
        user_sys_id = args.get("user_sys_id")
        if not user_sys_id:
            raise ServiceNowError("user_sys_id is required", "INVALID_REQUEST")
        resp = await client.query_records(QueryRecordsParams(
            table="sys_user_preference",
            query=f"user={user_sys_id}^name={_CURRENT_PREF_NAME}",
            limit=1,
            fields="sys_id,user,name,value",
        ))
        if resp.count == 0:
            return {"user_sys_id": user_sys_id, "current_update_set": None,
                    "note": "No sys_update_set preference set for this user — defaults to Default update set"}
        pref = resp.records[0]
        update_set = await client.get_record("sys_update_set", pref["value"])
        return {"preference": pref, "current_update_set": update_set}

    elif name == "list_remote_update_sets":
        parts = []
        if args.get("state"):
            parts.append(f"state={args['state']}")
        resp = await client.query_records(QueryRecordsParams(
            table="sys_remote_update_set",
            query="^".join(parts),
            limit=args.get("limit", 25),
            fields="sys_id,name,state,application_name,application_scope,description,update_source,sys_updated_on",
            order_by="-sys_updated_on",
        ))
        return {"count": resp.count, "remote_update_sets": resp.records}

    # ── Write ─────────────────────────────────────────────────────────────────
    elif name == "create_update_set":
        require_write()
        if not args.get("name"):
            raise ServiceNowError("name is required", "INVALID_REQUEST")
        data: dict[str, Any] = {"name": args["name"], "state": "in progress"}
        for k in ("description", "application", "release_date", "parent"):
            if args.get(k):
                data[k] = args[k]
        result = await client.create_record("sys_update_set", data)
        return {**result, "summary": f"Created update set '{args['name']}' ({result.get('sys_id')})"}

    elif name == "update_update_set":
        require_write()
        if not args.get("sys_id") or not args.get("fields"):
            raise ServiceNowError("sys_id and fields are required", "INVALID_REQUEST")
        result = await client.update_record("sys_update_set", args["sys_id"], args["fields"])
        return {**result, "summary": f"Updated update set {args['sys_id']}"}

    elif name == "set_current_update_set":
        require_write()
        user_sys_id = args.get("user_sys_id")
        update_set_sys_id = args.get("update_set_sys_id")
        if not user_sys_id or not update_set_sys_id:
            raise ServiceNowError("user_sys_id and update_set_sys_id are required", "INVALID_REQUEST")
        # Verify the update set exists before pinning the preference to it
        await client.get_record("sys_update_set", update_set_sys_id)
        existing = await client.query_records(QueryRecordsParams(
            table="sys_user_preference",
            query=f"user={user_sys_id}^name={_CURRENT_PREF_NAME}",
            limit=1,
            fields="sys_id",
        ))
        if existing.count > 0:
            pref_id = existing.records[0]["sys_id"]
            result = await client.update_record(
                "sys_user_preference", pref_id, {"value": update_set_sys_id},
            )
            return {**result, "summary": f"Updated user {user_sys_id} current update set → {update_set_sys_id}"}
        result = await client.create_record("sys_user_preference", {
            "user": user_sys_id,
            "name": _CURRENT_PREF_NAME,
            "value": update_set_sys_id,
            "type": "string",
        })
        return {**result, "summary": f"Set user {user_sys_id} current update set → {update_set_sys_id}"}

    elif name == "complete_update_set":
        return await _set_state(client, "sys_update_set", args.get("sys_id", ""), "complete", "Completed update set")

    elif name == "reopen_update_set":
        return await _set_state(client, "sys_update_set", args.get("sys_id", ""), "in progress", "Reopened update set")

    elif name == "ignore_update_set":
        return await _set_state(client, "sys_update_set", args.get("sys_id", ""), "ignore", "Ignored update set")

    elif name == "move_change_to_update_set":
        require_write()
        xml_id = args.get("update_xml_sys_id")
        target = args.get("target_update_set_sys_id")
        if not xml_id or not target:
            raise ServiceNowError("update_xml_sys_id and target_update_set_sys_id are required", "INVALID_REQUEST")
        result = await client.update_record("sys_update_xml", xml_id, {"update_set": target})
        return {**result, "summary": f"Moved change {xml_id} → update set {target}"}

    elif name == "preview_remote_update_set":
        return await _set_state(client, "sys_remote_update_set", args.get("sys_id", ""), "previewed", "Previewed remote update set")

    elif name == "commit_remote_update_set":
        return await _set_state(client, "sys_remote_update_set", args.get("sys_id", ""), "committed", "Committed remote update set")

    return None
