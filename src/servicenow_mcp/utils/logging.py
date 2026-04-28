import logging
import sys

# MCP uses stdio for transport, so all logging must go to stderr
handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

logger = logging.getLogger("servicenow-mcp")
logger.addHandler(handler)
logger.setLevel(logging.INFO)
