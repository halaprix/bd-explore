import json
import sys
import tempfile
import unittest
from pathlib import Path

src_dir = str(Path(__file__).resolve().parents[1] / "src")
while src_dir in sys.path:
    sys.path.remove(src_dir)
sys.path.insert(0, src_dir)

from bd_explore.index import build_index
from bd_explore.search import blast_data, hydrate, hydrate_blast, render, render_blast, search


def rec(rec_id, body="Body text", **overrides):
    base = {
        "id": rec_id,
        "kind": "issue",
        "title": f"Title {rec_id}",
        "status": "open",
        "itype": "task",
        "priority": 1,
        "created": "2026-08-01",
        "updated": "2026-08-02",
        "closed": "",
        "body": body,
        "neighborhood": {},
    }
    base.update(overrides)
    return base


class TestRenderPure(unittest.TestCase):
    """render/render_blast are pure: records in, string out — no connection."""

    def test_render_empty_records(self):
        self.assertEqual(render([], 1000), "no matches — try fewer terms, or status:all")

    def test_render_zero_budget(self):
        self.assertEqual(render([rec("t-1")], 0), "")

    def test_render_record_with_neighborhood(self):
        r = rec("t-1", neighborhood={"blocks": [("t-9", "Title t-9 [open]")]})
        out = render([r], 1000)
        self.assertIn("═══ t-1 [OPEN · P1 · task · updated 2026-08-02]", out)
        self.assertIn("Body text", out)
        self.assertIn("── neighborhood ──", out)
        self.assertIn("blocks: t-9 — Title t-9 [open]", out)

    def test_render_truncation_notice(self):
        out = render([rec("t-1", body="X" * 3000)], 1200)
        self.assertIn("… [truncated — full body: bd show t-1]", out)

    def test_render_omitted_hits_notice(self):
        records = [rec(f"t-{i}", body="Y" * 400) for i in range(6)]
        out = render(records, 300)
        self.assertIn("omitted", out)

    def test_render_hard_budget_cap(self):
        records = [rec(f"t-{i}", body="Z" * 500) for i in range(5)]
        for budget in (50, 100, 400, 1000, 24000):
            out = render(records, budget)
            self.assertLessEqual(len(out), budget)

    def test_render_blast_pure(self):
        data = {
            "root": rec("t-1", status="closed", closed="2026-08-03"),
            "blocked_by_transitively": [],
            "blocks_transitively": ["t-2", "t-external"],
            "epic_ancestry": ["epic-1"],
            "labels": {"t-2": "Title t-2 [open]", "epic-1": "The Epic [in_progress]"},
        }
        out = render_blast(data, 24_000)
        self.assertIn("═══ t-1 [CLOSED · P1 · task", out)
        self.assertIn("this bead is blocked by (transitively): none", out)
        self.assertIn("beads this blocks (transitively): 2", out)
        self.assertIn("t-2  Title t-2 [open]", out)
        self.assertIn("t-external   [?]", out)
        self.assertIn("epic-1  The Epic [in_progress]", out)

    def test_render_blast_budget_cap(self):
        data = {
            "root": rec("t-1"),
            "blocked_by_transitively": [f"b-{i}" for i in range(30)],
            "blocks_transitively": [],
            "epic_ancestry": [],
            "labels": {},
        }
        for budget in (50, 120, 24_000):
            self.assertLessEqual(len(render_blast(data, budget)), budget)


class TestHydrate(unittest.TestCase):
    """hydrate/hydrate_blast fetch everything render needs in batched queries."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.store_file = self.root / "issues.jsonl"
        issues = [
            {
                "id": "epic-1", "title": "Authentication Epic", "status": "in_progress",
                "issue_type": "epic", "priority": 1, "created_at": "2026-08-01",
                "updated_at": "2026-08-01", "description": "Auth overhaul", "dependencies": [],
            },
            {
                "id": "task-1", "title": "OAuth Provider Setup", "status": "closed",
                "issue_type": "task", "priority": 2, "created_at": "2026-08-02",
                "updated_at": "2026-08-03", "closed_at": "2026-08-03",
                "description": "Set up providers",
                "dependencies": [{"issue_id": "task-1", "depends_on_id": "epic-1", "type": "parent-child"}],
            },
            {
                "id": "task-2", "title": "JWT Token Refresh", "status": "open",
                "issue_type": "task", "priority": 1, "created_at": "2026-08-04",
                "updated_at": "2026-08-05", "description": "Rotate tokens. Mentioned task-1.",
                "dependencies": [
                    {"issue_id": "task-2", "depends_on_id": "task-1", "type": "blocks"},
                    {"issue_id": "task-2", "depends_on_id": "epic-1", "type": "parent-child"},
                ],
            },
        ]
        with open(self.store_file, "w", encoding="utf-8") as f:
            for i in issues:
                f.write(json.dumps(i) + "\n")
        self.con = build_index(self.store_file, self.root / "test.db")

    def tearDown(self):
        self.con.close()
        self.temp_dir.cleanup()

    def test_hydrate_empty(self):
        self.assertEqual(hydrate(self.con, []), [])

    def test_hydrate_attaches_neighborhood(self):
        rows = search(self.con, "", {"status": ["all"]}, limit=10)
        records = hydrate(self.con, rows)
        by_id = {r["id"]: r for r in records}
        self.assertIn("child of", by_id["task-2"]["neighborhood"])
        self.assertEqual(by_id["task-2"]["neighborhood"]["child of"][0][0], "epic-1")
        self.assertIn("Authentication Epic", by_id["task-2"]["neighborhood"]["child of"][0][1])
        self.assertIn("blocked by", by_id["task-2"]["neighborhood"])
        self.assertIn("children", by_id["epic-1"]["neighborhood"])

    def test_hydrate_query_count_is_bounded(self):
        rows = search(self.con, "", {"status": ["all"]}, limit=10)
        statements = []
        self.con.set_trace_callback(statements.append)
        try:
            hydrate(self.con, rows)
        finally:
            self.con.set_trace_callback(None)
        selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
        self.assertLessEqual(len(selects), 2, f"expected batched queries, got: {selects}")

    def test_hydrate_blast_attaches_labels(self):
        data = blast_data(self.con, "task-1")
        hydrated = hydrate_blast(self.con, data)
        self.assertEqual(hydrated["labels"]["task-2"], "JWT Token Refresh [open]")
        self.assertEqual(hydrated["labels"]["epic-1"], "Authentication Epic [in_progress]")
        self.assertEqual(hydrated["blocks_transitively"], data["blocks_transitively"])


if __name__ == "__main__":
    unittest.main()
