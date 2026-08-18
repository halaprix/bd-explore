import importlib.util
import io
import json
import os
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

from bd_explore.constants import VERSION


class TestCli(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.beads_dir = self.root / ".beads"
        self.beads_dir.mkdir(parents=True)
        self.store_file = self.beads_dir / "issues.jsonl"

        self.sample_issues = [
            {
                "id": "epic-1",
                "title": "Authentication Epic",
                "status": "in_progress",
                "issue_type": "epic",
                "priority": 1,
                "created_at": "2026-08-01T10:00:00Z",
                "updated_at": "2026-08-10T12:00:00Z",
                "closed_at": None,
                "description": "Auth epic root description",
                "dependencies": [],
            },
            {
                "id": "task-1",
                "title": "JWT Validation",
                "status": "closed",
                "issue_type": "task",
                "priority": 2,
                "created_at": "2026-08-02T10:00:00Z",
                "updated_at": "2026-08-05T12:00:00Z",
                "closed_at": "2026-08-05T12:00:00Z",
                "description": "Validate claims and tokens. See epic-1.",
                "dependencies": [
                    {"issue_id": "task-1", "depends_on_id": "epic-1", "type": "parent-child"}
                ],
            },
            {
                "id": "task-2",
                "title": "Token Refresh Endpoint",
                "status": "open",
                "issue_type": "task",
                "priority": 1,
                "created_at": "2026-08-03T10:00:00Z",
                "updated_at": "2026-08-08T12:00:00Z",
                "closed_at": None,
                "description": "Handle refresh rotation. Blocked by task-1.",
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

    def test_version_flag(self):
        from bd_explore.cli import main

        buf = io.StringIO()
        with patch("sys.stdout", buf), self.assertRaises(SystemExit) as cm:
            main(["--version"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn(f"bd-explore {VERSION}", buf.getvalue())

    def test_help_flag(self):
        from bd_explore.cli import main

        buf = io.StringIO()
        with patch("sys.stdout", buf), self.assertRaises(SystemExit) as cm:
            main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        out = buf.getvalue()
        self.assertIn("bd-explore", out)
        self.assertIn("--blast", out)
        self.assertIn("--rebuild", out)
        self.assertIn("serve", out)
        self.assertIn("install", out)
        self.assertIn("uninstall", out)
        self.assertIn("print-config", out)

    def test_search_query_positional(self):
        from bd_explore.cli import main

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = main(["--store", str(self.store_file), "JWT", "Validation"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("task-1", out)
        self.assertIn("JWT Validation", out)
        self.assertIn("Validate claims and tokens", out)

    def test_search_query_with_filters(self):
        from bd_explore.cli import main

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = main(["--store", str(self.store_file), "status:open", "Token"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("═══ task-2", out)
        self.assertIn("Token Refresh Endpoint", out)
        self.assertNotIn("═══ task-1", out)

    def test_search_query_limit_and_budget(self):
        from bd_explore.cli import main

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = main([
                "--store", str(self.store_file),
                "-n", "1",
                "--budget", "1500",
                "status:all",
            ])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        # Only 1 doc should be output
        self.assertEqual(out.count("═══"), 1)

    def test_search_query_no_matches(self):
        from bd_explore.cli import main

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = main(["--store", str(self.store_file), "nonexistentquerykeyword12345"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("no matches — try fewer terms, or status:all", out)

    def test_blast_radius(self):
        from bd_explore.cli import main

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = main(["--store", str(self.store_file), "--blast", "task-2"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("task-2", out)
        self.assertIn("this bead is blocked by (transitively)", out)
        self.assertIn("task-1", out)

    def test_blast_radius_nonexistent(self):
        from bd_explore.cli import main

        err_buf = io.StringIO()
        with patch("sys.stderr", err_buf), self.assertRaises(SystemExit) as cm:
            main(["--store", str(self.store_file), "--blast", "nonexistent-id"])
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("no bead matching 'nonexistent-id'", err_buf.getvalue())

    def test_rebuild_flag_without_query(self):
        from bd_explore.cli import main

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = main(["--store", str(self.store_file), "--rebuild"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("rebuilt: 3 docs from", out)

    def test_rebuild_flag_with_query(self):
        from bd_explore.cli import main

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = main(["--store", str(self.store_file), "--rebuild", "JWT"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("task-1", out)

    def test_no_args_error(self):
        from bd_explore.cli import main

        err_buf = io.StringIO()
        with patch("sys.stderr", err_buf), self.assertRaises(SystemExit) as cm:
            main([])
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("give a query, --blast <id>, or --rebuild", err_buf.getvalue())

    def test_store_not_found(self):
        from bd_explore.cli import main

        err_buf = io.StringIO()
        with patch("sys.stderr", err_buf), self.assertRaises(SystemExit) as cm:
            main(["--store", str(self.root / "nonexistent" / "issues.jsonl"), "test"])
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("store export not found", err_buf.getvalue())

    def test_mcp_flag_and_serve_subcommand(self):
        from bd_explore.cli import main

        with patch("bd_explore.cli.run_mcp_server") as mock_mcp:
            code = main(["--mcp", "--store", str(self.store_file)])
            self.assertEqual(code, 0)
            mock_mcp.assert_called_once_with(default_store=self.store_file)

        with patch("bd_explore.cli.run_mcp_server") as mock_mcp:
            code = main(["serve", "--store", str(self.store_file)])
            self.assertEqual(code, 0)
            mock_mcp.assert_called_once_with(default_store=self.store_file)

    def test_print_config_subcommand(self):
        from bd_explore.cli import main

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = main(["print-config", "claude"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("bd-explore", out)
        self.assertIn('"command": "bd-explore"', out)

        # Flag format: --target claude
        buf2 = io.StringIO()
        with patch("sys.stdout", buf2):
            code = main(["print-config", "--target", "gemini"])
        self.assertEqual(code, 0)
        out2 = buf2.getvalue()
        self.assertIn("bd-explore", out2)

    def test_print_config_invalid_target(self):
        from bd_explore.cli import main

        err_buf = io.StringIO()
        with patch("sys.stderr", err_buf), self.assertRaises(SystemExit) as cm:
            main(["print-config", "unknown_agent_xyz"])
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("Unknown target", err_buf.getvalue())

    def test_install_subcommand_yes_flag(self):
        from bd_explore.cli import main

        with patch("bd_explore.cli.run_installer") as mock_installer:
            mock_installer.return_value = {
                "status": "ok",
                "location": "global",
                "targets": [{"target": "claude", "status": "ok", "files": ["/mock/claude.json"]}],
                "memory": {"status": "injected", "command": "bd remember"},
            }
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                code = main(["install", "--yes", "--targets", "claude", "--auto-allow"])
            self.assertEqual(code, 0)
            mock_installer.assert_called_once_with(
                targets=["claude"],
                location="global",
                auto_allow=True,
                yes=True,
            )
            out = buf.getvalue()
            self.assertIn("claude", out)
            self.assertIn("Installation complete", out)

    def test_install_subcommand_project_location(self):
        from bd_explore.cli import main

        with patch("bd_explore.cli.run_installer") as mock_installer:
            mock_installer.return_value = {
                "status": "ok",
                "location": "project",
                "targets": [{"target": "cursor", "status": "ok", "files": [".cursor/mcp.json"]}],
                "memory": {"status": "skipped", "message": "already injected"},
            }
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                code = main(["install", "-y", "-t", "cursor", "-l", "project"])
            self.assertEqual(code, 0)
            mock_installer.assert_called_once_with(
                targets=["cursor"],
                location="project",
                auto_allow=False,
                yes=True,
            )

    def test_install_subcommand_interactive_confirmed(self):
        from bd_explore.cli import main

        with patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", side_effect=["claude,gemini", "global", "y"]), \
             patch("bd_explore.cli.detect_installed_targets", return_value=["claude"]), \
             patch("bd_explore.cli.run_installer") as mock_installer:

            mock_installer.return_value = {
                "status": "ok",
                "location": "global",
                "targets": [
                    {"target": "claude", "status": "ok", "files": ["/mock/claude.json"]},
                    {"target": "gemini", "status": "ok", "files": ["/mock/gemini.json"]},
                ],
                "memory": {"status": "injected", "command": "bd remember"},
            }
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                code = main(["install"])
            self.assertEqual(code, 0)
            mock_installer.assert_called_once_with(
                targets=["claude", "gemini"],
                location="global",
                auto_allow=False,
                yes=True,
            )
            out = buf.getvalue()
            self.assertIn("claude", out)
            self.assertIn("gemini", out)

    def test_install_subcommand_interactive_cancelled(self):
        from bd_explore.cli import main

        with patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", side_effect=["claude", "global", "n"]), \
             patch("bd_explore.cli.detect_installed_targets", return_value=["claude"]), \
             patch("bd_explore.cli.run_installer") as mock_installer:

            buf = io.StringIO()
            with patch("sys.stdout", buf):
                code = main(["install"])
            self.assertEqual(code, 0)
            mock_installer.assert_not_called()
            out = buf.getvalue()
            self.assertIn("Installation cancelled", out)

    def test_uninstall_subcommand_yes_flag(self):
        from bd_explore.cli import main

        with patch("bd_explore.cli.run_uninstaller") as mock_uninstaller:
            mock_uninstaller.return_value = {
                "status": "ok",
                "location": "global",
                "targets": [{"target": "claude", "status": "ok", "files": ["/mock/claude.json"]}],
                "memory": {"status": "removed", "command": "bd forget bd-explore"},
            }
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                code = main(["uninstall", "--yes", "--targets", "claude"])
            self.assertEqual(code, 0)
            mock_uninstaller.assert_called_once_with(
                targets=["claude"],
                location="global",
            )
            out = buf.getvalue()
            self.assertIn("claude", out)
            self.assertIn("Uninstallation complete", out)

    def test_uninstall_subcommand_interactive_cancelled(self):
        from bd_explore.cli import main

        with patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="n"), \
             patch("bd_explore.cli.run_uninstaller") as mock_uninstaller:

            buf = io.StringIO()
            with patch("sys.stdout", buf):
                code = main(["uninstall", "--targets", "claude"])
            self.assertEqual(code, 0)
            mock_uninstaller.assert_not_called()
            out = buf.getvalue()
            self.assertIn("Uninstallation cancelled", out)

    def test_legacy_bd_explore_shim(self):
        legacy_file = Path(__file__).resolve().parents[1] / "bd_explore.py"
        spec = importlib.util.spec_from_file_location("bd_explore_legacy", str(legacy_file))
        legacy_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy_mod)

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = legacy_mod.main(["--store", str(self.store_file), "Authentication"])
        self.assertEqual(code, 0)
        self.assertIn("epic-1", buf.getvalue())

    def test_dunder_main_module(self):
        import runpy

        with patch("bd_explore.cli.main", return_value=0) as mock_main:
            with self.assertRaises(SystemExit) as cm:
                runpy.run_module("bd_explore.__main__", run_name="__main__")
            self.assertEqual(cm.exception.code, 0)
            mock_main.assert_called_once()


if __name__ == "__main__":
    unittest.main()
