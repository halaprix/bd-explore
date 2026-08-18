"""Built-in stdio JSON-RPC 2.0 MCP (Model Context Protocol) server."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, BinaryIO

from bd_explore.constants import DEFAULT_BUDGET_CHARS, DEFAULT_SEEDS, VERSION
from bd_explore.index import find_store, open_index
from bd_explore.search import blast_data, format_blast, format_output, parse_query, search

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


def _safe_int(val: Any, default: int) -> int:
    """Defensive integer conversion helper for query limits and budgets."""
    try:
        parsed = int(val)
        return parsed if parsed > 0 else default
    except (ValueError, TypeError):
        return default


class McpServer:
    def __init__(self, default_store: Path | str | None = None) -> None:
        self.default_store = Path(default_store) if default_store else None

    def handle_request(self, req: dict) -> dict | None:
        method = req.get("method")
        msg_id = req.get("id")
        params = req.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
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
        store_arg = args.get("store")
        con = None
        try:
            store_path = find_store(store_arg) if store_arg else (self.default_store or find_store())
            con = open_index(store_path)

            blast_id = args.get("blast")
            if blast_id:
                try:
                    data = blast_data(con, blast_id)
                    return format_blast(con, data), False
                except Exception as e:
                    return f"bd-explore blast error: {e}", True

            query_str = args.get("query") or ""
            limit = _safe_int(args.get("limit"), DEFAULT_SEEDS)
            budget = _safe_int(args.get("budget"), DEFAULT_BUDGET_CHARS)

            text, filters = parse_query(query_str)
            rows = search(con, text, filters, limit)
            return format_output(con, rows, budget), False
        except Exception as e:
            return f"bd-explore error: {e}", True
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    def handle_stream(self, in_stream: BinaryIO, out_stream: BinaryIO) -> None:
        try:
            for line in in_stream:
                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue
                try:
                    req = json.loads(line_str)
                    if not isinstance(req, dict):
                        err_resp = {
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {"code": -32600, "message": "Invalid Request: JSON payload must be an object"},
                        }
                        out_stream.write((json.dumps(err_resp) + "\n").encode("utf-8"))
                        out_stream.flush()
                        continue
                    resp = self.handle_request(req)
                    if resp is not None:
                        out_bytes = (json.dumps(resp) + "\n").encode("utf-8")
                        out_stream.write(out_bytes)
                        out_stream.flush()
                except json.JSONDecodeError:
                    err_resp = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    }
                    out_stream.write((json.dumps(err_resp) + "\n").encode("utf-8"))
                    out_stream.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def run_mcp_server(default_store: Path | str | None = None) -> None:
    store_path = Path(default_store) if default_store else None
    server = McpServer(default_store=store_path)
    server.handle_stream(sys.stdin.buffer, sys.stdout.buffer)
