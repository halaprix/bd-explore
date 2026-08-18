import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

src_dir = str(Path(__file__).resolve().parents[1] / "src")
while src_dir in sys.path:
    sys.path.remove(src_dir)
sys.path.insert(0, src_dir)

from bd_explore.constants import VERSION
from bd_explore.index import build_index
from bd_explore.mcp import McpServer, run_mcp_server


class TestMcpServer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.beads_dir = self.root / ".beads"
        self.beads_dir.mkdir(parents=True)
        self.store_file = self.beads_dir / "issues.jsonl"
        self.db_path = self.root / "cache.db"

        self.sample_issues = [
            {
                "id": "epic-1",
                "title": "Auth Architecture",
                "status": "in_progress",
                "issue_type": "epic",
                "priority": 1,
                "created_at": "2026-08-01",
                "updated_at": "2026-08-01",
                "description": "Auth overhaul with JWT",
                "dependencies": [],
            },
            {
                "id": "task-1",
                "title": "Auth redesign",
                "status": "open",
                "issue_type": "task",
                "priority": 1,
                "created_at": "2026-08-02",
                "updated_at": "2026-08-02",
                "description": "Switch from session cookies to JWT auth tokens",
                "dependencies": [
                    {"issue_id": "task-1", "depends_on_id": "epic-1", "type": "parent-child"}
                ],
            },
            {
                "id": "task-2",
                "title": "Token Refresh",
                "status": "open",
                "issue_type": "task",
                "priority": 2,
                "created_at": "2026-08-03",
                "updated_at": "2026-08-03",
                "description": "Token refresh endpoint",
                "dependencies": [
                    {"issue_id": "task-2", "depends_on_id": "task-1", "type": "blocks"}
                ],
            },
        ]
        with open(self.store_file, "w", encoding="utf-8") as f:
            for issue in self.sample_issues:
                f.write(json.dumps(issue) + "\n")

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_rpc(self, server: McpServer, request: dict) -> dict | None:
        req_bytes = json.dumps(request).encode("utf-8")
        in_stream = io.BytesIO(req_bytes + b"\n")
        out_stream = io.BytesIO()

        server.handle_stream(in_stream, out_stream)
        out_stream.seek(0)
        lines = [line.strip() for line in out_stream.readlines() if line.strip()]
        if not lines:
            return None
        return json.loads(lines[0])

    def test_initialize(self):
        server = McpServer(default_store=self.store_file)
        init_resp = self.run_rpc(
            server,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            },
        )
        self.assertEqual(init_resp["id"], 1)
        self.assertEqual(init_resp["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(init_resp["result"]["serverInfo"]["name"], "bd-explore")
        self.assertEqual(init_resp["result"]["serverInfo"]["version"], VERSION)
        self.assertIn("tools", init_resp["result"]["capabilities"])
        self.assertIn("instructions", init_resp["result"])

    def test_initialize_protocol_version_echo(self):
        server = McpServer(default_store=self.store_file)
        # Echo supported version
        resp_known = self.run_rpc(
            server,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-10-07"}},
        )
        self.assertEqual(resp_known["result"]["protocolVersion"], "2024-10-07")

        # Fallback for unknown version
        resp_unknown = self.run_rpc(
            server,
            {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "9999-99-99"}},
        )
        self.assertEqual(resp_unknown["result"]["protocolVersion"], "2024-11-05")

    def test_notifications_initialized(self):
        server = McpServer(default_store=self.store_file)
        resp = self.run_rpc(
            server,
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )
        self.assertIsNone(resp)

    def test_ping(self):
        server = McpServer(default_store=self.store_file)
        ping_resp = self.run_rpc(server, {"jsonrpc": "2.0", "id": 2, "method": "ping"})
        self.assertEqual(ping_resp["id"], 2)
        self.assertEqual(ping_resp["result"], {})

    def test_tools_list(self):
        server = McpServer(default_store=self.store_file)
        resp = self.run_rpc(server, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        tools = resp["result"]["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "bd_explore")
        props = tools[0]["inputSchema"]["properties"]
        self.assertIn("query", props)
        self.assertIn("blast", props)
        self.assertIn("limit", props)
        self.assertIn("budget", props)
        self.assertIn("store", props)

    def test_tools_call_search(self):
        server = McpServer(default_store=self.store_file)
        resp = self.run_rpc(
            server,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "bd_explore",
                    "arguments": {"query": "JWT cookies", "store": str(self.store_file)},
                },
            },
        )
        self.assertEqual(resp["id"], 4)
        content = resp["result"]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertIn("task-1 [OPEN · P1 · task", content[0]["text"])
        self.assertIn("Switch from session cookies", content[0]["text"])

    def test_tools_call_blast(self):
        server = McpServer(default_store=self.store_file)
        resp = self.run_rpc(
            server,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "bd_explore",
                    "arguments": {"blast": "task-1", "store": str(self.store_file)},
                },
            },
        )
        self.assertEqual(resp["id"], 5)
        content = resp["result"]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertIn("task-1 [OPEN · P1 · task", content[0]["text"])
        self.assertIn("beads this blocks (transitively): 1", content[0]["text"])
        self.assertIn("task-2", content[0]["text"])
        self.assertIn("epic ancestry: 1", content[0]["text"])
        self.assertIn("epic-1", content[0]["text"])

    def test_tools_call_unknown_tool(self):
        server = McpServer(default_store=self.store_file)
        resp = self.run_rpc(
            server,
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "nonexistent_tool",
                    "arguments": {},
                },
            },
        )
        self.assertEqual(resp["id"], 6)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32601)
        self.assertIn("Unknown tool", resp["error"]["message"])

    def test_unknown_method(self):
        server = McpServer(default_store=self.store_file)
        resp = self.run_rpc(
            server,
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "some/unknown/method",
            },
        )
        self.assertEqual(resp["id"], 7)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32601)

    def test_malformed_json(self):
        server = McpServer(default_store=self.store_file)
        in_stream = io.BytesIO(b"this is not valid json\n")
        out_stream = io.BytesIO()
        server.handle_stream(in_stream, out_stream)
        out_stream.seek(0)
        line = out_stream.readline()
        resp = json.loads(line)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32700)
        self.assertEqual(resp["error"]["message"], "Parse error")

    def test_store_error_in_explore(self):
        server = McpServer()
        resp = self.run_rpc(
            server,
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {
                    "name": "bd_explore",
                    "arguments": {"store": "/path/to/nonexistent/store"},
                },
            },
        )
        self.assertEqual(resp["id"], 8)
        content = resp["result"]["content"]
        self.assertIn("store export not found", content[0]["text"])
        self.assertTrue(resp["result"].get("isError"))

    def test_blast_error_in_explore(self):
        server = McpServer(default_store=self.store_file)
        resp = self.run_rpc(
            server,
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "bd_explore",
                    "arguments": {"blast": "nonexistent-id", "store": str(self.store_file)},
                },
            },
        )
        self.assertEqual(resp["id"], 9)
        content = resp["result"]["content"]
        self.assertIn("no bead matching 'nonexistent-id'", content[0]["text"])
        self.assertTrue(resp["result"].get("isError"))

    def test_run_mcp_server(self):
        req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode("utf-8") + b"\n"
        fake_stdin = io.BytesIO(req)
        fake_stdout = io.BytesIO()

        mock_in = unittest.mock.MagicMock()
        mock_in.buffer = fake_stdin
        mock_out = unittest.mock.MagicMock()
        mock_out.buffer = fake_stdout

        with patch("sys.stdin", mock_in), patch("sys.stdout", mock_out):
            run_mcp_server(default_store=self.store_file)

        fake_stdout.seek(0)
        resp = json.loads(fake_stdout.readline())
        self.assertEqual(resp["id"], 1)
        self.assertEqual(resp["result"], {})

    def test_content_length_framing(self):
        server = McpServer(default_store=self.store_file)
        payload = json.dumps({"jsonrpc": "2.0", "id": 10, "method": "ping"}).encode("utf-8")
        msg = f"Content-Length: {len(payload)}\r\n\r\n".encode("utf-8") + payload
        in_stream = io.BytesIO(msg)
        out_stream = io.BytesIO()

        server.handle_stream(in_stream, out_stream)
        out_stream.seek(0)
        hdr = out_stream.readline().decode("utf-8")
        self.assertTrue(hdr.startswith("Content-Length:"))
        blank = out_stream.readline()
        self.assertEqual(blank, b"\r\n")
        body = json.loads(out_stream.readline().decode("utf-8"))
        self.assertEqual(body["id"], 10)
        self.assertEqual(body["result"], {})


if __name__ == "__main__":
    unittest.main()
