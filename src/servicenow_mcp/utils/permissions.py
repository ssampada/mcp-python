import os
from .errors import ServiceNowError


def require_write() -> None:
    if os.getenv("WRITE_ENABLED", "false").lower() != "true":
        raise ServiceNowError(
            "Write operations are disabled. Set WRITE_ENABLED=true to enable.",
            "WRITE_NOT_ENABLED",
        )


def require_cmdb_write() -> None:
    require_write()
    if os.getenv("CMDB_WRITE_ENABLED", "false").lower() != "true":
        raise ServiceNowError(
            "CMDB write operations are disabled. Set CMDB_WRITE_ENABLED=true.",
            "CMDB_WRITE_NOT_ENABLED",
        )


def require_scripting() -> None:
    require_write()
    if os.getenv("SCRIPTING_ENABLED", "false").lower() != "true":
        raise ServiceNowError(
            "Scripting operations are disabled. Set SCRIPTING_ENABLED=true.",
            "SCRIPTING_NOT_ENABLED",
        )


def require_now_assist() -> None:
    if os.getenv("NOW_ASSIST_ENABLED", "false").lower() != "true":
        raise ServiceNowError(
            "Now Assist features are disabled. Set NOW_ASSIST_ENABLED=true.",
            "NOW_ASSIST_NOT_ENABLED",
        )
