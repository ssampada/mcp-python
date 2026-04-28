"""Knowledge Base tools. Read: Tier 0. Write: Tier 1."""
from __future__ import annotations
from typing import Any
import re
from ..servicenow.client import ServiceNowClient
from ..servicenow.types import QueryRecordsParams
from ..utils.errors import ServiceNowError
from ..utils.permissions import require_write

TOOL_DEFINITIONS = [
    {"name": "list_knowledge_bases", "description": "List all knowledge bases",
     "inputSchema": {"type": "object", "properties": {"limit": {"type": "number"}}, "required": []}},
    {"name": "search_knowledge", "description": "Search knowledge articles by keyword",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "limit": {"type": "number"}, "knowledge_base": {"type": "string"}},
         "required": ["query"]}},
    {"name": "get_knowledge_article", "description": "Get article by number (KB...) or sys_id",
     "inputSchema": {"type": "object", "properties": {"number_or_sysid": {"type": "string"}}, "required": ["number_or_sysid"]}},
    {"name": "create_knowledge_article", "description": "Create a knowledge article (requires WRITE_ENABLED=true)",
     "inputSchema": {"type": "object", "properties": {
         "short_description": {"type": "string"}, "text": {"type": "string"},
         "knowledge_base_sys_id": {"type": "string"}, "category": {"type": "string"}},
         "required": ["short_description", "text", "knowledge_base_sys_id"]}},
    {"name": "update_knowledge_article", "description": "Update a knowledge article (requires WRITE_ENABLED=true)",
     "inputSchema": {"type": "object", "properties": {"sys_id": {"type": "string"}, "fields": {"type": "object"}}, "required": ["sys_id", "fields"]}},
    {"name": "publish_knowledge_article", "description": "Publish a draft article (requires WRITE_ENABLED=true)",
     "inputSchema": {"type": "object", "properties": {"sys_id": {"type": "string"}}, "required": ["sys_id"]}},
    {"name": "retire_knowledge_article", "description": "[Write] Retire a knowledge article",
     "inputSchema": {"type": "object", "properties": {"article_id": {"type": "string"}}, "required": ["article_id"]}},
]

async def execute(client: ServiceNowClient, name: str, args: dict[str, Any]) -> Any | None:
    if name == "list_knowledge_bases":
        resp = await client.query_records(QueryRecordsParams(table="kb_knowledge_base", query="active=true", limit=args.get("limit", 20), fields="sys_id,title,description,owner,workflow_state"))
        return {"count": resp.count, "knowledge_bases": resp.records}
    elif name == "search_knowledge":
        query = f"short_descriptionLIKE{args['query']}^ORtextLIKE{args['query']}^workflow_state=published"
        if args.get("knowledge_base"): query += f"^kb_knowledge_base.title={args['knowledge_base']}^ORkb_knowledge_base={args['knowledge_base']}"
        resp = await client.query_records(QueryRecordsParams(table="kb_knowledge", query=query, limit=args.get("limit", 10)))
        return {"count": resp.count, "articles": resp.records}
    elif name == "get_knowledge_article":
        ident = args["number_or_sysid"]
        if re.match(r"^[0-9a-fA-F]{32}$", ident): return await client.get_record("kb_knowledge", ident)
        resp = await client.query_records(QueryRecordsParams(table="kb_knowledge", query=f"number={ident}^ORsys_id={ident}", limit=1))
        if resp.count == 0: raise ServiceNowError(f"Article not found: {ident}", "NOT_FOUND")
        return resp.records[0]
    elif name == "create_knowledge_article":
        require_write()
        result = await client.create_record("kb_knowledge", {"short_description": args["short_description"], "text": args["text"], "kb_knowledge_base": args["knowledge_base_sys_id"], "category": args.get("category"), "workflow_state": "draft"})
        return {**result, "summary": f"Created article {result.get('number', result.get('sys_id'))}"}
    elif name == "update_knowledge_article":
        require_write()
        return await client.update_record("kb_knowledge", args["sys_id"], args["fields"])
    elif name == "publish_knowledge_article":
        require_write()
        return await client.update_record("kb_knowledge", args["sys_id"], {"workflow_state": "published"})
    elif name == "retire_knowledge_article":
        require_write()
        ident = args["article_id"]
        sys_id = ident
        if not re.match(r"^[0-9a-fA-F]{32}$", ident):
            resp = await client.query_records(QueryRecordsParams(table="kb_knowledge", query=f"number={ident}", limit=1))
            if resp.count == 0: raise ServiceNowError(f"Article not found: {ident}", "NOT_FOUND")
            sys_id = resp.records[0]["sys_id"]
        return await client.update_record("kb_knowledge", sys_id, {"workflow_state": "retired"})
    return None
