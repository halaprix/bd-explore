"""Built-in stdio JSON-RPC 2.0 MCP (Model Context Protocol) server."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, BinaryIO

from bd_explore.constants import DEFAULT_BUDGET_CHARS, DEFAULT_SEEDS, VERSION
from bd_explore.explorer import ExploreError, blast, explore
from bd_explore.index import find_store

__all__ = [
    "TOOL_SCHEMA",
    "SERVER_INSTRUCTIONS",
    "McpServer",
    "run_mcp_server",
]

TOOL_SCHEMA = {
    "name": "bd_explore",
    "description": (
        "Ask a beads store questions: one call returns the most relevant beads "
        "verbatim (title, description, notes, comments, close reason) plus each hit's "
        "relationship neighborhood (blocks, blocked-by, epic ancestry, mention edges) "
        "under an output budget. Derived from .beads/issues.jsonl."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Free text query with optional filters (e.g. 'why did we repoint SYRP status:open type:bug priority:1 epic:auth')",
            },
            "blast": {
                "type": "string",
                "description": "Bead ID (or suffix) to compute transitive dependency closure (blocks, blocked-by, and epic ancestry)",
            },
            "limit": {
                "type": "integer",
                "description": f"Max number of seeds/results to return (default: {DEFAULT_SEEDS})",
            },
            "budget": {
                "type": "integer",
                "description": f"Character budget cap for LLM context window (default: {DEFAULT_BUDGET_CHARS})",
            },
            "store": {
                "type": "string",
                "description": "Optional path to repo or .beads directory (defaults to auto-discovering from cwd)",
            },
        },
    },
}

SERVER_INSTRUCTIONS = (
    "In repositories with a beads store (a `.beads/` directory exists at the repo root), "
    "call `bd_explore` to ask questions about beads, tasks, epics, bug fixes, architecture "
    "decisions, and handoff notes."
)


class McpServer:
    def __init__(self, default_store: Path | str | None = None) -> None:
        self.default_store = Path(default_store) if default_store else None

    def handle_request(self, req: dict) -> dict | None:
        method = req.get("method")
        msg_id = req.get("id")
        params = req.get("params") or {}

        if method == "initialize":
            req_version = str(params.get("protocolVersion") or "")
            supported = {"2024-11-05", "2024-10-07", "0.1.0"}
            proto_version = req_version if req_version in supported else "2024-11-05"
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": proto_version,
                    "serverInfo": {"name": "bd-explore", "version": VERSION},
                    "capabilities": {"tools": {}},
                    "instructions": SERVER_INSTRUCTIONS,
                },
            }

        if method == "notifications/initialized":
            return None

        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": [TOOL_SCHEMA]},
            }

        if method == "tools/call":
            tool_name = params.get("name")
            if tool_name != "bd_explore":
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                }
            args = params.get("arguments") or {}
            result_text, is_error = self._execute_explore(args)
            result_payload: dict[str, Any] = {
                "content": [{"type": "text", "text": result_text}],
            }
            if is_error:
                result_payload["isError"] = True
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": result_payload,
            }

        if msg_id is not None:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        return None

    def _execute_explore(self, args: dict) -> tuple[str, bool]:
        store = args.get("store") or self.default_store
        try:
            blast_id = args.get("blast")
            if blast_id:
                return blast(blast_id, store=store, budget=args.get("budget")), False
            return (
                explore(
                    args.get("query") or "",
                    store=store,
                    limit=args.get("limit"),
                    budget=args.get("budget"),
                ),
                False,
            )
        except ExploreError as e:
            return str(e), True
        except Exception as e:
            return f"bd-explore error: {e}", True

    def handle_stream(self, in_stream: BinaryIO, out_stream: BinaryIO) -> None:
        """Process messages from in_stream supporting both Content-Length headers and NDJSON."""
        try:
            while True:
                line = in_stream.readline()
                if not line:
                    break
                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue

                content_bytes = b""
                is_content_length = False
                if line_str.lower().startswith("content-length:"):
                    is_content_length = True
                    try:
                        length = int(line_str.split(":", 1)[1].strip())
                    except ValueError:
                        length = 0
                    # Read headers until empty line
                    while True:
                        hdr = in_stream.readline()
                        if not hdr or hdr in (b"\r\n", b"\n", b""):
                            break
                    if length > 0:
                        content_bytes = in_stream.read(length)
                else:
                    content_bytes = line.strip()

                if not content_bytes:
                    continue

                try:
                    req = json.loads(content_bytes.decode("utf-8", errors="replace"))
                    if not isinstance(req, dict):
                        err_resp = {
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {"code": -32600, "message": "Invalid Request: JSON payload must be an object"},
                        }
                        self._write_response(out_stream, err_resp, is_content_length)
                        continue
                    resp = self.handle_request(req)
                    if resp is not None:
                        self._write_response(out_stream, resp, is_content_length)
                except json.JSONDecodeError:
                    err_resp = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    }
                    self._write_response(out_stream, err_resp, is_content_length)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _write_response(self, out_stream: BinaryIO, payload: dict, use_content_length: bool) -> None:
        body = json.dumps(payload) + "\n"
        body_bytes = body.encode("utf-8")
        if use_content_length:
            header = f"Content-Length: {len(body_bytes)}\r\n\r\n".encode("utf-8")
            out_stream.write(header + body_bytes)
        else:
            out_stream.write(body_bytes)
        out_stream.flush()


def run_mcp_server(default_store: Path | str | None = None) -> None:
    store_path = find_store(str(default_store)) if default_store else None
    server = McpServer(default_store=store_path)
    server.handle_stream(sys.stdin.buffer, sys.stdout.buffer)
