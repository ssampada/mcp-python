"""Scripting Management tools — Business Rules, Script Includes, Client Scripts,
UI Policies, UI Actions, and ACLs.
All tools require SCRIPTING_ENABLED=true (Tier 3).
Note: ServiceNow supports ES2021 (async/await, ?., ??) in script bodies.
Update Set management has moved to tools/update_set.py.
"""
from __future__ import annotations
import re
from typing import Any

from ..servicenow.client import ServiceNowClient
from ..servicenow.types import QueryRecordsParams
from ..utils.errors import ServiceNowError
from ..utils.permissions import require_scripting

TOOL_DEFINITIONS = [
    # ── Business Rules ────────────────────────────────────────────────────────
    {
        "name": "list_business_rules",
        "description": "List business rules (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Filter by table name"},
                "active": {"type": "boolean", "description": "Filter to active rules only"},
                "limit": {"type": "number", "description": "Max results (default: 20)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_business_rule",
        "description": "Get full details and script body of a business rule (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id": {"type": "string", "description": "System ID of the business rule"},
            },
            "required": ["sys_id"],
        },
    },
    {
        "name": "create_business_rule",
        "description": 'Create a new business rule (requires SCRIPTING_ENABLED=true). ServiceNow supports ES2021 async/await in scripts.',
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Rule name"},
                "table": {"type": "string", "description": "Table this rule applies to"},
                "when": {"type": "string", "description": '"before" | "after" | "async" | "display"'},
                "script": {"type": "string", "description": "Server-side JavaScript. ServiceNow supports ES2021 (async/await, ?., ??)."},
                "condition": {"type": "string", "description": "Optional condition script"},
                "active": {"type": "boolean", "description": "Whether to activate the rule (default: true)"},
                "order": {"type": "number", "description": "Execution order (default: 100)"},
            },
            "required": ["name", "table", "when", "script"],
        },
    },
    {
        "name": "update_business_rule",
        "description": "Update a business rule (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id": {"type": "string", "description": "System ID of the rule"},
                "fields": {"type": "object", "description": "Key-value pairs to update (name, script, active, condition, etc.)"},
            },
            "required": ["sys_id", "fields"],
        },
    },
    # ── Script Includes ───────────────────────────────────────────────────────
    {
        "name": "list_script_includes",
        "description": "List script includes (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": 'Filter (e.g., "nameLIKEUtil")'},
                "active": {"type": "boolean", "description": "Filter to active includes"},
                "limit": {"type": "number", "description": "Max results (default: 20)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_script_include",
        "description": "Get full script body of a script include (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id_or_name": {"type": "string", "description": "Script include sys_id or api_name"},
            },
            "required": ["sys_id_or_name"],
        },
    },
    {
        "name": "create_script_include",
        "description": "Create a new script include (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Script include name"},
                "script": {"type": "string", "description": "Script body (class definition). ServiceNow supports ES2021."},
                "api_name": {"type": "string", "description": "API name used to call this from other scripts"},
                "access": {"type": "string", "description": '"public" or "package_private" (default: "public")'},
                "active": {"type": "boolean", "description": "Whether to activate (default: true)"},
            },
            "required": ["name", "script"],
        },
    },
    {
        "name": "update_script_include",
        "description": "Update a script include (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id": {"type": "string", "description": "System ID of the script include"},
                "fields": {"type": "object", "description": "Key-value pairs to update"},
            },
            "required": ["sys_id", "fields"],
        },
    },
    # ── Client Scripts ────────────────────────────────────────────────────────
    {
        "name": "list_client_scripts",
        "description": "List client scripts (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Filter by table name"},
                "type": {"type": "string", "description": '"onLoad" | "onChange" | "onSubmit" | "onCellEdit"'},
                "active": {"type": "boolean", "description": "Filter to active scripts"},
                "limit": {"type": "number", "description": "Max results (default: 20)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_client_script",
        "description": "Get full details and script body of a client script (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id": {"type": "string", "description": "System ID of the client script"},
            },
            "required": ["sys_id"],
        },
    },
    {
        "name": "create_client_script",
        "description": "Create a new client script (onLoad, onChange, onSubmit, onCellEdit) (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Script name"},
                "table": {"type": "string", "description": "Table this client script applies to"},
                "type": {"type": "string", "description": '"onLoad" | "onChange" | "onSubmit" | "onCellEdit"'},
                "script": {"type": "string", "description": "Client-side JavaScript. Use g_form, g_user, etc."},
                "field_name": {"type": "string", "description": "Field name (required for onChange/onCellEdit)"},
                "active": {"type": "boolean", "description": "Whether to activate the script (default: true)"},
                "global": {"type": "boolean", "description": "Run script globally (default: false)"},
            },
            "required": ["name", "table", "type", "script"],
        },
    },
    {
        "name": "update_client_script",
        "description": "Update an existing client script (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id": {"type": "string", "description": "Client script sys_id"},
                "fields": {"type": "object", "description": "Fields to update (script, active, name, type, etc.)"},
            },
            "required": ["sys_id", "fields"],
        },
    },
    # ── UI Policies ───────────────────────────────────────────────────────────
    {
        "name": "list_ui_policies",
        "description": "List UI Policies for a table (field visibility, mandatory, read-only rules) (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Filter by table name"},
                "active": {"type": "boolean", "description": "Filter to active policies only"},
                "limit": {"type": "number", "description": "Max results (default: 25)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_ui_policy",
        "description": "Get full details and conditions of a UI Policy (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id": {"type": "string", "description": "UI Policy sys_id"},
            },
            "required": ["sys_id"],
        },
    },
    {
        "name": "create_ui_policy",
        "description": "Create a new UI Policy to control field behavior dynamically (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "short_description": {"type": "string", "description": "Policy description"},
                "table": {"type": "string", "description": "Table to apply this policy on"},
                "conditions": {"type": "string", "description": "Encoded query conditions that trigger the policy"},
                "script": {"type": "string", "description": "Optional script to run when conditions are met"},
                "active": {"type": "boolean", "description": "Whether to activate immediately (default: true)"},
                "run_scripts": {"type": "boolean", "description": "Run script in addition to UI actions (default: false)"},
            },
            "required": ["short_description", "table"],
        },
    },
    # ── UI Actions ────────────────────────────────────────────────────────────
    {
        "name": "list_ui_actions",
        "description": "List UI Actions (buttons, context menus, related links) for a table (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Filter by table name"},
                "type": {"type": "string", "description": "Filter by type: button, context_menu, related_link, list_link, list_button, list_context_menu"},
                "active": {"type": "boolean", "description": "Filter to active actions only"},
                "limit": {"type": "number", "description": "Max results (default: 25)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_ui_action",
        "description": "Get full details and script of a UI Action (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id": {"type": "string", "description": "UI Action sys_id"},
            },
            "required": ["sys_id"],
        },
    },
    {
        "name": "create_ui_action",
        "description": "Create a new UI Action (button or link) on a form (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Button/link label visible to users"},
                "table": {"type": "string", "description": "Table to add this action on"},
                "action_name": {"type": "string", "description": "Internal action name (no spaces)"},
                "script": {"type": "string", "description": "Server-side script to execute when clicked"},
                "type": {"type": "string", "description": '"button" | "context_menu" | "related_link" | "list_button"'},
                "condition": {"type": "string", "description": "Condition to show/hide the action"},
                "active": {"type": "boolean", "description": "Whether to activate immediately (default: true)"},
                "form_button": {"type": "boolean", "description": "Show on form (default: true)"},
                "list_button": {"type": "boolean", "description": "Show on list (default: false)"},
            },
            "required": ["name", "table", "action_name"],
        },
    },
    {
        "name": "update_ui_action",
        "description": "Update an existing UI Action (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id": {"type": "string", "description": "UI Action sys_id"},
                "fields": {"type": "object", "description": "Fields to update (name, script, active, condition, etc.)"},
            },
            "required": ["sys_id", "fields"],
        },
    },
    # ── ACL Management ────────────────────────────────────────────────────────
    {
        "name": "list_acls",
        "description": "List Access Control rules (ACLs) — who can read/write/create/delete records (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Filter ACLs by table name"},
                "operation": {"type": "string", "description": "Filter by operation: read, write, create, delete, execute"},
                "active": {"type": "boolean", "description": "Filter to active ACLs only"},
                "limit": {"type": "number", "description": "Max results (default: 25)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_acl",
        "description": "Get full details of an ACL rule including its script and role requirements (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id": {"type": "string", "description": "ACL sys_id"},
            },
            "required": ["sys_id"],
        },
    },
    {
        "name": "create_acl",
        "description": "Create a new ACL rule to control access to a table or field (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": 'ACL name (typically "table.field" or "table.*")'},
                "type": {"type": "string", "description": '"record" | "field" | "rest_endpoint" | "soap_endpoint"'},
                "operation": {"type": "string", "description": '"read" | "write" | "create" | "delete" | "execute"'},
                "admin_overrides": {"type": "boolean", "description": "Allow admin to override (default: true)"},
                "active": {"type": "boolean", "description": "Whether to activate immediately (default: true)"},
                "script": {"type": "string", "description": "Optional condition script (return true to allow)"},
                "roles": {"type": "string", "description": 'Comma-separated roles required (e.g. "admin,itil")'},
                "description": {"type": "string", "description": "Description of this access rule"},
            },
            "required": ["name", "operation"],
        },
    },
    {
        "name": "update_acl",
        "description": "Update an existing ACL rule (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id": {"type": "string", "description": "ACL sys_id"},
                "fields": {"type": "object", "description": "Fields to update (active, script, roles, condition, etc.)"},
            },
            "required": ["sys_id", "fields"],
        },
    },
]


async def execute(client: ServiceNowClient, name: str, args: dict[str, Any]) -> Any | None:
    # All scripting tools require SCRIPTING_ENABLED
    _SCRIPTING_TOOLS = {t["name"] for t in TOOL_DEFINITIONS}
    if name not in _SCRIPTING_TOOLS:
        return None
    require_scripting()

    # ── Business Rules ────────────────────────────────────────────────────────
    if name == "list_business_rules":
        parts: list[str] = []
        if args.get("active") is not None:
            parts.append(f"active={args['active']}")
        if args.get("table"):
            parts.append(f"collection={args['table']}")
        resp = await client.query_records(QueryRecordsParams(
            table="sys_script",
            query="^".join(parts),
            limit=args.get("limit", 20),
            fields="sys_id,name,collection,when,active,order,sys_updated_on",
        ))
        return {"count": resp.count, "business_rules": resp.records,
                "note": "ServiceNow supports ES2021 (async/await, ?., ??) in script bodies"}

    elif name == "get_business_rule":
        if not args.get("sys_id"):
            raise ServiceNowError("sys_id is required", "INVALID_REQUEST")
        return await client.get_record("sys_script", args["sys_id"])

    elif name == "create_business_rule":
        if not args.get("name") or not args.get("table") or not args.get("when") or not args.get("script"):
            raise ServiceNowError("name, table, when, and script are required", "INVALID_REQUEST")
        data: dict[str, Any] = {
            "name": args["name"],
            "collection": args["table"],
            "when": args["when"],
            "script": args["script"],
            "active": args.get("active", True),
            "order": args.get("order", 100),
        }
        if args.get("condition"):
            data["condition"] = args["condition"]
        result = await client.create_record("sys_script", data)
        return {**result, "summary": f"Created business rule {args['name']}",
                "note": "GlideEncrypter is deprecated; use sn_si.Vault or keystore APIs instead"}

    elif name == "update_business_rule":
        if not args.get("sys_id") or not args.get("fields"):
            raise ServiceNowError("sys_id and fields are required", "INVALID_REQUEST")
        result = await client.update_record("sys_script", args["sys_id"], args["fields"])
        return {**result, "summary": f"Updated business rule {args['sys_id']}"}

    # ── Script Includes ───────────────────────────────────────────────────────
    elif name == "list_script_includes":
        parts = []
        if args.get("active") is not None:
            parts.append(f"active={args['active']}")
        if args.get("query"):
            parts.append(args["query"])
        resp = await client.query_records(QueryRecordsParams(
            table="sys_script_include",
            query="^".join(parts),
            limit=args.get("limit", 20),
            fields="sys_id,name,api_name,active,access,sys_updated_on",
        ))
        return {"count": resp.count, "script_includes": resp.records}

    elif name == "get_script_include":
        ident = args.get("sys_id_or_name")
        if not ident:
            raise ServiceNowError("sys_id_or_name is required", "INVALID_REQUEST")
        if re.match(r"^[0-9a-fA-F]{32}$", ident):
            return await client.get_record("sys_script_include", ident)
        resp = await client.query_records(QueryRecordsParams(
            table="sys_script_include", query=f"api_name={ident}^ORname={ident}", limit=1
        ))
        if resp.count == 0:
            raise ServiceNowError(f"Script include not found: {ident}", "NOT_FOUND")
        return resp.records[0]

    elif name == "create_script_include":
        if not args.get("name") or not args.get("script"):
            raise ServiceNowError("name and script are required", "INVALID_REQUEST")
        result = await client.create_record("sys_script_include", {
            "name": args["name"],
            "script": args["script"],
            "api_name": args.get("api_name", args["name"]),
            "access": args.get("access", "public"),
            "active": args.get("active", True),
        })
        return {**result, "summary": f"Created script include {args['name']}",
                "note": "ES2021 (async/await, ?., ??) supported in the latest release"}

    elif name == "update_script_include":
        if not args.get("sys_id") or not args.get("fields"):
            raise ServiceNowError("sys_id and fields are required", "INVALID_REQUEST")
        return await client.update_record("sys_script_include", args["sys_id"], args["fields"])

    # ── Client Scripts ────────────────────────────────────────────────────────
    elif name == "list_client_scripts":
        parts = []
        if args.get("active") is not None:
            parts.append(f"active={args['active']}")
        if args.get("table"):
            parts.append(f"table={args['table']}")
        if args.get("type"):
            parts.append(f"type={args['type']}")
        resp = await client.query_records(QueryRecordsParams(
            table="sys_script_client",
            query="^".join(parts),
            limit=args.get("limit", 20),
            fields="sys_id,name,table,type,active,sys_updated_on",
        ))
        return {"count": resp.count, "client_scripts": resp.records}

    elif name == "get_client_script":
        if not args.get("sys_id"):
            raise ServiceNowError("sys_id is required", "INVALID_REQUEST")
        return await client.get_record("sys_script_client", args["sys_id"])

    elif name == "create_client_script":
        if not args.get("name") or not args.get("table") or not args.get("type") or not args.get("script"):
            raise ServiceNowError("name, table, type, and script are required", "INVALID_REQUEST")
        data = {
            "name": args["name"],
            "table": args["table"],
            "type": args["type"],
            "script": args["script"],
            "active": args.get("active", True),
            "global": args.get("global", False),
        }
        if args.get("field_name"):
            data["field_name"] = args["field_name"]
        result = await client.create_record("sys_script_client", data)
        return {**result, "summary": f"Created client script \"{args['name']}\" ({args['type']}) on table \"{args['table']}\""}

    elif name == "update_client_script":
        if not args.get("sys_id") or not args.get("fields"):
            raise ServiceNowError("sys_id and fields are required", "INVALID_REQUEST")
        result = await client.update_record("sys_script_client", args["sys_id"], args["fields"])
        return {**result, "summary": f"Updated client script {args['sys_id']}"}

    # ── UI Policies ───────────────────────────────────────────────────────────
    elif name == "list_ui_policies":
        parts = []
        if args.get("active") is not None:
            parts.append(f"active={args['active']}")
        if args.get("table"):
            parts.append(f"model_table={args['table']}")
        resp = await client.query_records(QueryRecordsParams(
            table="sys_ui_policy",
            query="^".join(parts),
            limit=args.get("limit", 25),
            fields="sys_id,short_description,model_table,active,conditions,sys_updated_on",
        ))
        return {"count": resp.count, "ui_policies": resp.records}

    elif name == "get_ui_policy":
        if not args.get("sys_id"):
            raise ServiceNowError("sys_id is required", "INVALID_REQUEST")
        return await client.get_record("sys_ui_policy", args["sys_id"])

    elif name == "create_ui_policy":
        if not args.get("short_description") or not args.get("table"):
            raise ServiceNowError("short_description and table are required", "INVALID_REQUEST")
        data = {
            "short_description": args["short_description"],
            "model_table": args["table"],
            "active": args.get("active", True),
            "run_scripts": args.get("run_scripts", False),
        }
        if args.get("conditions"):
            data["conditions"] = args["conditions"]
        if args.get("script"):
            data["script"] = args["script"]
        result = await client.create_record("sys_ui_policy", data)
        return {**result, "summary": f"Created UI policy \"{args['short_description']}\" on table \"{args['table']}\""}

    # ── UI Actions ────────────────────────────────────────────────────────────
    elif name == "list_ui_actions":
        parts = []
        if args.get("active") is not None:
            parts.append(f"active={args['active']}")
        if args.get("table"):
            parts.append(f"table={args['table']}")
        if args.get("type"):
            parts.append(f"action_type={args['type']}")
        resp = await client.query_records(QueryRecordsParams(
            table="sys_ui_action",
            query="^".join(parts),
            limit=args.get("limit", 25),
            fields="sys_id,name,table,action_type,active,form_button,list_button,sys_updated_on",
        ))
        return {"count": resp.count, "ui_actions": resp.records}

    elif name == "get_ui_action":
        if not args.get("sys_id"):
            raise ServiceNowError("sys_id is required", "INVALID_REQUEST")
        return await client.get_record("sys_ui_action", args["sys_id"])

    elif name == "create_ui_action":
        if not args.get("name") or not args.get("table") or not args.get("action_name"):
            raise ServiceNowError("name, table, and action_name are required", "INVALID_REQUEST")
        data = {
            "name": args["name"],
            "table": args["table"],
            "action_name": args["action_name"],
            "active": args.get("active", True),
            "form_button": args.get("form_button", True),
            "list_button": args.get("list_button", False),
        }
        if args.get("script"):
            data["script"] = args["script"]
        if args.get("condition"):
            data["condition"] = args["condition"]
        if args.get("type"):
            data["action_type"] = args["type"]
        result = await client.create_record("sys_ui_action", data)
        return {**result, "summary": f"Created UI action \"{args['name']}\" on table \"{args['table']}\""}

    elif name == "update_ui_action":
        if not args.get("sys_id") or not args.get("fields"):
            raise ServiceNowError("sys_id and fields are required", "INVALID_REQUEST")
        result = await client.update_record("sys_ui_action", args["sys_id"], args["fields"])
        return {**result, "summary": f"Updated UI action {args['sys_id']}"}

    # ── ACL Management ────────────────────────────────────────────────────────
    elif name == "list_acls":
        parts = []
        if args.get("active") is not None:
            parts.append(f"active={args['active']}")
        if args.get("table"):
            parts.append(f"nameLIKE{args['table']}")
        if args.get("operation"):
            parts.append(f"operation={args['operation']}")
        resp = await client.query_records(QueryRecordsParams(
            table="sys_security_acl",
            query="^".join(parts),
            limit=args.get("limit", 25),
            fields="sys_id,name,type,operation,active,admin_overrides,sys_updated_on",
        ))
        return {"count": resp.count, "acls": resp.records}

    elif name == "get_acl":
        if not args.get("sys_id"):
            raise ServiceNowError("sys_id is required", "INVALID_REQUEST")
        return await client.get_record("sys_security_acl", args["sys_id"])

    elif name == "create_acl":
        if not args.get("name") or not args.get("operation"):
            raise ServiceNowError("name and operation are required", "INVALID_REQUEST")
        data = {
            "name": args["name"],
            "operation": args["operation"],
            "type": args.get("type", "record"),
            "active": args.get("active", True),
            "admin_overrides": args.get("admin_overrides", True),
        }
        if args.get("script"):
            data["script"] = args["script"]
        if args.get("description"):
            data["description"] = args["description"]
        result = await client.create_record("sys_security_acl", data)
        return {**result, "summary": f"Created ACL \"{args['name']}\" for operation \"{args['operation']}\""}

    elif name == "update_acl":
        if not args.get("sys_id") or not args.get("fields"):
            raise ServiceNowError("sys_id and fields are required", "INVALID_REQUEST")
        result = await client.update_record("sys_security_acl", args["sys_id"], args["fields"])
        return {**result, "summary": f"Updated ACL {args['sys_id']}"}

    return None
