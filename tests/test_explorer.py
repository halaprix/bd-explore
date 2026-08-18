import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

src_dir = str(Path(__file__).resolve().parents[1] / "src")
while src_dir in sys.path:
    sys.path.remove(src_dir)
sys.path.insert(0, src_dir)

from bd_explore.explorer import ExploreError, blast, explore


class TestExplorer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.beads_dir = self.root / ".beads"
        self.beads_dir.mkdir(parents=True)
        self.store_file = self.beads_dir / "issues.jsonl"

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

        self.env_patcher = patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.root / "cache")})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.temp_dir.cleanup()

    def test_explore_query_returns_formatted_hits(self):
        out = explore("JWT cookies", store=self.store_file)
        self.assertIn("task-1 [OPEN · P1 · task", out)
        self.assertIn("Switch from session cookies", out)

    def test_explore_applies_field_filters(self):
        out = explore("status:open Token", store=self.store_file)
        self.assertIn("═══ task-2", out)
        self.assertNotIn("═══ epic-1", out)

    def test_explore_empty_query_lists_recent_docs(self):
        out = explore("", store=self.store_file)
        self.assertIn("task-2", out)

    def test_explore_no_matches_message(self):
        out = explore("nonexistentquerykeyword12345", store=self.store_file)
        self.assertIn("no matches — try fewer terms, or status:all", out)

    def test_explore_rebuild_without_query_returns_summary(self):
        out = explore("", store=self.store_file, rebuild=True)
        self.assertIn("rebuilt: 3 docs from", out)
        self.assertIn(str(self.store_file), out)

    def test_explore_rebuild_with_query_searches(self):
        out = explore("JWT", store=self.store_file, rebuild=True)
        self.assertIn("task-1", out)
        self.assertNotIn("rebuilt:", out)

    def test_explore_store_not_found_raises(self):
        with self.assertRaises(ExploreError) as cm:
            explore("anything", store=self.root / "nowhere" / "issues.jsonl")
        self.assertIn("store export not found", str(cm.exception))

    def test_explore_limit_caps_hits(self):
        out = explore("status:all", store=self.store_file, limit=1)
        self.assertEqual(out.count("═══"), 1)

    def test_explore_coerces_invalid_limit_and_budget_to_defaults(self):
        out = explore("JWT", store=self.store_file, limit="bogus", budget=None)
        self.assertIn("task-1", out)

    def test_explore_clamps_tiny_budget_to_minimum(self):
        out = explore("status:all", store=self.store_file, budget=5)
        self.assertLessEqual(len(out), 100)
        self.assertGreater(len(out), 0)

    def test_blast_returns_transitive_closure(self):
        out = blast("task-1", store=self.store_file)
        self.assertIn("task-1 [OPEN · P1 · task", out)
        self.assertIn("beads this blocks (transitively): 1", out)
        self.assertIn("task-2", out)
        self.assertIn("epic ancestry: 1", out)

    def test_blast_no_match_raises(self):
        with self.assertRaises(ExploreError) as cm:
            blast("nonexistent-id", store=self.store_file)
        self.assertIn("no bead matching 'nonexistent-id'", str(cm.exception))

    def test_blast_honors_budget(self):
        out = blast("task-1", store=self.store_file, budget=120)
        self.assertLessEqual(len(out), 120)


if __name__ == "__main__":
    unittest.main()
