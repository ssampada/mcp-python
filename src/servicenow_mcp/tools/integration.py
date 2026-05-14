"""Integration tools — REST Messages, Transform Maps, Import Sets, and Event Registry.
Read tools: Tier 0. Write tools: Tier 1 (WRITE_ENABLED=true).
"""
from __future__ import annotations
import re
from typing import Any

from ..servicenow.client import ServiceNowClient
from ..servicenow.types import QueryRecordsParams
from ..utils.errors import ServiceNowError
from ..utils.permissions import require_write, require_scripting

TOOL_DEFINITIONS = [
    # ── Outbound REST Messages ────────────────────────────────────────────────
    {
        "name": "list_rest_messages",
        "description": "List outbound REST Message configurations (integrations with external APIs)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search by name or description"},
                "limit": {"type": "number", "description": "Max records to return (default 25)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_rest_message",
        "description": "Get full configuration of an outbound REST Message including its endpoints",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id_or_name": {"type": "string", "description": "REST Message sys_id or name"},
            },
            "required": ["sys_id_or_name"],
        },
    },
    {
        "name": "list_rest_message_functions",
        "description": "List HTTP methods (functions) defined within a REST Message",
        "inputSchema": {
            "type": "object",
            "properties": {
                "rest_message_sys_id": {"type": "string", "description": "Parent REST Message sys_id"},
                "limit": {"type": "number", "description": "Max records to return (default 25)"},
            },
            "required": ["rest_message_sys_id"],
        },
    },
    {
        "name": "create_rest_message",
        "description": "Create a new outbound REST Message definition (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique REST Message name"},
                "endpoint": {"type": "string", "description": 'Base URL endpoint (e.g. "https://api.example.com/v1")'},
                "description": {"type": "string", "description": "Purpose/description of this integration"},
                "use_mutual_auth": {"type": "boolean", "description": "Whether to use mutual TLS authentication"},
                "authentication_type": {"type": "string", "description": 'Auth type: "no_authentication", "basic", "oauth2"'},
            },
            "required": ["name", "endpoint"],
        },
    },
    # ── Transform Maps ────────────────────────────────────────────────────────
    {
        "name": "list_transform_maps",
        "description": "List Transform Maps used for importing data into ServiceNow tables",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search by name or target table"},
                "target_table": {"type": "string", "description": 'Filter by target table name (e.g. "incident")'},
                "limit": {"type": "number", "description": "Max records to return (default 25)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_transform_map",
        "description": "Get details of a Transform Map including its field mappings",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id_or_name": {"type": "string", "description": "Transform Map sys_id or name"},
            },
            "required": ["sys_id_or_name"],
        },
    },
    {
        "name": "run_transform_map",
        "description": "Execute a Transform Map on an Import Set to load data (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "transform_map_sys_id": {"type": "string", "description": "sys_id of the Transform Map to run"},
                "import_set_sys_id": {"type": "string", "description": "sys_id of the Import Set containing source data"},
            },
            "required": ["transform_map_sys_id", "import_set_sys_id"],
        },
    },
    {
        "name": "list_transform_field_maps",
        "description": "List field-level mappings within a Transform Map",
        "inputSchema": {
            "type": "object",
            "properties": {
                "transform_map_sys_id": {"type": "string", "description": "Parent Transform Map sys_id"},
                "limit": {"type": "number", "description": "Max records to return (default 50)"},
            },
            "required": ["transform_map_sys_id"],
        },
    },
    # ── Import Sets ───────────────────────────────────────────────────────────
    {
        "name": "list_import_sets",
        "description": "List Import Sets with optional filter by state or staging table",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "Filter by state: loaded, partial, transform_failed, complete"},
                "query": {"type": "string", "description": "Additional encoded query string"},
                "limit": {"type": "number", "description": "Max records to return (default 25)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_import_set",
        "description": "Get details of a specific Import Set including row count and transform status",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sys_id": {"type": "string", "description": "Import Set sys_id"},
            },
            "required": ["sys_id"],
        },
    },
    {
        "name": "create_import_set_row",
        "description": "Insert a row into an Import Set staging table for later transformation (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "staging_table": {"type": "string", "description": 'Staging table name (e.g. "u_import_incident"). Must already exist.'},
                "data": {"type": "object", "description": "Key-value pairs for the staging table row"},
            },
            "required": ["staging_table", "data"],
        },
    },
    {
        "name": "list_data_sources",
        "description": "List Import Set data source definitions (file/JDBC/REST loaders)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search by name"},
                "type": {"type": "string", "description": "Filter by type: file, jdbc, ldap, rest"},
                "limit": {"type": "number", "description": "Max records to return (default 25)"},
            },
            "required": [],
        },
    },
    # ── Event Registry & Management ───────────────────────────────────────────
    {
        "name": "list_event_registry",
        "description": "List registered event definitions in the ServiceNow event registry",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search events by name or description"},
                "limit": {"type": "number", "description": "Max records to return (default 50)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_event_registry_entry",
        "description": "Get details of a specific registered event definition",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name_or_sysid": {"type": "string", "description": 'Event name (e.g. "incident.created") or sys_id'},
            },
            "required": ["name_or_sysid"],
        },
    },
    {
        "name": "register_event",
        "description": "Register a new custom event in the event registry (requires SCRIPTING_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": 'Unique event name (e.g. "my_app.record_created")'},
                "description": {"type": "string", "description": "Description of when this event fires"},
                "table": {"type": "string", "description": 'Table that fires this event (e.g. "incident")'},
            },
            "required": ["name", "table"],
        },
    },
    {
        "name": "fire_event",
        "description": "Fire a custom ServiceNow event for a specific record (requires WRITE_ENABLED=true)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_name": {"type": "string", "description": "Event name to fire (must be registered)"},
                "table": {"type": "string", "description": "Table name of the target record"},
                "record_sys_id": {"type": "string", "description": "sys_id of the record to fire the event on"},
                "parm1": {"type": "string", "description": "Optional first parameter passed to event handlers"},
                "parm2": {"type": "string", "description": "Optional second parameter passed to event handlers"},
            },
            "required": ["event_name", "table", "record_sys_id"],
        },
    },
    {
        "name": "list_event_log",
        "description": "List recent event log entries (fired events and their processing status)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_name": {"type": "string", "description": "Filter by event name"},
                "state": {"type": "string", "description": "Filter by state: ready, processing, processed, error, transferred"},
                "limit": {"type": "number", "description": "Max records to return (default 50)"},
            },
            "required": [],
        },
    },
    # ── OAuth & Credentials ───────────────────────────────────────────────────
    {
        "name": "list_oauth_applications",
        "description": "List OAuth application registry entries (client applications that can authenticate)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search by name or client ID"},
                "limit": {"type": "number", "description": "Max records to return (default 25)"},
            },
            "required": [],
        },
    },
    {
        "name": "list_credential_aliases",
        "description": "List connection and credential aliases used by integrations",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search by name"},
                "type": {"type": "string", "description": "Filter by type: basic, oauth2, api_key, certificate"},
                "limit": {"type": "number", "description": "Max records to return (default 25)"},
            },
            "required": [],
        },
    },
]


async def execute(client: ServiceNowClient, name: str, args: dict[str, Any]) -> Any | None:
    # ── Outbound REST Messages ────────────────────────────────────────────────
    if name == "list_rest_messages":
        parts: list[str] = []
        if args.get("query"):
            parts.append(f"nameCONTAINS{args['query']}^ORdescriptionCONTAINS{args['query']}")
        return await client.query_records(QueryRecordsParams(
            table="sys_rest_message",
            query="^".join(parts),
            limit=args.get("limit", 25),
            fields="sys_id,name,endpoint,description,authentication_type,sys_updated_on",
        ))

    elif name == "get_rest_message":
        ident = args.get("sys_id_or_name")
        if not ident:
            raise ServiceNowError("sys_id_or_name is required", "INVALID_REQUEST")
        if re.match(r"^[0-9a-fA-F]{32}$", ident):
            return await client.get_record("sys_rest_message", ident)
        resp = await client.query_records(QueryRecordsParams(
            table="sys_rest_message", query=f"name={ident}", limit=1
        ))
        if resp.count == 0:
            raise ServiceNowError(f"REST Message not found: {ident}", "NOT_FOUND")
        return resp.records[0]

    elif name == "list_rest_message_functions":
        if not args.get("rest_message_sys_id"):
            raise ServiceNowError("rest_message_sys_id is required", "INVALID_REQUEST")
        return await client.query_records(QueryRecordsParams(
            table="sys_rest_message_fn",
            query=f"rest_message={args['rest_message_sys_id']}",
            limit=args.get("limit", 25),
            fields="sys_id,name,http_method,relative_path,rest_message,sys_updated_on",
        ))

    elif name == "create_rest_message":
        require_write()
        if not args.get("name") or not args.get("endpoint"):
            raise ServiceNowError("name and endpoint are required", "INVALID_REQUEST")
        data: dict[str, Any] = {
            "name": args["name"],
            "endpoint": args["endpoint"],
            "description": args.get("description", ""),
            "authentication_type": args.get("authentication_type", "no_authentication"),
        }
        if args.get("use_mutual_auth") is not None:
            data["use_mutual_auth"] = args["use_mutual_auth"]
        result = await client.create_record("sys_rest_message", data)
        return {**result, "summary": f"Created REST Message \"{args['name']}\""}

    # ── Transform Maps ────────────────────────────────────────────────────────
    elif name == "list_transform_maps":
        parts = []
        if args.get("target_table"):
            parts.append(f"target_table={args['target_table']}")
        if args.get("query"):
            parts.append(f"nameCONTAINS{args['query']}^ORtarget_tableCONTAINS{args['query']}")
        return await client.query_records(QueryRecordsParams(
            table="sys_transform_map",
            query="^".join(parts),
            limit=args.get("limit", 25),
            fields="sys_id,name,target_table,source_table,active,sys_updated_on",
        ))

    elif name == "get_transform_map":
        ident = args.get("sys_id_or_name")
        if not ident:
            raise ServiceNowError("sys_id_or_name is required", "INVALID_REQUEST")
        if re.match(r"^[0-9a-fA-F]{32}$", ident):
            return await client.get_record("sys_transform_map", ident)
        resp = await client.query_records(QueryRecordsParams(
            table="sys_transform_map", query=f"name={ident}", limit=1
        ))
        if resp.count == 0:
            raise ServiceNowError(f"Transform Map not found: {ident}", "NOT_FOUND")
        return resp.records[0]

    elif name == "run_transform_map":
        require_write()
        if not args.get("transform_map_sys_id") or not args.get("import_set_sys_id"):
            raise ServiceNowError("transform_map_sys_id and import_set_sys_id are required", "INVALID_REQUEST")
        result = await client.create_record("sys_import_set_run", {
            "import_set": args["import_set_sys_id"],
            "transform_map": args["transform_map_sys_id"],
        })
        return {**result, "summary": f"Triggered Transform Map {args['transform_map_sys_id']} on Import Set {args['import_set_sys_id']}"}

    elif name == "list_transform_field_maps":
        if not args.get("transform_map_sys_id"):
            raise ServiceNowError("transform_map_sys_id is required", "INVALID_REQUEST")
        return await client.query_records(QueryRecordsParams(
            table="sys_transform_entry",
            query=f"map={args['transform_map_sys_id']}",
            limit=args.get("limit", 50),
            fields="sys_id,map,source_field,target_field,coalesce,use_source_script,sys_updated_on",
        ))

    # ── Import Sets ───────────────────────────────────────────────────────────
    elif name == "list_import_sets":
        parts = []
        if args.get("state"):
            parts.append(f"state={args['state']}")
        if args.get("query"):
            parts.append(args["query"])
        return await client.query_records(QueryRecordsParams(
            table="sys_import_set",
            query="^".join(parts),
            limit=args.get("limit", 25),
            fields="sys_id,label,state,table_name,import_count,error_count,sys_created_on",
        ))

    elif name == "get_import_set":
        if not args.get("sys_id"):
            raise ServiceNowError("sys_id is required", "INVALID_REQUEST")
        return await client.get_record("sys_import_set", args["sys_id"])

    elif name == "create_import_set_row":
        require_write()
        if not args.get("staging_table") or not args.get("data"):
            raise ServiceNowError("staging_table and data are required", "INVALID_REQUEST")
        result = await client.create_record(args["staging_table"], args["data"])
        return {**result, "summary": f"Inserted row into staging table \"{args['staging_table']}\""}

    elif name == "list_data_sources":
        parts = []
        if args.get("type"):
            parts.append(f"type={args['type']}")
        if args.get("query"):
            parts.append(f"nameCONTAINS{args['query']}")
        return await client.query_records(QueryRecordsParams(
            table="sys_data_source",
            query="^".join(parts),
            limit=args.get("limit", 25),
            fields="sys_id,name,type,format,import_set_table_name,sys_updated_on",
        ))

    # ── Event Registry ────────────────────────────────────────────────────────
    elif name == "list_event_registry":
        parts = []
        if args.get("query"):
            parts.append(f"nameCONTAINS{args['query']}^ORdescriptionCONTAINS{args['query']}")
        return await client.query_records(QueryRecordsParams(
            table="sysevent_register",
            query="^".join(parts),
            limit=args.get("limit", 50),
            fields="sys_id,name,table,description,sys_updated_on",
        ))

    elif name == "get_event_registry_entry":
        ident = args.get("name_or_sysid")
        if not ident:
            raise ServiceNowError("name_or_sysid is required", "INVALID_REQUEST")
        if re.match(r"^[0-9a-fA-F]{32}$", ident):
            return await client.get_record("sysevent_register", ident)
        resp = await client.query_records(QueryRecordsParams(
            table="sysevent_register", query=f"name={ident}", limit=1
        ))
        if resp.count == 0:
            raise ServiceNowError(f"Event registry entry not found: {ident}", "NOT_FOUND")
        return resp.records[0]

    elif name == "register_event":
        require_scripting()
        if not args.get("name") or not args.get("table"):
            raise ServiceNowError("name and table are required", "INVALID_REQUEST")
        result = await client.create_record("sysevent_register", {
            "name": args["name"],
            "table": args["table"],
            "description": args.get("description", ""),
        })
        return {**result, "summary": f"Registered event \"{args['name']}\" for table \"{args['table']}\""}

    elif name == "fire_event":
        require_write()
        if not args.get("event_name") or not args.get("table") or not args.get("record_sys_id"):
            raise ServiceNowError("event_name, table, and record_sys_id are required", "INVALID_REQUEST")
        data = {
            "name": args["event_name"],
            "table": args["table"],
            "instance": args["record_sys_id"],
        }
        if args.get("parm1"):
            data["parm1"] = args["parm1"]
        if args.get("parm2"):
            data["parm2"] = args["parm2"]
        result = await client.create_record("sysevent", data)
        return {**result, "summary": f"Fired event \"{args['event_name']}\" on {args['table']}:{args['record_sys_id']}"}

    elif name == "list_event_log":
        parts = []
        if args.get("event_name"):
            parts.append(f"nameCONTAINS{args['event_name']}")
        if args.get("state"):
            parts.append(f"state={args['state']}")
        return await client.query_records(QueryRecordsParams(
            table="sysevent",
            query="^".join(parts),
            limit=args.get("limit", 50),
            fields="sys_id,name,table,instance,state,parm1,parm2,sys_created_on",
        ))

    # ── OAuth & Credentials ───────────────────────────────────────────────────
    elif name == "list_oauth_applications":
        parts = []
        if args.get("query"):
            parts.append(f"nameCONTAINS{args['query']}^ORclient_idCONTAINS{args['query']}")
        return await client.query_records(QueryRecordsParams(
            table="oauth_entity",
            query="^".join(parts),
            limit=args.get("limit", 25),
            fields="sys_id,name,client_id,type,active,sys_updated_on",
        ))

    elif name == "list_credential_aliases":
        parts = []
        if args.get("type"):
            parts.append(f"type={args['type']}")
        if args.get("query"):
            parts.append(f"nameCONTAINS{args['query']}")
        return await client.query_records(QueryRecordsParams(
            table="sys_alias",
            query="^".join(parts),
            limit=args.get("limit", 25),
            fields="sys_id,name,type,description,sys_updated_on",
        ))

    return None
