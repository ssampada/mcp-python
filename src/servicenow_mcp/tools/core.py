"""Core generic CRUD tools — query, get, schema, search, CMDB."""
from __future__ import annotations
from typing import Any
from ..servicenow.client import ServiceNowClient
from ..servicenow.types import QueryRecordsParams

TOOL_DEFINITIONS = [
    {
        "name": "query_records",
        "description": "Query records from any ServiceNow table with filters, pagination, and sorting",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table name (e.g. incident, change_request)"},
                "query": {"type": "string", "description": "ServiceNow encoded query string"},
                "fields": {"type": "string", "description": "Comma-separated field names"},
                "limit": {"type": "number", "description": "Max records to return (default 10, max 1000)"},
                "offset": {"type": "number", "description": "Pagination offset"},
                "order_by": {"type": "string", "description": "Field to sort by (prefix with - for desc)"},
            },
            "required": ["table"],
        },
    },
    {
        "name": "get_record",
        "description": "Get a single record by table and sys_id",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "sys_id": {"type": "string"},
                "fields": {"type": "string"},
            },
            "required": ["table", "sys_id"],
        },
    },
    {
        "name": "get_table_schema",
        "description": "Get the schema/fields for a ServiceNow table",
        "inputSchema": {
            "type": "object",
            "properties": {"table": {"type": "string"}},
            "required": ["table"],
        },
    },
    {
        "name": "natural_language_search",
        "description": "Search incidents using a natural language query",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "number"},
            },
            "required": ["query"],
        },
    },
]


async def execute(client: ServiceNowClient, name: str, args: dict[str, Any]) -> Any | None:
    if name == "query_records":
        params = QueryRecordsParams(
            table=args["table"],
            query=args.get("query"),
            fields=args.get("fields"),
            limit=args.get("limit", 10),
            offset=args.get("offset"),
            order_by=args.get("order_by"),
        )
        resp = await client.query_records(params)
        return {"count": resp.count, "records": resp.records}

    elif name == "get_record":
        return await client.get_record(args["table"], args["sys_id"], args.get("fields"))

    elif name == "get_table_schema":
        params = QueryRecordsParams(table=args["table"], limit=1)
        resp = await client.query_records(params)
        if resp.records:
            return {"table": args["table"], "columns": list(resp.records[0].keys())}
        return {"table": args["table"], "columns": []}

    elif name == "natural_language_search":
        q = args["query"]
        search_query = f"short_descriptionLIKE{q}^ORdescriptionLIKE{q}"
        params = QueryRecordsParams(table="incident", query=search_query, limit=args.get("limit", 10))
        resp = await client.query_records(params)
        return {"count": resp.count, "records": resp.records}

    return None
