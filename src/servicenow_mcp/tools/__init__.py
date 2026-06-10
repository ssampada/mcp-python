"""Tool router — aggregates all domain modules and applies role-based packaging."""
from __future__ import annotations
import os
from typing import Any

from servicenow_mcp.tools import catalog, change, knowledge, problem, task, user


from ..servicenow.client import ServiceNowClient
from ..utils.cache import ToolResponseCache, is_cacheable
from ..utils.errors import ServiceNowError
from ..utils.logging import logger
from ..utils.request_context import request_bearer_token

from . import core, incident, flow, integration, script, update_set

# Each module exposes TOOL_DEFINITIONS and execute()
_MODULES = [core, incident, catalog, change, knowledge, problem, task, user, flow, integration, script, update_set]

# Role-based packages (same as TypeScript version)
PACKAGE_TOOL_NAMES: dict[str, list[str]] = {
    "service_desk": [
        "query_records", "get_record", "get_table_schema", "natural_language_search",
        "create_incident", "get_incident", "update_incident", "resolve_incident", "close_incident",
    ],
    "change_coordinator": [
        "query_records", "get_record", "get_table_schema", "natural_language_search",
        "create_problem", "get_problem", "update_problem", "resolve_problem",
    ],
    "catalog_manager": [
        "query_records", "get_record", "get_table_schema", "natural_language_search",
        "list_catalog_items", "search_catalog", "get_catalog_item",
        "create_catalog_item", "update_catalog_item", "order_catalog_item",
        "create_catalog_variable", "create_catalog_ui_policy",
        "create_approval_rule", "get_my_approvals", "list_approvals",
        "approve_request", "reject_request",
        "get_sla_details", "list_active_slas",
    ],
    "knowledge_manager": [
        "query_records", "get_record", "get_table_schema", "natural_language_search",
        "list_knowledge_bases", "search_knowledge", "get_knowledge_article",
        "create_knowledge_article", "update_knowledge_article",
        "publish_knowledge_article", "retire_knowledge_article",
    ],
    "user_admin": [
        "query_records", "get_record", "get_table_schema", "natural_language_search",
        "list_users", "create_user", "update_user",
        "list_groups", "create_group", "update_group",
        "add_user_to_group", "remove_user_from_group",
    ],
    "flow_designer": [
        "query_records", "get_record", "get_table_schema", "natural_language_search",
        "list_flows", "get_flow", "trigger_flow",
        "get_flow_execution", "list_flow_executions", "get_flow_error_log",
        "list_subflows", "get_subflow",
        "list_action_instances",
        "get_process_automation", "list_process_automations",
        "create_flow", "create_subflow", "create_flow_action",
        "publish_flow", "test_flow",
    ],
    "integration": [
        "query_records", "get_record", "get_table_schema", "natural_language_search",
        "list_rest_messages", "get_rest_message", "list_rest_message_functions", "create_rest_message",
        "list_transform_maps", "get_transform_map", "run_transform_map", "list_transform_field_maps",
        "list_import_sets", "get_import_set", "create_import_set_row", "list_data_sources",
        "list_event_registry", "get_event_registry_entry", "register_event", "fire_event", "list_event_log",
        "list_oauth_applications", "list_credential_aliases",
    ],
    "scripting": [
        "query_records", "get_record", "get_table_schema", "natural_language_search",
        "list_business_rules", "get_business_rule", "create_business_rule", "update_business_rule",
        "list_script_includes", "get_script_include", "create_script_include", "update_script_include",
        "list_client_scripts", "get_client_script", "create_client_script", "update_client_script",
        "list_update_sets", "get_update_set", "create_update_set", "update_update_set",
        "list_update_set_changes", "get_current_update_set", "set_current_update_set",
        "complete_update_set", "reopen_update_set", "ignore_update_set",
        "move_change_to_update_set",
        "list_remote_update_sets", "preview_remote_update_set", "commit_remote_update_set",
        "list_ui_policies", "get_ui_policy", "create_ui_policy",
        "list_ui_actions", "get_ui_action", "create_ui_action", "update_ui_action",
        "list_acls", "get_acl", "create_acl", "update_acl",
    ],
}


def get_tools() -> list[dict]:
    all_tools = []
    for mod in _MODULES:
        all_tools.extend(mod.TOOL_DEFINITIONS)

    package_name = os.getenv("MCP_TOOL_PACKAGE", "full").lower()
    if package_name == "full":
        return all_tools

    allowed = PACKAGE_TOOL_NAMES.get(package_name)
    if not allowed:
        return all_tools

    allowed_set = set(allowed)
    return [t for t in all_tools if t["name"] in allowed_set]


async def execute_tool(
    client: ServiceNowClient,
    name: str,
    args: dict[str, Any],
    cache: ToolResponseCache | None = None,
) -> Any:
    user_token = request_bearer_token.get()
    cache_active = cache is not None and cache.enabled and is_cacheable(name)

    if cache_active:
        hit = await cache.get(name, args, user_token)
        if hit is not None:
            logger.info(f"Cache HIT: {name}")
            return hit

    for mod in _MODULES:
        result = await mod.execute(client, name, args)
        if result is not None:
            if cache_active:
                await cache.set(name, args, user_token, result)
            return result
    raise ServiceNowError(f"Unknown tool: {name}", "UNKNOWN_TOOL")
