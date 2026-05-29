import json
import logging
import os
import sys
from datetime import datetime, timezone

# MCP uses stdio for transport, so all logging must go to stderr
handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

logger = logging.getLogger("servicenow-mcp")
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ── Audit logger ───────────────────────────────────────────────────
_audit_logger = logging.getLogger("servicenow-mcp.audit")
_audit_logger.setLevel(logging.INFO)
_audit_logger.propagate = False

_audit_log_path = os.getenv("MCP_AUDIT_LOG", os.path.join(os.getcwd(), "audit.log"))
_audit_handler = logging.FileHandler(_audit_log_path)
_audit_handler.setFormatter(logging.Formatter("%(message)s"))
_audit_logger.addHandler(_audit_handler)


def audit_log(tool: str, arguments: dict, status: str, error: str | None = None) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "arguments": arguments,
        "status": status,
    }
    if error:
        entry["error"] = error
    _audit_logger.info(json.dumps(entry, default=str))
