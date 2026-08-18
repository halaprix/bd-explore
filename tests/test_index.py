import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

src_dir = str(Path(__file__).resolve().parents[1] / "src")
while src_dir in sys.path:
    sys.path.remove(src_dir)
sys.path.insert(0, src_dir)

from bd_explore.index import (
    build_index,
    cache_db_path,
    compose_body,
    find_store,
    load_memories,
    open_index,
)


class TestIndex(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.beads_dir = self.root / ".beads"
        self.beads_dir.mkdir(parents=True)
        self.store_file = self.beads_dir / "issues.jsonl"

        # Mock issues with description, notes, comments, close reason, dependencies, and mentions
        self.sample_issues = [
            {
                "id": "bd-100",
                "title": "Epic Root Issue for PR #99",
                "status": "in_progress",
                "issue_type": "epic",
                "priority": 1,
                "created_at": "2026-08-01T10:00:00Z",
                "updated_at": "2026-08-10T12:00:00Z",
                "closed_at": None,
                "description": "Top level epic for auth migration",
                "dependencies": [],
            },
            {
                "id": "bd-101",
                "title": "Implement JWT validation",
                "status": "closed",
                "issue_type": "task",
                "priority": 2,
                "created_at": "2026-08-02T10:00:00Z",
                "updated_at": "2026-08-05T12:00:00Z",
                "closed_at": "2026-08-05T12:00:00Z",
                "description": "Validate claims and tokens. See bd-100. GH #42",
                "design": "Use RSA256 signature verification",
                "acceptance_criteria": "Pass all crypto test vectors",
                "notes": "Handoff: bd-102 depends on this token format.",
                "comments": [{"author": "alice", "created_at": "2026-08-03T11:00:00Z", "text": "Tested on staging"}],
                "close_reason": "Merged in PR #43",
                "dependencies": [
                    {"issue_id": "bd-101", "depends_on_id": "bd-100", "type": "parent-child"}
                ],
            },
            {
                "id": "bd-102",
                "title": "Token refresh endpoint",
                "status": "open",
                "issue_type": "task",
                "priority": 1,
                "created_at": "2026-08-03T10:00:00Z",
                "updated_at": "2026-08-08T12:00:00Z",
                "closed_at": None,
                "description": "Handle refresh rotation. Blocked by bd-101.",
                "dependencies": [
                    {"issue_id": "bd-102", "depends_on_id": "bd-101", "type": "blocks"}
                ],
            },
        ]
        with open(self.store_file, "w", encoding="utf-8") as f:
            for issue in self.sample_issues:
                f.write(json.dumps(issue) + "\n")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_find_store_explicit_file(self):
        found = find_store(str(self.store_file))
        self.assertEqual(found.resolve(), self.store_file.resolve())

    def test_find_store_explicit_dir(self):
        found = find_store(str(self.root))
        self.assertEqual(found.resolve(), self.store_file.resolve())

    def test_find_store_explicit_missing(self):
        with self.assertRaises(FileNotFoundError):
            find_store(str(self.root / "nonexistent"))

    def test_find_store_rejects_non_beads_file(self):
        random_file = self.root / "random.txt"
        random_file.write_text("not a store", encoding="utf-8")
        with self.assertRaises(ValueError):
            find_store(str(random_file))

    def test_find_store_env(self):
        with patch.dict(os.environ, {"BD_EXPLORE_STORE": str(self.store_file)}):
            found = find_store()
            self.assertEqual(found.resolve(), self.store_file.resolve())

    def test_find_store_from_cwd(self):
        orig_cwd = os.getcwd()
        nested = self.root / "sub" / "deep"
        nested.mkdir(parents=True)
        try:
            os.chdir(nested)
            with patch.dict(os.environ, {}, clear=True):
                # Ensure BD_EXPLORE_STORE is not set
                if "BD_EXPLORE_STORE" in os.environ:
                    del os.environ["BD_EXPLORE_STORE"]
                found = find_store()
                self.assertEqual(found.resolve(), self.store_file.resolve())
        finally:
            os.chdir(orig_cwd)

    def test_find_store_not_found(self):
        empty_temp = tempfile.TemporaryDirectory()
        orig_cwd = os.getcwd()
        try:
            os.chdir(empty_temp.name)
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(FileNotFoundError):
                    find_store()
        finally:
            os.chdir(orig_cwd)
            empty_temp.cleanup()

    def test_compose_body(self):
        body = compose_body(self.sample_issues[1])
        self.assertIn("Validate claims and tokens", body)
        self.assertIn("DESIGN:\nUse RSA256", body)
        self.assertIn("ACCEPTANCE:\nPass all crypto", body)
        self.assertIn("NOTES:\nHandoff: bd-102", body)
        self.assertIn("COMMENT (alice 2026-08-03):\nTested on staging", body)
        self.assertIn("CLOSE REASON:\nMerged in PR #43", body)

    def test_compose_body_empty(self):
        body = compose_body({"id": "bd-999"})
        self.assertEqual(body, "")

    def test_cache_db_path(self):
        os.environ["XDG_CACHE_HOME"] = str(self.root / "cache_home")
        p1 = cache_db_path(self.store_file)
        p2 = cache_db_path(self.store_file)
        self.assertEqual(p1, p2)
        self.assertTrue(str(p1).endswith(".db"))
        self.assertTrue(p1.parent.exists())

    def test_load_memories_cli_unavailable(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("bd not found")):
            mems = load_memories()
            self.assertEqual(mems, [])

    def test_load_memories_dict_output_with_cwd(self):
        mock_res = MagicMock(returncode=0, stdout=json.dumps({"arch_decision": "Use SQLite FTS5"}))
        with patch("subprocess.run", return_value=mock_res) as mock_run:
            mems = load_memories(cwd=self.root)
            self.assertEqual(len(mems), 1)
            self.assertEqual(mems[0]["key"], "arch_decision")
            self.assertEqual(mems[0]["content"], "Use SQLite FTS5")
            mock_run.assert_called_once_with(
                ["bd", "memories", "--json"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self.root,
            )

    def test_load_memories_list_output(self):
        mock_res = MagicMock(returncode=0, stdout=json.dumps([{"key": "rule1", "content": "Keep zero deps"}]))
        with patch("subprocess.run", return_value=mock_res):
            mems = load_memories()
            self.assertEqual(len(mems), 1)
            self.assertEqual(mems[0]["key"], "rule1")
            self.assertEqual(mems[0]["content"], "Keep zero deps")

    def test_build_and_query_index(self):
        db_path = self.root / "cache.db"
        con = build_index(self.store_file, db_path)

        # Check docs table
        doc_count = con.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        self.assertEqual(doc_count, 3)

        # Check mention edges: bd-101 cited bd-100 and bd-102
        mentions = con.execute("SELECT src, dst, kind FROM edges WHERE kind='mentions'").fetchall()
        mention_pairs = [(m[0], m[1]) for m in mentions]
        self.assertIn(("bd-101", "bd-100"), mention_pairs)
        self.assertIn(("bd-101", "bd-102"), mention_pairs)

        # Check GH ref edges (including PR #99 from bd-100 title)
        gh_refs = [(r[0], r[1], r[2]) for r in con.execute("SELECT src, dst, kind FROM edges WHERE kind='gh-ref'").fetchall()]
        self.assertIn(("bd-100", "#99", "gh-ref"), gh_refs)
        self.assertIn(("bd-101", "#42", "gh-ref"), gh_refs)
        self.assertIn(("bd-101", "#43", "gh-ref"), gh_refs)

        # Check dependency edges
        dep_edges = [(r[0], r[1], r[2]) for r in con.execute("SELECT src, dst, kind FROM edges WHERE kind='parent-child'").fetchall()]
        self.assertEqual(dep_edges, [("bd-101", "bd-100", "parent-child")])

        # Check FTS index populated
        fts_hits = con.execute("SELECT id FROM docs_fts WHERE docs_fts MATCH 'RSA256'").fetchall()
        self.assertEqual(len(fts_hits), 1)
        self.assertEqual(fts_hits[0][0], "bd-101")

        con.close()

    def test_build_index_skips_invalid_json_lines(self):
        corrupt_store = self.root / "corrupt_lines.jsonl"
        with open(corrupt_store, "w", encoding="utf-8") as f:
            f.write("NOT VALID JSON\n")
            f.write('{"title": "Missing ID"}\n')
            f.write('{"id": "valid-1", "title": "Valid Issue", "status": "open"}\n')
        db_path = self.root / "corrupt_lines.db"
        con = build_index(corrupt_store, db_path)
        docs = con.execute("SELECT id, title FROM docs").fetchall()
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["id"], "valid-1")
        con.close()

    def test_build_index_error_closes_con(self):
        # Trigger an error during index build (e.g. non-existent directory for db_path)
        bad_store = self.store_file
        db_path = self.root / "non_existent_dir" / "sub" / "db.db"
        with self.assertRaises(sqlite3.OperationalError):
            build_index(bad_store, db_path)

    def test_open_index_cache_reuse(self):
        os.environ["XDG_CACHE_HOME"] = str(self.root / "cache_home")
        con1 = open_index(self.store_file)
        meta1 = dict(con1.execute("SELECT k, v FROM meta"))
        con1.close()

        # Opening again without modifications reuses DB
        con2 = open_index(self.store_file)
        meta2 = dict(con2.execute("SELECT k, v FROM meta"))
        self.assertEqual(meta1["mtime"], meta2["mtime"])
        con2.close()

        # Force rebuild recreates
        con3 = open_index(self.store_file, force=True)
        self.assertIsNotNone(con3)
        con3.close()


if __name__ == "__main__":
    unittest.main()
