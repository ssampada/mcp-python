#!/usr/bin/env bash
set -euo pipefail

# Quick-start: run the MCP server locally for testing.
# Usage: ./scripts/start.sh
#
# Requires a .env file in the project root.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "ERROR: No .env file found. Copy .env.example or scripts/env.single-user.example to .env and fill in your credentials."
    exit 1
fi

cd "$PROJECT_DIR"

if [ ! -d ".venv" ]; then
    echo "==> Creating virtual environment..."
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -e .
fi

echo "==> Starting MCP server (streamable-http on :8000)..."
echo "    Endpoint: http://localhost:8000/mcp"
echo "    Auth mode: passthrough (each user provides their own bearer token)"
echo ""
echo "    Test with: curl -H 'Authorization: Bearer <your-token>' http://localhost:8000/mcp"
echo "    Press Ctrl+C to stop."
echo ""

exec .venv/bin/servicenow-mcp --transport streamable-http --host 0.0.0.0 --port 8000
