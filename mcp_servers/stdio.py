#!/usr/bin/env python3
"""Minimal MCP (Model Context Protocol) stdio server for PaperAssist.

The plugin entrypoint. It speaks JSON-RPC 2.0 over stdin/stdout so an MCP
client such as OpenClaude or Claude Code can list and call PaperAssist tools.

Tools from the ``paperassist`` pack server and the ``writing`` server are
merged under one namespace, because the harness should see a single toolset.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_servers.runner import load_server  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "paperassist"
SERVER_VERSION = "4.0.0"


class ToolRouter:
    def __init__(self) -> None:
        self.servers = [load_server("paperassist"), load_server("writing")]

    def _find(self, tool_name: str):
        for server in self.servers:
            if any(spec.name == tool_name for spec in server.tools()):
                return server
        return None

    def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for server in self.servers:
            for spec in server.tools():
                tools.append(
                    {
                        "name": spec.name,
                        "description": spec.description,
                        "inputSchema": {"type": "object", "additionalProperties": True},
                    }
                )
        return tools

    def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        server = self._find(tool_name)
        if server is None:
            raise ValueError(f"unknown tool: {tool_name}")
        return server.call_tool(tool_name, **arguments)

    def resources(self) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        for server in self.servers:
            for spec in server.resources():
                resources.append(
                    {
                        "uri": spec.uri,
                        "name": spec.uri,
                        "description": spec.description,
                        "mimeType": "application/json",
                    }
                )
        return resources


def _respond(request_id: Any, result: Any) -> None:
    sys.stdout.write(
        json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}) + "\n"
    )
    sys.stdout.flush()


def _error(request_id: Any, code: int, message: str) -> None:
    sys.stdout.write(
        json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
        )
        + "\n"
    )
    sys.stdout.flush()


def main() -> int:
    router = ToolRouter()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            _error(None, -32700, "parse error")
            continue
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}
        try:
            if method == "initialize":
                _respond(
                    request_id,
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {}, "resources": {}},
                        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    },
                )
            elif method in {"notifications/initialized", "initialized"}:
                continue
            elif method == "ping":
                _respond(request_id, {})
            elif method == "tools/list":
                _respond(request_id, {"tools": router.list_tools()})
            elif method == "tools/call":
                name = str(params.get("name") or "")
                arguments = params.get("arguments") or {}
                if not isinstance(arguments, dict):
                    raise ValueError("tool arguments must be an object")
                result = router.call(name, arguments)
                _respond(
                    request_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, ensure_ascii=False, indent=2, default=str),
                            }
                        ],
                        "isError": False,
                    },
                )
            elif method == "resources/list":
                _respond(request_id, {"resources": router.resources()})
            elif method == "resources/read":
                uri = str(params.get("uri") or "")
                raise ValueError(f"resource reads require tool-specific payloads: {uri}")
            else:
                _error(request_id, -32601, f"method not found: {method}")
        except Exception as exc:  # noqa: BLE001 - protocol boundary must not crash
            _error(request_id, -32000, f"{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
