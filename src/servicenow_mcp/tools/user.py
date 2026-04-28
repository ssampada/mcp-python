"""User and Group Management tools. Read: Tier 0. Write: Tier 1."""
from __future__ import annotations
from typing import Any
from ..servicenow.client import ServiceNowClient
from ..servicenow.types import QueryRecordsParams
from ..utils.errors import ServiceNowError
from ..utils.permissions import require_write

TOOL_DEFINITIONS = [
    {"name": "list_users", "description": "List users with optional search", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "number"}}, "required": []}},
    {"name": "create_user", "description": "[Write] Create a user account", "inputSchema": {"type": "object", "properties": {"user_name": {"type": "string"}, "email": {"type": "string"}, "first_name": {"type": "string"}, "last_name": {"type": "string"}, "title": {"type": "string"}, "department": {"type": "string"}}, "required": ["user_name", "email", "first_name", "last_name"]}},
    {"name": "update_user", "description": "[Write] Update a user", "inputSchema": {"type": "object", "properties": {"sys_id": {"type": "string"}, "fields": {"type": "object"}}, "required": ["sys_id", "fields"]}},
    {"name": "list_groups", "description": "List groups", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "number"}}, "required": []}},
    {"name": "create_group", "description": "[Write] Create a group", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}, "manager": {"type": "string"}}, "required": ["name"]}},
    {"name": "update_group", "description": "[Write] Update a group", "inputSchema": {"type": "object", "properties": {"sys_id": {"type": "string"}, "fields": {"type": "object"}}, "required": ["sys_id", "fields"]}},
    {"name": "add_user_to_group", "description": "[Write] Add user to group", "inputSchema": {"type": "object", "properties": {"user_sys_id": {"type": "string"}, "group_sys_id": {"type": "string"}}, "required": ["user_sys_id", "group_sys_id"]}},
    {"name": "remove_user_from_group", "description": "[Write] Remove user from group", "inputSchema": {"type": "object", "properties": {"member_sys_id": {"type": "string"}}, "required": ["member_sys_id"]}},
]

async def execute(client: ServiceNowClient, name: str, args: dict[str, Any]) -> Any | None:
    if name == "list_users":
        resp = await client.query_records(QueryRecordsParams(table="sys_user", query=args.get("query", "active=true"), limit=args.get("limit", 20), fields="sys_id,user_name,email,first_name,last_name,title,department,active"))
        return {"count": resp.count, "users": resp.records}
    elif name == "create_user":
        require_write(); return await client.create_record("sys_user", args)
    elif name == "update_user":
        require_write(); return await client.update_record("sys_user", args["sys_id"], args["fields"])
    elif name == "list_groups":
        resp = await client.query_records(QueryRecordsParams(table="sys_user_group", query=args.get("query", "active=true"), limit=args.get("limit", 20), fields="sys_id,name,description,manager,active"))
        return {"count": resp.count, "groups": resp.records}
    elif name == "create_group":
        require_write(); return await client.create_record("sys_user_group", args)
    elif name == "update_group":
        require_write(); return await client.update_record("sys_user_group", args["sys_id"], args["fields"])
    elif name == "add_user_to_group":
        require_write(); return await client.create_record("sys_user_grmember", {"user": args["user_sys_id"], "group": args["group_sys_id"]})
    elif name == "remove_user_from_group":
        require_write(); await client.delete_record("sys_user_grmember", args["member_sys_id"]); return {"summary": f"Removed {args['member_sys_id']}"}
    return None
