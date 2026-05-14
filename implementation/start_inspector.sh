#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python)}"

mkdir -p "$SCRIPT_DIR/.npm-cache"
NPM_CONFIG_CACHE="$SCRIPT_DIR/.npm-cache" \
  npx -y @modelcontextprotocol/inspector "$PYTHON_BIN" "$SCRIPT_DIR/mcp_server.py"
