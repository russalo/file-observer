#!/usr/bin/env bash
# Example 08 — call the MCP server's read-only tools directly (no MCP client needed).
# Requires the MCP extra:  pip install "file-observer[mcp]"
set -euo pipefail
cd "$(dirname "$0")"
exec python3 demo.py
