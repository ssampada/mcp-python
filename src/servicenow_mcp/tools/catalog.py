"""Service Catalog, Approval, and SLA tools. Read: Tier 0. Write: Tier 1."""
from __future__ import annotations
import os, re
from typing import Any
from ..servicenow.client import ServiceNowClient
from ..servicenow.types import QueryRecordsParams
from ..utils.errors import ServiceNowError
from ..utils.permissions import require_write

TOOL_DEFINITIONS = [
    {"name": "list_catalog_items", "description": "List available service catalog items",
     "inputSchema": {"type": "object", "properties": {"category": {"type": "string"}, "limit": {"type": "number"}}, "required": []}},
    {"name": "search_catalog", "description": "Search catalog items by keyword",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "number"}}, "required": ["query"]}},
    {"name": "get_catalog_item", "description": "Get catalog item details",
     "inputSchema": {"type": "object", "properties": {"sys_id_or_name": {"type": "string"}}, "required": ["sys_id_or_name"]}},
    {"name": "create_catalog_item", "description": "[Write] Create a catalog item",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "short_description": {"type": "string"}, "description": {"type": "string"}, "category": {"type": "string"}, "price": {"type": "string"}, "active": {"type": "boolean"}}, "required": ["name", "short_description"]}},
    {"name": "update_catalog_item", "description": "[Write] Update a catalog item",
     "inputSchema": {"type": "object", "properties": {"sys_id": {"type": "string"}, "fields": {"type": "object"}}, "required": ["sys_id", "fields"]}},
    {"name": "order_catalog_item", "description": "[Write] Order a catalog item",
     "inputSchema": {"type": "object", "properties": {"sys_id": {"type": "string"}, "quantity": {"type": "number"}, "variables": {"type": "object"}}, "required": ["sys_id"]}},
    {"name": "create_approval_rule", "description": "[Write] Create an approval rule",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "table": {"type": "string"}, "approver_type": {"type": "string"}, "approver": {"type": "string"}, "condition": {"type": "string"}, "active": {"type": "boolean"}, "order": {"type": "number"}}, "required": ["name", "table", "approver_type", "approver"]}},
    {"name": "get_my_approvals", "description": "List approvals pending for configured user",
     "inputSchema": {"type": "object", "properties": {"state": {"type": "string"}}, "required": []}},
    {"name": "list_approvals", "description": "List approval requests",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "state": {"type": "string"}, "limit": {"type": "number"}}, "required": []}},
    {"name": "approve_request", "description": "[Write] Approve a pending approval",
     "inputSchema": {"type": "object", "properties": {"sys_id": {"type": "string"}, "comments": {"type": "string"}}, "required": ["sys_id"]}},
    {"name": "reject_request", "description": "[Write] Reject a pending approval",
     "inputSchema": {"type": "object", "properties": {"sys_id": {"type": "string"}, "comments": {"type": "string"}}, "required": ["sys_id", "comments"]}},
    {"name": "get_sla_details", "description": "Get SLA breach status for a task",
     "inputSchema": {"type": "object", "properties": {"task_sys_id": {"type": "string"}}, "required": ["task_sys_id"]}},
    {"name": "list_active_slas", "description": "List active SLA records",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "number"}}, "required": []}},
    {"name": "create_catalog_variable", "description": "[Write] Add a variable to a catalog item",
     "inputSchema": {"type": "object", "properties": {"cat_item_id": {"type": "string"}, "name": {"type": "string"}, "question_text": {"type": "string"}, "type": {"type": "string"}, "order": {"type": "number"}, "mandatory": {"type": "boolean"}}, "required": ["cat_item_id", "name", "question_text", "type"]}},
    {"name": "create_catalog_ui_policy", "description": "[Write] Create a UI policy for a catalog item",
     "inputSchema": {"type": "object", "properties": {"cat_item_id": {"type": "string"}, "short_description": {"type": "string"}, "conditions": {"type": "string"}, "reverse_if_false": {"type": "boolean"}}, "required": ["cat_item_id", "short_description"]}},
]

async def execute(client: ServiceNowClient, name: str, args: dict[str, Any]) -> Any | None:
    if name == "list_catalog_items":
        query = "active=true"
        if args.get("category"): query += f"^category.title={args['category']}^ORcategory={args['category']}"
        resp = await client.query_records(QueryRecordsParams(table="sc_cat_item", query=query, limit=args.get("limit", 20), fields="sys_id,name,short_description,category,price"))
        return {"count": resp.count, "catalog_items": resp.records}
    elif name == "search_catalog":
        resp = await client.query_records(QueryRecordsParams(table="sc_cat_item", query=f"nameLIKE{args['query']}^ORshort_descriptionLIKE{args['query']}^active=true", limit=args.get("limit", 10)))
        return {"count": resp.count, "catalog_items": resp.records}
    elif name == "get_catalog_item":
        ident = args["sys_id_or_name"]
        if re.match(r"^[0-9a-fA-F]{32}$", ident): return await client.get_record("sc_cat_item", ident)
        resp = await client.query_records(QueryRecordsParams(table="sc_cat_item", query=f"name={ident}^ORsys_id={ident}", limit=1))
        if resp.count == 0: raise ServiceNowError(f"Catalog item not found: {ident}", "NOT_FOUND")
        return resp.records[0]
    elif name == "create_catalog_item":
        require_write()
        data = {"name": args["name"], "short_description": args["short_description"], "active": args.get("active", True)}
        for k in ("description", "category", "price"): 
            if args.get(k): data[k] = args[k]
        return await client.create_record("sc_cat_item", data)
    elif name == "update_catalog_item":
        require_write()
        return await client.update_record("sc_cat_item", args["sys_id"], args["fields"])
    elif name == "order_catalog_item":
        require_write()
        # ServiceNow Catalog API endpoint
        from ..servicenow.client import ServiceNowClient as _
        url = f"{client.base_url}/api/sn_sc/servicecatalog/items/{args['sys_id']}/order_now"
        return await client._request("POST", url, json={"sysparm_quantity": args.get("quantity", 1), "variables": args.get("variables", {})})
    elif name == "create_approval_rule":
        require_write()
        data: dict = {"name": args["name"], "table": args["table"], "approver_type": args["approver_type"], "active": args.get("active", True), "order": args.get("order", 100)}
        data["approver_group" if args["approver_type"] == "group" else "approver"] = args["approver"]
        if args.get("condition"): data["condition"] = args["condition"]
        return await client.create_record("sysapproval_rule", data)
    elif name == "get_my_approvals":
        username = os.getenv("SERVICENOW_BASIC_USERNAME", "")
        state = args.get("state", "requested")
        query = f"state={state}"
        if username: query += f"^approver.user_name={username}"
        resp = await client.query_records(QueryRecordsParams(table="sysapproval_approver", query=query, limit=20))
        return {"count": resp.count, "approvals": resp.records}
    elif name == "list_approvals":
        query = args.get("query", "")
        if args.get("state"): query = f"{query}^state={args['state']}" if query else f"state={args['state']}"
        resp = await client.query_records(QueryRecordsParams(table="sysapproval_approver", query=query or None, limit=args.get("limit", 10)))
        return {"count": resp.count, "approvals": resp.records}
    elif name == "approve_request":
        require_write()
        data: dict = {"state": "approved"}
        if args.get("comments"): data["comments"] = args["comments"]
        return await client.update_record("sysapproval_approver", args["sys_id"], data)
    elif name == "reject_request":
        require_write()
        return await client.update_record("sysapproval_approver", args["sys_id"], {"state": "rejected", "comments": args["comments"]})
    elif name == "get_sla_details":
        resp = await client.query_records(QueryRecordsParams(table="task_sla", query=f"task={args['task_sys_id']}", limit=20))
        return {"count": resp.count, "slas": resp.records}
    elif name == "list_active_slas":
        query = "stage!=complete^has_breached=false"
        if args.get("query"): query = f"{args['query']}^{query}"
        resp = await client.query_records(QueryRecordsParams(table="task_sla", query=query, limit=args.get("limit", 10)))
        return {"count": resp.count, "slas": resp.records}
    elif name == "create_catalog_variable":
        require_write()
        type_map = {"string": "6", "reference": "8", "select_box": "1", "checkbox": "7", "date": "10", "date_time": "15", "integer": "2", "multi_line_text": "2", "email": "32"}
        return await client.create_record("item_option_new", {"cat_item": args["cat_item_id"], "name": args["name"], "question_text": args["question_text"], "type": type_map.get(args["type"], args["type"]), "order": args.get("order", 100), "mandatory": "true" if args.get("mandatory") else "false"})
    elif name == "create_catalog_ui_policy":
        require_write()
        return await client.create_record("catalog_ui_policy", {"catalog_item": args["cat_item_id"], "short_description": args["short_description"], "applies_to": "catalog_item", "catalog_conditions": args.get("conditions", ""), "reverse_if_false": "true" if args.get("reverse_if_false") else "false", "active": "true"})
    return None
