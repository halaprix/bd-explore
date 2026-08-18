import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

src_dir = str(Path(__file__).resolve().parents[1] / "src")
while src_dir in sys.path:
    sys.path.remove(src_dir)
sys.path.insert(0, src_dir)

from bd_explore.installer.instructions import (
    BD_EXPLORE_INSTRUCTIONS_BLOCK,
    BD_EXPLORE_SECTION_END,
    BD_EXPLORE_SECTION_START,
    remove_marked_section,
    replace_or_append_marked_section,
    upsert_instructions_entry,
)
from bd_explore.installer.memory import (
    MEMORY_BODY,
    MEMORY_KEY,
    get_memory_content,
    inject_beads_memory,
    is_bd_available,
    remove_beads_memory,
)
from bd_explore.installer.shared import (
    atomic_write_file,
    json_deep_equal,
    read_json_file,
    write_json_file,
)
from bd_explore.installer.targets import (
    TARGET_REGISTRY,
    detect_installed_targets,
    get_target,
    print_config,
    run_installer,
    run_uninstaller,
)
from bd_explore.installer.targets.agents_md import AgentsMdTarget
from bd_explore.installer.targets.antigravity import AntigravityTarget
from bd_explore.installer.targets.claude import ClaudeTarget
from bd_explore.installer.targets.codex import CodexTarget
from bd_explore.installer.targets.cursor import CursorTarget
from bd_explore.installer.targets.gemini import GeminiTarget
from bd_explore.mcp import McpServer


class TestInstallerShared(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_atomic_write_file(self):
        dest = self.root / "sub" / "dir" / "test.txt"
        atomic_write_file(dest, "hello world\n")
        self.assertTrue(dest.exists())
        self.assertEqual(dest.read_text(encoding="utf-8"), "hello world\n")

        # Overwrite existing
        atomic_write_file(dest, "new content\n")
        self.assertEqual(dest.read_text(encoding="utf-8"), "new content\n")

    def test_atomic_write_failure_cleans_tmp(self):
        dest = self.root / "file.txt"
        with patch("builtins.open", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                atomic_write_file(dest, "data")
        # Ensure no temp file leftover
        tmp_files = list(self.root.glob("file.txt.tmp.*"))
        self.assertEqual(len(tmp_files), 0)

    def test_read_and_write_json_file(self):
        f = self.root / "config.json"
        self.assertEqual(read_json_file(f), {})

        data = {"mcpServers": {"bd-explore": {"command": "bd-explore", "args": ["serve", "--mcp"]}}}
        write_json_file(f, data)
        self.assertTrue(f.exists())

        loaded = read_json_file(f)
        self.assertEqual(loaded, data)

    def test_read_json_file_corrupt_creates_backup(self):
        f = self.root / "corrupt.json"
        f.write_text("{ this is not valid json }", encoding="utf-8")

        with self.assertRaises(ValueError):
            read_json_file(f)

        backup = f.with_suffix(".backup")
        if not backup.exists():
            backup = f.with_name(f"{f.name}.backup")
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_text(encoding="utf-8"), "{ this is not valid json }")

    def test_json_deep_equal(self):
        a = {"x": 1, "y": [1, 2, {"k": "v"}]}
        b = {"y": [1, 2, {"k": "v"}], "x": 1}
        self.assertTrue(json_deep_equal(a, b))

        c = {"x": 1, "y": [2, 1, {"k": "v"}]}
        self.assertFalse(json_deep_equal(a, c))

        d = {"x": 2, "y": [1, 2, {"k": "v"}]}
        self.assertFalse(json_deep_equal(a, d))


class TestInstallerInstructions(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_marker_section_replacement_and_removal(self):
        md = self.root / "CLAUDE.md"
        md.write_text("# Project Notes\n\nExisting user instructions.\n", encoding="utf-8")

        # First upsert: appends block
        res1 = upsert_instructions_entry(md)
        self.assertEqual(res1["action"], "updated")
        content1 = md.read_text(encoding="utf-8")
        self.assertIn(BD_EXPLORE_SECTION_START, content1)
        self.assertIn(BD_EXPLORE_SECTION_END, content1)
        self.assertIn("Existing user instructions.", content1)
        self.assertIn("## bd-explore", content1)

        # Second upsert: unchanged (idempotent)
        res2 = upsert_instructions_entry(md)
        self.assertEqual(res2["action"], "unchanged")
        content2 = md.read_text(encoding="utf-8")
        self.assertEqual(content1, content2)

        # Update modified block
        modified_block = f"{BD_EXPLORE_SECTION_START}\nOutdated instructions\n{BD_EXPLORE_SECTION_END}"
        md.write_text(f"# Project Notes\n\n{modified_block}\n\nExisting user instructions.\n", encoding="utf-8")
        res3 = upsert_instructions_entry(md)
        self.assertEqual(res3["action"], "updated")
        content3 = md.read_text(encoding="utf-8")
        self.assertIn("## bd-explore", content3)
        self.assertNotIn("Outdated instructions", content3)
        self.assertIn("Existing user instructions.", content3)

        # Removal
        act = remove_marked_section(md, BD_EXPLORE_SECTION_START, BD_EXPLORE_SECTION_END)
        self.assertEqual(act, "removed")
        content_after = md.read_text(encoding="utf-8")
        self.assertNotIn(BD_EXPLORE_SECTION_START, content_after)
        self.assertNotIn(BD_EXPLORE_SECTION_END, content_after)
        self.assertIn("Existing user instructions.", content_after)

    def test_upsert_creates_file_if_not_exists(self):
        md = self.root / "AGENTS.md"
        res = upsert_instructions_entry(md)
        self.assertEqual(res["action"], "created")
        self.assertTrue(md.exists())
        self.assertIn(BD_EXPLORE_SECTION_START, md.read_text(encoding="utf-8"))

    def test_remove_marked_section_deletes_file_if_empty(self):
        md = self.root / "EMPTY.md"
        upsert_instructions_entry(md)
        self.assertTrue(md.exists())

        act = remove_marked_section(md, BD_EXPLORE_SECTION_START, BD_EXPLORE_SECTION_END)
        self.assertEqual(act, "removed")
        self.assertFalse(md.exists())

    def test_remove_marked_section_not_found(self):
        md = self.root / "NO_MARKERS.md"
        md.write_text("Just regular text", encoding="utf-8")
        act = remove_marked_section(md, BD_EXPLORE_SECTION_START, BD_EXPLORE_SECTION_END)
        self.assertEqual(act, "not-found")


class TestInstallerMemory(unittest.TestCase):
    def test_get_memory_content(self):
        self.assertEqual(get_memory_content(), MEMORY_BODY)
        self.assertIn("bd-explore", MEMORY_BODY)

    @patch("bd_explore.installer.memory.is_bd_available", return_value=False)
    def test_inject_beads_memory_no_bd(self, mock_avail):
        res = inject_beads_memory()
        self.assertEqual(res["status"], "skipped")
        self.assertIn("not found", res["reason"])

    @patch("bd_explore.installer.memory.is_bd_available", return_value=True)
    @patch("subprocess.run")
    def test_inject_beads_memory_success(self, mock_run, mock_avail):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        res = inject_beads_memory()
        self.assertEqual(res["status"], "injected")
        self.assertEqual(res["key"], MEMORY_KEY)
        mock_run.assert_called_once_with(
            ["bd", "remember", MEMORY_BODY, "--key", MEMORY_KEY],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=None,
        )

    @patch("bd_explore.installer.memory.is_bd_available", return_value=True)
    @patch("subprocess.run")
    def test_inject_beads_memory_error(self, mock_run, mock_avail):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="db locked")
        res = inject_beads_memory()
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["message"], "db locked")

    @patch("bd_explore.installer.memory.is_bd_available", return_value=False)
    def test_remove_beads_memory_no_bd(self, mock_avail):
        res = remove_beads_memory()
        self.assertEqual(res["status"], "skipped")

    @patch("bd_explore.installer.memory.is_bd_available", return_value=True)
    @patch("subprocess.run")
    def test_remove_beads_memory_success(self, mock_run, mock_avail):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        res = remove_beads_memory()
        self.assertEqual(res["status"], "removed")
        mock_run.assert_called_once_with(
            ["bd", "forget", MEMORY_KEY],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=None,
        )


class TestTargets(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.home = self.root / "home"
        self.project = self.root / "project"
        self.home.mkdir(parents=True)
        self.project.mkdir(parents=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_claude_target_global_and_local(self):
        target = ClaudeTarget(home_dir=self.home, project_dir=self.project)

        # Global install
        res_global = target.install(location="global", auto_allow=True)
        self.assertEqual(res_global["status"], "ok")

        claude_json = self.home / ".claude.json"
        self.assertTrue(claude_json.exists())
        cfg = read_json_file(claude_json)
        self.assertIn("bd-explore", cfg["mcpServers"])
        self.assertEqual(cfg["mcpServers"]["bd-explore"]["command"], "bd-explore")
        self.assertEqual(cfg["mcpServers"]["bd-explore"]["args"], ["serve", "--mcp"])

        # Permissions in settings.json
        settings_file = self.home / ".claude" / "settings.json"
        self.assertTrue(settings_file.exists())
        sett = read_json_file(settings_file)
        self.assertIn("mcp__bd-explore", sett.get("permissions", {}).get("allow", []))
        self.assertNotIn("autoApprove", sett)

        # Local install
        res_local = target.install(location="local", auto_allow=False)
        self.assertEqual(res_local["status"], "ok")
        local_mcp = self.project / ".mcp.json"
        self.assertTrue(local_mcp.exists())
        self.assertIn("bd-explore", read_json_file(local_mcp)["mcpServers"])

        local_claude_md = self.project / "CLAUDE.md"
        self.assertTrue(local_claude_md.exists())
        self.assertIn(BD_EXPLORE_SECTION_START, local_claude_md.read_text(encoding="utf-8"))

        # Uninstall global
        target.uninstall(location="global")
        self.assertNotIn("bd-explore", read_json_file(claude_json).get("mcpServers", {}))

        # Uninstall local
        target.uninstall(location="local")
        self.assertNotIn("bd-explore", read_json_file(local_mcp).get("mcpServers", {}))
        if local_claude_md.exists():
            self.assertNotIn(BD_EXPLORE_SECTION_START, local_claude_md.read_text(encoding="utf-8"))

    def test_gemini_target(self):
        target = GeminiTarget(home_dir=self.home, project_dir=self.project)

        # Global install
        res_global = target.install(location="global")
        self.assertEqual(res_global["status"], "ok")

        settings_file = self.home / ".gemini" / "settings.json"
        self.assertTrue(settings_file.exists())
        self.assertIn("bd-explore", read_json_file(settings_file)["mcpServers"])

        gemini_md = self.project / "GEMINI.md"
        # Local install adds GEMINI.md
        res_local = target.install(location="local")
        self.assertEqual(res_local["status"], "ok")
        self.assertTrue(gemini_md.exists())
        self.assertIn(BD_EXPLORE_SECTION_START, gemini_md.read_text(encoding="utf-8"))

        # Uninstall
        target.uninstall(location="global")
        self.assertNotIn("bd-explore", read_json_file(settings_file).get("mcpServers", {}))
        target.uninstall(location="local")
        if gemini_md.exists():
            self.assertNotIn(BD_EXPLORE_SECTION_START, gemini_md.read_text(encoding="utf-8"))

    def test_antigravity_target(self):
        target = AntigravityTarget(home_dir=self.home, project_dir=self.project)

        # Setup legacy config to test dual handling
        legacy_dir = self.home / ".gemini" / "antigravity"
        legacy_dir.mkdir(parents=True)
        legacy_file = legacy_dir / "mcp_config.json"
        write_json_file(legacy_file, {"mcpServers": {}})

        res = target.install(location="global")
        self.assertEqual(res["status"], "ok")

        # Unified config
        unified_file = self.home / ".gemini" / "config" / "mcp_config.json"
        self.assertTrue(unified_file.exists())
        cfg = read_json_file(unified_file)
        self.assertIn("bd-explore", cfg["mcpServers"])
        entry = cfg["mcpServers"]["bd-explore"]
        self.assertEqual(entry["command"], "bd-explore")
        self.assertEqual(entry["args"], ["serve", "--mcp"])
        # Crucial requirement: Antigravity config must NOT have 'type': 'stdio'
        self.assertNotIn("type", entry)

        # Uninstall
        target.uninstall(location="global")
        self.assertNotIn("bd-explore", read_json_file(unified_file).get("mcpServers", {}))
        self.assertNotIn("bd-explore", read_json_file(legacy_file).get("mcpServers", {}))

    def test_codex_target(self):
        target = CodexTarget(home_dir=self.home, project_dir=self.project)

        # Global install
        res = target.install(location="global")
        self.assertEqual(res["status"], "ok")

        toml_file = self.home / ".codex" / "config.toml"
        self.assertTrue(toml_file.exists())
        content = toml_file.read_text(encoding="utf-8")
        self.assertIn("[mcp_servers.bd-explore]", content)
        self.assertIn('command = "bd-explore"', content)
        self.assertIn('args = ["serve", "--mcp"]', content)

        # Local install adds AGENTS.md
        target.install(location="local")
        agents_md = self.project / "AGENTS.md"
        self.assertTrue(agents_md.exists())
        self.assertIn(BD_EXPLORE_SECTION_START, agents_md.read_text(encoding="utf-8"))

        # Uninstall
        target.uninstall(location="global")
        content_after = toml_file.read_text(encoding="utf-8") if toml_file.exists() else ""
        self.assertNotIn("[mcp_servers.bd-explore]", content_after)

        target.uninstall(location="local")
        if agents_md.exists():
            self.assertNotIn(BD_EXPLORE_SECTION_START, agents_md.read_text(encoding="utf-8"))

    def test_cursor_target(self):
        target = CursorTarget(home_dir=self.home, project_dir=self.project)

        # Global install
        res_global = target.install(location="global")
        self.assertEqual(res_global["status"], "ok")
        cursor_json = self.home / ".cursor" / "mcp.json"
        self.assertTrue(cursor_json.exists())
        self.assertIn("bd-explore", read_json_file(cursor_json)["mcpServers"])

        # Local install
        res_local = target.install(location="local")
        self.assertEqual(res_local["status"], "ok")
        rule_file = self.project / ".cursor" / "rules" / "bd-explore.mdc"
        self.assertTrue(rule_file.exists())
        self.assertIn(BD_EXPLORE_SECTION_START, rule_file.read_text(encoding="utf-8"))

        # Uninstall
        target.uninstall(location="global")
        self.assertNotIn("bd-explore", read_json_file(cursor_json).get("mcpServers", {}))
        target.uninstall(location="local")
        self.assertFalse(rule_file.exists())

    def test_agents_md_target(self):
        target = AgentsMdTarget(home_dir=self.home, project_dir=self.project)

        # Local install
        res_local = target.install(location="local")
        self.assertEqual(res_local["status"], "ok")
        local_md = self.project / "AGENTS.md"
        self.assertTrue(local_md.exists())
        self.assertIn(BD_EXPLORE_SECTION_START, local_md.read_text(encoding="utf-8"))

        # Global install
        res_global = target.install(location="global")
        self.assertEqual(res_global["status"], "ok")
        global_md = self.home / ".config" / "AGENTS.md"
        self.assertTrue(global_md.exists())
        self.assertIn(BD_EXPLORE_SECTION_START, global_md.read_text(encoding="utf-8"))

        # Uninstall
        target.uninstall(location="local")
        if local_md.exists():
            self.assertNotIn(BD_EXPLORE_SECTION_START, local_md.read_text(encoding="utf-8"))
        target.uninstall(location="global")
        if global_md.exists():
            self.assertNotIn(BD_EXPLORE_SECTION_START, global_md.read_text(encoding="utf-8"))


class TestInstallerOrchestrator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.home = self.root / "home"
        self.project = self.root / "project"
        self.home.mkdir(parents=True)
        self.project.mkdir(parents=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_target_registry(self):
        self.assertIn("claude", TARGET_REGISTRY)
        self.assertIn("gemini", TARGET_REGISTRY)
        self.assertIn("antigravity", TARGET_REGISTRY)
        self.assertIn("codex", TARGET_REGISTRY)
        self.assertIn("cursor", TARGET_REGISTRY)
        self.assertIn("agents_md", TARGET_REGISTRY)

        t = get_target("claude", home_dir=self.home, project_dir=self.project)
        self.assertIsInstance(t, ClaudeTarget)

    def test_detect_installed_targets(self):
        # Create directories for claude and cursor
        (self.home / ".claude.json").write_text("{}", encoding="utf-8")
        (self.home / ".cursor").mkdir(parents=True)

        detected = detect_installed_targets(home_dir=self.home, project_dir=self.project)
        self.assertIn("claude", detected)
        self.assertIn("cursor", detected)

    @patch("bd_explore.installer.memory.inject_beads_memory")
    def test_run_installer(self, mock_mem):
        mock_mem.return_value = {"status": "injected", "key": "bd-explore"}
        report = run_installer(
            targets=["claude", "gemini"],
            location="global",
            auto_allow=True,
            yes=True,
            home_dir=self.home,
            project_dir=self.project,
        )
        self.assertEqual(report["status"], "ok")
        self.assertEqual(len(report["targets"]), 2)
        self.assertTrue((self.home / ".claude.json").exists())
        self.assertTrue((self.home / ".gemini" / "settings.json").exists())

    @patch("bd_explore.installer.memory.remove_beads_memory")
    def test_run_uninstaller(self, mock_mem):
        mock_mem.return_value = {"status": "removed"}
        # First install
        run_installer(
            targets=["claude"],
            location="global",
            yes=True,
            home_dir=self.home,
            project_dir=self.project,
        )
        self.assertTrue((self.home / ".claude.json").exists())

        # Then uninstall
        report = run_uninstaller(
            targets=["claude"],
            location="global",
            home_dir=self.home,
            project_dir=self.project,
        )
        self.assertEqual(report["status"], "ok")
        cfg = read_json_file(self.home / ".claude.json")
        self.assertNotIn("bd-explore", cfg.get("mcpServers", {}))

    def test_print_config(self):
        claude_cfg = print_config("claude")
        self.assertIn('"bd-explore"', claude_cfg)
        self.assertIn('"command": "bd-explore"', claude_cfg)

        codex_cfg = print_config("codex")
        self.assertIn("[mcp_servers.bd-explore]", codex_cfg)

        ag_cfg = print_config("antigravity")
        self.assertIn('"bd-explore"', ag_cfg)
        self.assertNotIn('"type": "stdio"', ag_cfg)


class TestMcpPolish(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.beads_dir = self.root / ".beads"
        self.beads_dir.mkdir(parents=True)
        self.store_file = self.beads_dir / "issues.jsonl"
        self.sample_issue = {
            "id": "bd-1",
            "title": "Auth redesign",
            "status": "open",
            "issue_type": "task",
            "priority": 1,
            "description": "Switch from session cookies to JWT auth tokens",
        }
        with open(self.store_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.sample_issue) + "\n")

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_rpc_raw(self, server: McpServer, raw_bytes: bytes) -> dict | None:
        in_stream = io.BytesIO(raw_bytes)
        out_stream = io.BytesIO()
        server.handle_stream(in_stream, out_stream)
        out_stream.seek(0)
        lines = [line.strip() for line in out_stream.readlines() if line.strip()]
        if not lines:
            return None
        return json.loads(lines[0])

    def test_invalid_json_payload_not_dict(self):
        server = McpServer(default_store=self.store_file)
        # Array instead of object
        resp = self.run_rpc_raw(server, b"[1, 2, 3]\n")
        self.assertIsNotNone(resp)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32600)
        self.assertIn("Invalid Request", resp["error"]["message"])

        # String instead of object
        resp2 = self.run_rpc_raw(server, b'"hello world"\n')
        self.assertIsNotNone(resp2)
        self.assertIn("error", resp2)
        self.assertEqual(resp2["error"]["code"], -32600)

    def test_is_error_flag_on_tool_call_failure(self):
        server = McpServer()
        resp = self.run_rpc_raw(
            server,
            json.dumps({
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "bd_explore",
                    "arguments": {"store": "/path/to/nonexistent/store"},
                },
            }).encode("utf-8") + b"\n",
        )
        self.assertEqual(resp["id"], 10)
        self.assertTrue(resp["result"]["isError"])
        self.assertIn("store export not found", resp["result"]["content"][0]["text"])

    def test_blast_error_is_error_flag(self):
        server = McpServer(default_store=self.store_file)
        resp = self.run_rpc_raw(
            server,
            json.dumps({
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {
                    "name": "bd_explore",
                    "arguments": {"blast": "nonexistent-id", "store": str(self.store_file)},
                },
            }).encode("utf-8") + b"\n",
        )
        self.assertEqual(resp["id"], 11)
        self.assertTrue(resp["result"]["isError"])
        self.assertIn("no bead matching 'nonexistent-id'", resp["result"]["content"][0]["text"])

    def test_defensive_limit_and_budget_parsing(self):
        server = McpServer(default_store=self.store_file)
        resp = self.run_rpc_raw(
            server,
            json.dumps({
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {
                    "name": "bd_explore",
                    "arguments": {
                        "query": "JWT",
                        "limit": "not_an_int",
                        "budget": -100,
                        "store": str(self.store_file),
                    },
                },
            }).encode("utf-8") + b"\n",
        )
        self.assertEqual(resp["id"], 12)
        self.assertFalse(resp["result"].get("isError", False))
        content = resp["result"]["content"][0]["text"]
        self.assertIn("bd-1 [OPEN · P1 · task", content)

    def test_db_connection_closed_on_tool_call(self):
        server = McpServer(default_store=self.store_file)
        closed_flags = []

        original_open = sys.modules["bd_explore.explorer"].open_index

        class ConProxy:
            def __init__(self, con):
                self._con = con

            def close(self):
                closed_flags.append(True)
                return self._con.close()

            def __getattr__(self, name):
                return getattr(self._con, name)

        def mock_open_index(*args, **kwargs):
            real_con = original_open(*args, **kwargs)
            return ConProxy(real_con)

        with patch("bd_explore.explorer.open_index", side_effect=mock_open_index):
            self.run_rpc_raw(
                server,
                json.dumps({
                    "jsonrpc": "2.0",
                    "id": 13,
                    "method": "tools/call",
                    "params": {
                        "name": "bd_explore",
                        "arguments": {"query": "Auth", "store": str(self.store_file)},
                    },
                }).encode("utf-8") + b"\n",
            )
        self.assertTrue(len(closed_flags) >= 1)

    def test_codex_preserves_other_toml_tables(self):
        target = CodexTarget(home_dir=self.root, project_dir=self.root)
        toml_file = self.root / ".codex" / "config.toml"
        toml_file.parent.mkdir(parents=True, exist_ok=True)
        toml_file.write_text(
            '[general]\nmodel = "gpt-4"\n\n[mcp_servers.other]\ncommand = "other"\n',
            encoding="utf-8",
        )

        target.install(location="global")
        installed = toml_file.read_text(encoding="utf-8")
        self.assertIn('[general]\nmodel = "gpt-4"', installed)
        self.assertIn('[mcp_servers.other]\ncommand = "other"', installed)
        self.assertIn("[mcp_servers.bd-explore]", installed)

        target.uninstall(location="global")
        uninstalled = toml_file.read_text(encoding="utf-8")
        self.assertIn('[general]\nmodel = "gpt-4"', uninstalled)
        self.assertIn('[mcp_servers.other]\ncommand = "other"', uninstalled)
        self.assertNotIn("[mcp_servers.bd-explore]", uninstalled)


if __name__ == "__main__":
    unittest.main()
