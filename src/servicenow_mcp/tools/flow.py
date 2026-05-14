"""Flow Designer tools — list, inspect, trigger, and monitor flows and subflows.
Read tools: Tier 0. Trigger/create tools: Tier 1 (WRITE_ENABLED=true).
"""
from __future__ import annotations
import re
from datetime import datetime, timezone, timedelta
from typing import Any

from ..servicenow.client import ServiceNowClient
from ..servicenow.types import QueryRecordsParams
from ..utils.errors import ServiceNowError
from ..utils.permissions import require_write, require_scripting

TOOL_DEFINITIONS = [
    {
        "name": "list_flows",
        "description": "List Flow Designer flows with optional filter by name, category, or active status",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search flows by name or description"},
                "active": {"type": "boolean", "description": "Filter to active flows only (default true)"},
                "category": {"type": "string", "description": 'Filter by category (e.g., "ITSM", "HR", "Security")'},
                "limit": {"type": "number", "description": "Max records to return (default 50)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_flow",
        "description": "Get full details of a Flow Designer flow including its actions and trigger",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name_or_sysid": {"type": "string", "description": "Flow name or sys_id"},
            },
            "required": ["name_or_sysid"],
        },
    },
    {
        "name": "trigger_flow",
        "description": "Trigger a Flow Designer flow with optional input parameters (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "flow_sys_id": {"type": "string", "description": "sys_id of the flow to trigger"},
                "inputs": {"type": "object", "description": "Key-value pairs for flow input variables"},
            },
            "required": ["flow_sys_id"],
        },
    },
    {
        "name": "get_flow_execution",
        "description": "Get the status and details of a specific flow execution",
        "inputSchema": {
            "type": "object",
            "properties": {
                "execution_sysid": {"type": "string", "description": "sys_id of the flow execution to inspect"},
            },
            "required": ["execution_sysid"],
        },
    },
    {
        "name": "list_flow_executions",
        "description": "List recent executions of a flow with status (completed, error, running)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "flow_sys_id": {"type": "string", "description": "sys_id of the parent flow"},
                "status": {"type": "string", "description": "Filter by status: running, complete, error, cancelled"},
                "limit": {"type": "number", "description": "Max records to return (default 25)"},
            },
            "required": ["flow_sys_id"],
        },
    },
    {
        "name": "list_subflows",
        "description": "List available subflows that can be reused across flows",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search subflows by name"},
                "active": {"type": "boolean", "description": "Filter to active subflows only (default true)"},
                "limit": {"type": "number", "description": "Max records to return (default 50)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_subflow",
        "description": "Get full details of a subflow including its inputs, outputs, and actions",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name_or_sysid": {"type": "string", "description": "Subflow name or sys_id"},
            },
            "required": ["name_or_sysid"],
        },
    },
    {
        "name": "list_action_instances",
        "description": "List reusable Flow Designer action instances available in the environment",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search actions by name or category"},
                "category": {"type": "string", "description": 'Filter by action category (e.g., "ServiceNow Core", "Integrations")'},
                "limit": {"type": "number", "description": "Max records to return (default 50)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_process_automation",
        "description": "Get details of a Process Automation Designer playbook or process",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name_or_sysid": {"type": "string", "description": "Playbook or process name or sys_id"},
            },
            "required": ["name_or_sysid"],
        },
    },
    {
        "name": "list_process_automations",
        "description": "List Process Automation Designer playbooks and processes",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search by name or description"},
                "active": {"type": "boolean", "description": "Filter to active processes only (default true)"},
                "limit": {"type": "number", "description": "Max records to return (default 50)"},
            },
            "required": [],
        },
    },
    {
        "name": "create_flow",
        "description": "Create a new Flow Designer flow. **[Write]**",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Flow name"},
                "description": {"type": "string", "description": "Flow description"},
                "trigger_type": {"type": "string", "description": "Trigger type: record, schedule, inbound_email, rest (default record)"},
                "trigger_table": {"type": "string", "description": "Trigger table (for record triggers)"},
                "scope": {"type": "string", "description": "Application scope"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "create_subflow",
        "description": "Create a new reusable subflow. **[Write]**",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Subflow name"},
                "description": {"type": "string", "description": "Subflow description"},
                "inputs": {"type": "array", "items": {"type": "object"}, "description": "Input variable definitions [{name, type, mandatory}]"},
                "scope": {"type": "string", "description": "Application scope"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "create_flow_action",
        "description": "Create a custom Flow Designer action. **[Scripting]**",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Action name"},
                "description": {"type": "string", "description": "Action description"},
                "inputs": {"type": "array", "items": {"type": "object"}, "description": "Input definitions [{name, type, mandatory}]"},
                "outputs": {"type": "array", "items": {"type": "object"}, "description": "Output definitions [{name, type}]"},
                "script": {"type": "string", "description": "Action script body"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "publish_flow",
        "description": "Publish (activate) a draft flow or subflow. **[Write]**",
        "inputSchema": {
            "type": "object",
            "properties": {
                "flow_sys_id": {"type": "string", "description": "Flow or subflow sys_id to publish"},
                "type": {"type": "string", "description": "Type: flow or subflow (default flow)"},
            },
            "required": ["flow_sys_id"],
        },
    },
    {
        "name": "test_flow",
        "description": "Execute a flow in test mode with sample inputs. **[Write]**",
        "inputSchema": {
            "type": "object",
            "properties": {
                "flow_sys_id": {"type": "string", "description": "Flow sys_id to test"},
                "test_inputs": {"type": "object", "description": "Test input values"},
            },
            "required": ["flow_sys_id"],
        },
    },
    {
        "name": "get_flow_error_log",
        "description": "Get detailed error logs for failed flow executions",
        "inputSchema": {
            "type": "object",
            "properties": {
                "flow_sys_id": {"type": "string", "description": "Flow sys_id"},
                "days": {"type": "number", "description": "Look-back period in days (default 7)"},
                "limit": {"type": "number", "description": "Max records (default 25)"},
            },
            "required": ["flow_sys_id"],
        },
    },
]


async def execute(client: ServiceNowClient, name: str, args: dict[str, Any]) -> Any | None:
    if name == "list_flows":
        parts: list[str] = []
        if args.get("active", True):
            parts.append("active=true")
        if args.get("category"):
            parts.append(f"category={args['category']}")
        if args.get("query"):
            parts.append(f"nameCONTAINS{args['query']}^ORdescriptionCONTAINS{args['query']}")
        return await client.query_records(QueryRecordsParams(
            table="sys_hub_flow", query="^".join(parts), limit=args.get("limit", 50)
        ))

    elif name == "get_flow":
        ident = args.get("name_or_sysid")
        if not ident:
            raise ServiceNowError("name_or_sysid is required", "INVALID_REQUEST")
        if re.match(r"^[0-9a-fA-F]{32}$", ident):
            return await client.get_record("sys_hub_flow", ident)
        resp = await client.query_records(QueryRecordsParams(
            table="sys_hub_flow", query=f"nameCONTAINS{ident}", limit=1
        ))
        if resp.count == 0:
            raise ServiceNowError(f"Flow not found: {ident}", "NOT_FOUND")
        return resp.records[0]

    elif name == "trigger_flow":
        require_write()
        if not args.get("flow_sys_id"):
            raise ServiceNowError("flow_sys_id is required", "INVALID_REQUEST")
        payload = {"sys_id": args["flow_sys_id"], "inputs": args.get("inputs", {})}
        result = await client.create_record("sys_hub_flow_trigger", payload)
        return {**result, "summary": f"Triggered flow {args['flow_sys_id']}"}

    elif name == "get_flow_execution":
        if not args.get("execution_sysid"):
            raise ServiceNowError("execution_sysid is required", "INVALID_REQUEST")
        return await client.get_record("sys_flow_context", args["execution_sysid"])

    elif name == "list_flow_executions":
        if not args.get("flow_sys_id"):
            raise ServiceNowError("flow_sys_id is required", "INVALID_REQUEST")
        parts = [f"flow={args['flow_sys_id']}"]
        if args.get("status"):
            parts.append(f"status={args['status']}")
        return await client.query_records(QueryRecordsParams(
            table="sys_flow_context", query="^".join(parts), limit=args.get("limit", 25)
        ))

    elif name == "list_subflows":
        parts = []
        if args.get("active", True):
            parts.append("active=true")
        if args.get("query"):
            parts.append(f"nameCONTAINS{args['query']}")
        try:
            return await client.query_records(QueryRecordsParams(
                table="sys_hub_subflow", query="^".join(parts), limit=args.get("limit", 50)
            ))
        except ServiceNowError as e:
            if "INVALID_REQUEST" in e.code or "Invalid table" in str(e):
                return {"count": 0, "records": [],
                        "note": "sys_hub_subflow table not available — Flow Designer plugin may not be activated"}
            raise

    elif name == "get_subflow":
        ident = args.get("name_or_sysid")
        if not ident:
            raise ServiceNowError("name_or_sysid is required", "INVALID_REQUEST")
        if re.match(r"^[0-9a-fA-F]{32}$", ident):
            return await client.get_record("sys_hub_subflow", ident)
        resp = await client.query_records(QueryRecordsParams(
            table="sys_hub_subflow", query=f"nameCONTAINS{ident}", limit=1
        ))
        if resp.count == 0:
            raise ServiceNowError(f"Subflow not found: {ident}", "NOT_FOUND")
        return resp.records[0]

    elif name == "list_action_instances":
        parts = []
        if args.get("category"):
            parts.append(f"category={args['category']}")
        if args.get("query"):
            parts.append(f"nameCONTAINS{args['query']}")
        return await client.query_records(QueryRecordsParams(
            table="sys_hub_action_instance", query="^".join(parts), limit=args.get("limit", 50)
        ))

    elif name == "get_process_automation":
        ident = args.get("name_or_sysid")
        if not ident:
            raise ServiceNowError("name_or_sysid is required", "INVALID_REQUEST")
        if re.match(r"^[0-9a-fA-F]{32}$", ident):
            return await client.get_record("pa_process", ident)
        resp = await client.query_records(QueryRecordsParams(
            table="pa_process", query=f"nameCONTAINS{ident}", limit=1
        ))
        if resp.count == 0:
            raise ServiceNowError(f"Process automation not found: {ident}", "NOT_FOUND")
        return resp.records[0]

    elif name == "list_process_automations":
        parts = []
        if args.get("active", True):
            parts.append("active=true")
        if args.get("query"):
            parts.append(f"nameCONTAINS{args['query']}^ORdescriptionCONTAINS{args['query']}")
        try:
            return await client.query_records(QueryRecordsParams(
                table="pa_process", query="^".join(parts), limit=args.get("limit", 50)
            ))
        except ServiceNowError as e:
            if "INVALID_REQUEST" in e.code or "Invalid table" in str(e):
                return {"count": 0, "records": [],
                        "note": "pa_process table not available — Process Automation plugin may not be activated"}
            raise

    elif name == "create_flow":
        require_write()
        if not args.get("name"):
            raise ServiceNowError("name is required", "INVALID_REQUEST")
        data: dict[str, Any] = {"name": args["name"], "active": "false"}
        if args.get("description"):
            data["description"] = args["description"]
        if args.get("trigger_type"):
            data["trigger_type"] = args["trigger_type"]
        if args.get("trigger_table"):
            data["trigger_table"] = args["trigger_table"]
        if args.get("scope"):
            data["sys_scope"] = args["scope"]
        result = await client.create_record("sys_hub_flow", data)
        return {"action": "created", **result}

    elif name == "create_subflow":
        require_write()
        if not args.get("name"):
            raise ServiceNowError("name is required", "INVALID_REQUEST")
        data = {"name": args["name"], "active": "false"}
        if args.get("description"):
            data["description"] = args["description"]
        if args.get("scope"):
            data["sys_scope"] = args["scope"]
        result = await client.create_record("sys_hub_subflow", data)
        return {"action": "created", **result}

    elif name == "create_flow_action":
        require_scripting()
        if not args.get("name"):
            raise ServiceNowError("name is required", "INVALID_REQUEST")
        data = {"name": args["name"]}
        if args.get("description"):
            data["description"] = args["description"]
        if args.get("script"):
            data["script"] = args["script"]
        result = await client.create_record("sys_hub_action_type_definition", data)
        return {"action": "created", **result}

    elif name == "publish_flow":
        require_write()
        if not args.get("flow_sys_id"):
            raise ServiceNowError("flow_sys_id is required", "INVALID_REQUEST")
        table = "sys_hub_subflow" if args.get("type") == "subflow" else "sys_hub_flow"
        result = await client.update_record(table, args["flow_sys_id"], {"active": "true"})
        return {"action": "published", **result}

    elif name == "test_flow":
        require_write()
        if not args.get("flow_sys_id"):
            raise ServiceNowError("flow_sys_id is required", "INVALID_REQUEST")
        result = await client.create_record("sys_hub_flow_trigger", {
            "sys_id": args["flow_sys_id"],
            "inputs": args.get("test_inputs", {}),
            "test_mode": "true",
        })
        return {"action": "test_triggered", **result}

    elif name == "get_flow_error_log":
        if not args.get("flow_sys_id"):
            raise ServiceNowError("flow_sys_id is required", "INVALID_REQUEST")
        days = args.get("days", 7)
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        return await client.query_records(QueryRecordsParams(
            table="sys_flow_context",
            query=f"flow={args['flow_sys_id']}^status=error^sys_created_on>={since}",
            limit=args.get("limit", 25),
        ))

    return None
