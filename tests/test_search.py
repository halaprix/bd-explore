import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

src_dir = str(Path(__file__).resolve().parents[1] / "src")
while src_dir in sys.path:
    sys.path.remove(src_dir)
sys.path.insert(0, src_dir)

from bd_explore.index import build_index
from bd_explore.search import (
    blast_data,
    escape_like,
    format_blast,
    format_output,
    fts_escape,
    neighborhood,
    parse_query,
    render_header,
    search,
    status_rank,
)


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.store_file = self.root / "issues.jsonl"
        self.db_path = self.root / "test.db"

        issues = [
            {
                "id": "epic-1",
                "title": "Authentication Epic",
                "status": "in_progress",
                "issue_type": "epic",
                "priority": 1,
                "created_at": "2026-08-01",
                "updated_at": "2026-08-01",
                "description": "Auth overhaul with OAuth and JWT. See GH #100",
                "dependencies": [],
            },
            {
                "id": "task-1",
                "title": "OAuth Provider Setup",
                "status": "closed",
                "issue_type": "task",
                "priority": 2,
                "created_at": "2026-08-02",
                "updated_at": "2026-08-03",
                "closed_at": "2026-08-03",
                "description": "Set up Google and GitHub OAuth providers",
                "close_reason": "Completed and merged",
                "dependencies": [
                    {"issue_id": "task-1", "depends_on_id": "epic-1", "type": "parent-child"}
                ],
            },
            {
                "id": "task-2",
                "title": "JWT Token Refresh",
                "status": "open",
                "issue_type": "task",
                "priority": 1,
                "created_at": "2026-08-04",
                "updated_at": "2026-08-05",
                "description": "Rotate refresh tokens safely OAuth style. Mentioned task-3.",
                "dependencies": [
                    {"issue_id": "task-2", "depends_on_id": "task-1", "type": "blocks"},
                    {"issue_id": "task-2", "depends_on_id": "epic-1", "type": "parent-child"},
                ],
            },
            {
                "id": "task-3",
                "title": "Session Invalidation",
                "status": "deferred",
                "issue_type": "task",
                "priority": 3,
                "created_at": "2026-08-05",
                "updated_at": "2026-08-06",
                "description": "Blacklist tokens on logout. Blocked by task-2.",
                "dependencies": [
                    {"issue_id": "task-3", "depends_on_id": "task-2", "type": "blocks"},
                    {"issue_id": "task-3", "depends_on_id": "epic-1", "type": "parent-child"},
                    {"issue_id": "task-3", "depends_on_id": "task-1", "type": "discovered-from"},
                    {"issue_id": "task-3", "depends_on_id": "task-0", "type": "supersedes"},
                    {"issue_id": "task-3", "depends_on_id": "task-4", "type": "related"},
                ],
            },
        ]
        with open(self.store_file, "w", encoding="utf-8") as f:
            for i in issues:
                f.write(json.dumps(i) + "\n")

        self.con = build_index(self.store_file, self.db_path)

    def tearDown(self):
        self.con.close()
        self.temp_dir.cleanup()

    def test_parse_query_filters_and_text(self):
        text, filters = parse_query(
            "OAuth refresh status:open,in_progress type:task,epic priority:1,2 epic:epic-1 id:task-2"
        )
        self.assertEqual(text, "OAuth refresh")
        self.assertEqual(filters["status"], ["open", "in_progress"])
        self.assertEqual(filters["type"], ["task", "epic"])
        self.assertEqual(filters["priority"], ["1", "2"])
        self.assertEqual(filters["epic"], ["epic-1"])
        self.assertEqual(filters["id"], ["task-2"])

    def test_parse_query_unknown_prefix_falls_back_to_text(self):
        text, filters = parse_query("PR #42: fixed auth bug http://example.com/test:123")
        self.assertEqual(text, "PR #42: fixed auth bug http://example.com/test:123")
        self.assertEqual(filters, {})

    def test_parse_query_case_insensitive_keys(self):
        text, filters = parse_query("STATUS:open TYPE:bug PRIORITY:0")
        self.assertEqual(text, "")
        self.assertEqual(filters["status"], ["open"])
        self.assertEqual(filters["type"], ["bug"])
        self.assertEqual(filters["priority"], ["0"])

    def test_fts_escape(self):
        self.assertEqual(fts_escape("OAuth2 JWT #100"), '"OAuth2" OR "JWT" OR "#100"')
        self.assertEqual(fts_escape(""), "")
        self.assertEqual(fts_escape("!@$%^&*()"), "")

    def test_status_rank(self):
        self.assertEqual(status_rank("in_progress"), 0)
        self.assertEqual(status_rank("open"), 1)
        self.assertEqual(status_rank("deferred"), 2)
        self.assertEqual(status_rank(""), 3)
        self.assertEqual(status_rank("closed"), 4)
        self.assertEqual(status_rank("unknown"), 4)

    def test_search_bm25_and_status_ordering(self):
        # Searching 'OAuth' matches task-1 (closed) and task-2 (open). Open task-2 should rank ahead of task-1
        rows = search(self.con, "OAuth", {"type": ["task"]}, limit=10)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["id"], "task-2")  # open before closed
        self.assertEqual(rows[1]["id"], "task-1")

    def test_search_filter_status(self):
        rows_open = search(self.con, "OAuth", {"status": ["open"]}, limit=10)
        self.assertEqual(len(rows_open), 1)
        self.assertEqual(rows_open[0]["id"], "task-2")

        rows_all = search(self.con, "OAuth", {"status": ["all"]}, limit=10)
        self.assertEqual(len(rows_all), 3)  # epic-1, task-1, task-2

    def test_search_filter_priority_and_id(self):
        rows = search(self.con, "", {"priority": ["1"], "id": ["task"]}, limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "task-2")

    def test_search_filter_epic(self):
        rows = search(self.con, "", {"epic": ["epic-1"]}, limit=10)
        row_ids = [r["id"] for r in rows]
        self.assertIn("task-1", row_ids)
        self.assertIn("task-2", row_ids)
        self.assertIn("task-3", row_ids)
        self.assertNotIn("epic-1", row_ids)

    def test_search_empty_text_order_by_updated(self):
        rows = search(self.con, "", {}, limit=10)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["id"], "task-3")  # updated 2026-08-06

    def test_search_whitespace_only(self):
        rows = search(self.con, "   ", {}, limit=10)
        self.assertEqual(len(rows), 4)

    def test_neighborhood(self):
        hood = neighborhood(self.con, "task-2")
        # task-2 has parent epic-1, blocks task-1, is blocked by task-3, and mentions task-3
        self.assertIn("child of", hood)
        self.assertEqual(hood["child of"][0][0], "epic-1")
        self.assertIn("Authentication Epic", hood["child of"][0][1])

        self.assertIn("blocked by", hood)
        self.assertEqual(hood["blocked by"][0][0], "task-1")

        self.assertIn("blocks", hood)
        self.assertEqual(hood["blocks"][0][0], "task-3")

        self.assertIn("mentions", hood)
        self.assertEqual(hood["mentions"][0][0], "task-3")

    def test_neighborhood_labels(self):
        hood_t3 = neighborhood(self.con, "task-3")
        self.assertIn("child of", hood_t3)
        self.assertIn("discovered from", hood_t3)
        self.assertIn("supersedes", hood_t3)
        self.assertIn("related", hood_t3)
        self.assertIn("mentioned by", hood_t3)

        hood_epic = neighborhood(self.con, "epic-1")
        self.assertIn("children", hood_epic)
        self.assertIn("github refs", hood_epic)
        self.assertEqual(hood_epic["github refs"][0], ("#100", ""))

    def test_blast_data(self):
        # task-3 --blocks--> task-2 --blocks--> task-1
        data_t1 = blast_data(self.con, "task-1")
        self.assertEqual(data_t1["root"]["id"], "task-1")
        self.assertEqual(data_t1["blocked_by_transitively"], [])
        self.assertEqual(data_t1["blocks_transitively"], ["task-2", "task-3"])
        self.assertEqual(data_t1["epic_ancestry"], ["epic-1"])

        data_t3 = blast_data(self.con, "task-3")
        self.assertEqual(data_t3["root"]["id"], "task-3")
        self.assertEqual(data_t3["blocked_by_transitively"], ["task-2", "task-1"])
        self.assertEqual(data_t3["blocks_transitively"], [])
        self.assertEqual(data_t3["epic_ancestry"], ["epic-1"])

    def test_blast_data_not_found(self):
        with self.assertRaises(ValueError):
            blast_data(self.con, "nonexistent-id")

    def test_render_header(self):
        row_epic = self.con.execute("SELECT * FROM docs WHERE id='epic-1'").fetchone()
        h_epic = render_header(row_epic)
        self.assertIn("═══ epic-1 [IN_PROGRESS · P1 · epic · updated 2026-08-01]", h_epic)
        self.assertIn("Authentication Epic", h_epic)

        row_t1 = self.con.execute("SELECT * FROM docs WHERE id='task-1'").fetchone()
        h_t1 = render_header(row_t1)
        self.assertIn("═══ task-1 [CLOSED · P2 · task · updated 2026-08-03, closed 2026-08-03]", h_t1)

        mem_row = {
            "id": "mem:arch",
            "kind": "memory",
            "title": "arch",
            "status": "",
            "itype": "memory",
            "priority": None,
            "updated": "",
            "closed": "",
            "body": "Memory text",
        }
        h_mem = render_header(mem_row)
        self.assertEqual(h_mem, "═══ mem:arch [MEMORY]")

    def test_format_output_empty(self):
        out = format_output(self.con, [], budget=1000)
        self.assertEqual(out, "no matches — try fewer terms, or status:all")

    def test_format_output_truncation(self):
        long_issue = {
            "id": "task-long",
            "title": "Long Issue",
            "status": "open",
            "issue_type": "task",
            "priority": 1,
            "created_at": "2026-08-01",
            "updated_at": "2026-08-01",
            "description": "X" * 3000,
        }
        with open(self.store_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(long_issue) + "\n")
        con = build_index(self.store_file, self.db_path)
        rows = search(con, "", {"id": ["task-long"]}, limit=1)
        out = format_output(con, rows, budget=1200)
        self.assertIn("… [truncated — full body: bd show task-long]", out)
        con.close()

    def test_format_blast(self):
        data = blast_data(self.con, "task-1")
        out = format_blast(self.con, data)
        self.assertIn("═══ task-1 [CLOSED · P2 · task", out)
        self.assertIn("this bead is blocked by (transitively): none", out)
        self.assertIn("beads this blocks (transitively): 2", out)
        self.assertIn("task-2  JWT Token Refresh [open]", out)
        self.assertIn("task-3  Session Invalidation [deferred]", out)
        self.assertIn("epic ancestry: 1", out)
        self.assertIn("epic-1  Authentication Epic [in_progress]", out)


    def test_search_filter_priority_formats(self):
        rows = search(self.con, "", {"priority": ["P1"]}, limit=10)
        self.assertEqual(len(rows), 2)  # epic-1 and task-2
        # Non-numeric should not crash
        rows_invalid = search(self.con, "", {"priority": ["invalid", "p2"]}, limit=10)
        self.assertEqual(len(rows_invalid), 1)  # task-1

    def test_blast_data_prefers_exact_match(self):
        extra_issue = {
            "id": "task-10",
            "title": "Sub task 10",
            "status": "open",
            "issue_type": "task",
            "priority": 1,
            "created_at": "2026-08-01",
            "updated_at": "2026-08-01",
            "description": "Extra task",
        }
        with open(self.store_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(extra_issue) + "\n")
        con = build_index(self.store_file, self.db_path)
        data = blast_data(con, "task-1")
        self.assertEqual(data["root"]["id"], "task-1")
        con.close()

    def test_render_header_none_status(self):
        doc = {
            "id": "task-none",
            "kind": "issue",
            "title": "None Status Task",
            "status": None,
            "itype": "task",
            "priority": 1,
            "updated": "2026-08-01",
            "closed": None,
            "body": "Body",
        }
        h = render_header(doc)
        self.assertIn("═══ task-none [ · P1 · task", h)

    def test_escape_like(self):
        self.assertEqual(escape_like("simple"), "simple")
        self.assertEqual(escape_like("100%_done\\path"), "100\\%\\_done\\\\path")

    def test_format_output_hard_budget_cap(self):
        # Multiple matching rows with a small total budget should cap and report omitted
        rows = search(self.con, "", {}, limit=10)
        out = format_output(self.con, rows, budget=400)
        self.assertLessEqual(len(out), 600)
        self.assertIn("output capped at 400 chars", out)

    def test_format_blast_budget_cap(self):
        data = blast_data(self.con, "task-1")
        out = format_blast(self.con, data, budget=50)
        self.assertIn("blast output capped at 50 chars", out)


if __name__ == "__main__":
    unittest.main()

