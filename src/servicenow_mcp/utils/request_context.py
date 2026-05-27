from contextvars import ContextVar

# Holds the bearer token extracted from the incoming MCP HTTP request.
# Set by BearerPassthroughMiddleware; read by ServiceNowClient._auth_headers().
# Falls back to "" when running over stdio (no HTTP layer).
request_bearer_token: ContextVar[str] = ContextVar("request_bearer_token", default="")
