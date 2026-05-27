import os
from .errors import ServiceNowError


def _is_passthrough() -> bool:
    return os.getenv("SERVICENOW_AUTH_METHOD", "").lower() == "passthrough"


def require_write() -> None:
    if _is_passthrough():
        return
    if os.getenv("WRITE_ENABLED", "false").lower() != "true":
        raise ServiceNowError(
            "Write operations are disabled. Set WRITE_ENABLED=true to enable.",
            "WRITE_NOT_ENABLED",
        )


def require_cmdb_write() -> None:
    require_write()
    if _is_passthrough():
        return
    if os.getenv("CMDB_WRITE_ENABLED", "false").lower() != "true":
        raise ServiceNowError(
            "CMDB write operations are disabled. Set CMDB_WRITE_ENABLED=true.",
            "CMDB_WRITE_NOT_ENABLED",
        )


def require_scripting() -> None:
    require_write()
    if _is_passthrough():
        return
    if os.getenv("SCRIPTING_ENABLED", "false").lower() != "true":
        raise ServiceNowError(
            "Scripting operations are disabled. Set SCRIPTING_ENABLED=true.",
            "SCRIPTING_NOT_ENABLED",
        )


def require_now_assist() -> None:
    if _is_passthrough():
        return
    if os.getenv("NOW_ASSIST_ENABLED", "false").lower() != "true":
        raise ServiceNowError(
            "Now Assist features are disabled. Set NOW_ASSIST_ENABLED=true.",
            "NOW_ASSIST_NOT_ENABLED",
        )
