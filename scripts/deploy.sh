#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Deploy ServiceNow MCP Server on a Linux VM (no Docker).
# ============================================================
#
# Prerequisites:
#   - Linux VM (Ubuntu 22.04+ / RHEL 8+ / Amazon Linux 2023)
#   - Python 3.11+
#   - Root or sudo access
#
# Usage:
#   # 1. Copy project to the VM
#   scp -r . user@your-server:/tmp/servicenow-mcp
#
#   # 2. SSH in and run this script
#   ssh user@your-server
#   sudo bash /tmp/servicenow-mcp/scripts/deploy.sh

INSTALL_DIR="/opt/servicenow-mcp"
SERVICE_USER="mcp"
PYTHON="python3"

echo ""
echo "============================================"
echo "  ServiceNow MCP Server — VM Deployment"
echo "============================================"
echo ""

# ── 1. Check Python ────────────────────────────────────────────────

echo "==> [1/6] Checking Python version..."
if ! command -v "$PYTHON" &>/dev/null; then
    echo "ERROR: $PYTHON not found."
    echo "Install it:"
    echo "  Ubuntu/Debian: sudo apt install python3.11 python3.11-venv"
    echo "  RHEL/Amazon:   sudo dnf install python3.11"
    exit 1
fi

PY_VERSION=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo "ERROR: Python 3.11+ required (found $PY_VERSION)."
    exit 1
fi
echo "    Python $PY_VERSION OK"

# ── 2. Create service user ─────────────────────────────────────────

echo "==> [2/6] Creating service user '$SERVICE_USER'..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
    echo "    Created user '$SERVICE_USER'"
else
    echo "    User '$SERVICE_USER' already exists"
fi

# ── 3. Install application ─────────────────────────────────────────

echo "==> [3/6] Installing to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

$PYTHON -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip --quiet
"$INSTALL_DIR/venv/bin/pip" install "$PROJECT_DIR" --quiet
echo "    Installed servicenow-mcp and dependencies"

# ── 4. Set up .env ─────────────────────────────────────────────────

echo "==> [4/6] Setting up .env..."
if [ ! -f "$INSTALL_DIR/.env" ]; then
    cp "$SCRIPT_DIR/env.single-user.example" "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    echo "    Created $INSTALL_DIR/.env (edit this next!)"
else
    echo "    $INSTALL_DIR/.env already exists, skipping"
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# ── 5. Install systemd service ─────────────────────────────────────

echo "==> [5/6] Installing systemd service..."
cp "$SCRIPT_DIR/servicenow-mcp.service" /etc/systemd/system/servicenow-mcp.service
systemctl daemon-reload
systemctl enable servicenow-mcp
echo "    Service enabled (will auto-start on boot)"

# ── 6. Open firewall port ──────────────────────────────────────────

echo "==> [6/6] Firewall..."
if command -v ufw &>/dev/null; then
    ufw allow 8000/tcp 2>/dev/null && echo "    Opened port 8000 (ufw)" || echo "    ufw: port 8000 may already be open"
elif command -v firewall-cmd &>/dev/null; then
    firewall-cmd --permanent --add-port=8000/tcp 2>/dev/null && firewall-cmd --reload && echo "    Opened port 8000 (firewalld)" || echo "    firewalld: port 8000 may already be open"
else
    echo "    No firewall detected — make sure port 8000 is accessible"
fi

# ── Done ───────────────────────────────────────────────────────────

echo ""
echo "============================================"
echo "  Deployment complete!"
echo "============================================"
echo ""
echo "NEXT STEPS:"
echo ""
echo "  1. Edit the config:"
echo "     sudo nano $INSTALL_DIR/.env"
echo ""
echo "     For dev/testing (bearer token):"
echo "       SERVICENOW_AUTH_METHOD=bearer"
echo "       SERVICENOW_BEARER_TOKEN=your-token"
echo ""
echo "     For production (OAuth + SAML SSO):"
echo "       SERVICENOW_AUTH_METHOD=passthrough"
echo "       SERVICENOW_OAUTH_CLIENT_ID=from-servicenow"
echo "       SERVICENOW_OAUTH_CLIENT_SECRET=from-servicenow"
echo ""
echo "  2. Start the server:"
echo "     sudo systemctl start servicenow-mcp"
echo ""
echo "  3. Verify it's running:"
echo "     curl -s http://localhost:8000/mcp | head"
echo "     sudo systemctl status servicenow-mcp"
echo "     sudo journalctl -u servicenow-mcp -f"
echo ""
echo "  4. GitHub Copilot config (.vscode/mcp.json):"
echo '     {'
echo '       "servers": {'
echo '         "servicenow": {'
echo '           "type": "http",'
echo '           "url": "http://<THIS-SERVER-IP>:8000/mcp"'
echo '         }'
echo '       }'
echo '     }'
echo ""
echo "  5. (Recommended) Set up HTTPS with nginx:"
echo "     See scripts/nginx.conf for a ready-to-use config"
echo ""
