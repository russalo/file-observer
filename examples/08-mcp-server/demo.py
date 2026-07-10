#!/usr/bin/env python3
"""Example 08 — call the MCP server's tools directly (no MCP client needed) to see the shapes.

The MCP tools are plain read-only Python functions over File Observer's existing manifest/summary/schema.
This prints what an agent would get from `scan_summary` on the examples tree. Requires `file-observer[mcp]`.
"""
import json
from pathlib import Path

from file_observer.mcp_server import scan_summary

if __name__ == "__main__":
    target = str(Path(__file__).resolve().parent.parent)  # the examples/ tree
    print(f"scan_summary({target}):\n")
    print(scan_summary(target))
