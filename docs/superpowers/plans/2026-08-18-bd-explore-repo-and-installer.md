# bd-explore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package `bd-explore` as a production-ready Python repository with built-in stdio MCP server, multi-target agent installer (Claude, Gemini, Antigravity, Codex, Cursor), marker-fenced instructions injection, and Beads memory injection.

**Architecture:** Python standard library (3.10+ stdlib only, zero 3rd-party dependencies). Clean separation across `index.py` (SQLite FTS5 + edge mining), `search.py` (BM25 + graph traversal), `mcp.py` (stdio JSON-RPC MCP server), `installer/` (agent targets + beads remember), and `cli.py` (CLI routing).

**Tech Stack:** Python 3.10+, SQLite FTS5, JSON-RPC 2.0 / Model Context Protocol (MCP), standard `pyproject.toml` packaging.

---

### Task 1: Package Structure, Constants & Indexing Engine

**Files:**
- Create: `src/bd_explore/__init__.py`
- Create: `src/bd_explore/constants.py`
- Create: `src/bd_explore/index.py`
- Test: `tests/__init__.py`
- Test: `tests/test_index.py`

- [ ] **Step 1: Write test for indexing, mention mining, and store discovery**

Create `tests/test_index.py`:
```python
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bd_explore.index import (
    build_index,
    cache_db_path,
    compose_body,
    find_store,
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
                "title": "Epic Root Issue",
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

    def test_find_store_explicit(self):
        found = find_store(str(self.store_file))
        self.assertEqual(found.resolve(), self.store_file.resolve())

    def test_find_store_from_dir(self):
        found = find_store(str(self.root))
        self.assertEqual(found.resolve(), self.store_file.resolve())

    def test_compose_body(self):
        body = compose_body(self.sample_issues[1])
        self.assertIn("Validate claims and tokens", body)
        self.assertIn("DESIGN:\nUse RSA256", body)
        self.assertIn("ACCEPTANCE:\nPass all crypto", body)
        self.assertIn("NOTES:\nHandoff: bd-102", body)
        self.assertIn("COMMENT (alice 2026-08-03):\nTested on staging", body)
        self.assertIn("CLOSE REASON:\nMerged in PR #43", body)

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

        # Check GH ref edges
        gh_refs = con.execute("SELECT src, dst, kind FROM edges WHERE kind='gh-ref'").fetchall()
        self.assertIn(("bd-101", "#42", "gh-ref"), gh_refs)
        self.assertIn(("bd-101", "#43", "gh-ref"), gh_refs)

        # Check dependency edges
        dep_edges = con.execute("SELECT src, dst, kind FROM edges WHERE kind='parent-child'").fetchall()
        self.assertEqual(dep_edges, [("bd-101", "bd-100", "parent-child")])

        con.close()

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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_index.py`  
Expected: ModuleNotFoundError: No module named 'bd_explore'

- [ ] **Step 3: Implement `constants.py`, `__init__.py`, and `index.py`**

Create `src/bd_explore/__init__.py`:
```python
"""bd-explore: Ask a beads store questions, codegraph-style."""

from bd_explore.constants import VERSION

__version__ = VERSION
__all__ = ["__version__"]
```

Create `src/bd_explore/constants.py`:
```python
"""Constants and defaults for bd-explore."""

VERSION = "0.1.0"

DEFAULT_BUDGET_CHARS = 24_000
DEFAULT_SEEDS = 5

DEP_KINDS = {
    "parent-child",
    "discovered-from",
    "blocks",
    "blocked-by",
    "related",
    "relates-to",
    "supersedes",
}

FILTER_KEYS = {"status", "type", "priority", "epic", "id"}
```

Create `src/bd_explore/index.py`:
```python
"""Indexing engine: parse .beads/issues.jsonl and load memories into SQLite FTS5."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

from bd_explore.constants import DEP_KINDS

SCHEMA = """
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE docs (
  id TEXT PRIMARY KEY, kind TEXT, title TEXT, status TEXT, itype TEXT,
  priority INTEGER, created TEXT, updated TEXT, closed TEXT, body TEXT
);
CREATE TABLE edges (src TEXT, dst TEXT, kind TEXT, PRIMARY KEY (src, dst, kind));
CREATE INDEX edges_dst ON edges (dst);
CREATE VIRTUAL TABLE docs_fts USING fts5(id, title, body, tokenize='porter unicode61');
"""


def find_store(explicit: str | None = None) -> Path:
    """Resolve the issues.jsonl export: --store flag, BD_EXPLORE_STORE env, or
    walk up from cwd looking for .beads/issues.jsonl."""
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_dir():
            p = p / "issues.jsonl" if (p / "issues.jsonl").exists() else p / ".beads" / "issues.jsonl"
        if not p.exists():
            raise FileNotFoundError(f"bd-explore: store export not found: {p}")
        return p
    env = os.environ.get("BD_EXPLORE_STORE")
    if env:
        return find_store(env)
    cur = Path.cwd()
    for d in [cur, *cur.parents]:
        cand = d / ".beads" / "issues.jsonl"
        if cand.exists():
            return cand
    raise FileNotFoundError(
        "bd-explore: no .beads/issues.jsonl found from cwd upward. "
        "Run inside a beads repo, or pass --store / set BD_EXPLORE_STORE. "
        "(The export requires the store's export.auto: true.)"
    )


def cache_db_path(store: Path) -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "bd-explore"
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(str(store.resolve()).encode()).hexdigest()[:16]
    return root / f"{key}.db"


def compose_body(rec: dict) -> str:
    """The verbatim searchable text of one bead: every prose field it carries."""
    parts: list[str] = []
    if rec.get("description"):
        parts.append(rec["description"])
    if rec.get("design"):
        parts.append("DESIGN:\n" + rec["design"])
    if rec.get("acceptance_criteria"):
        parts.append("ACCEPTANCE:\n" + rec["acceptance_criteria"])
    if rec.get("notes"):
        parts.append("NOTES:\n" + rec["notes"])
    for c in rec.get("comments") or []:
        stamp = (c.get("created_at") or "")[:10]
        parts.append(f"COMMENT ({c.get('author', '?')} {stamp}):\n{c.get('text', '')}")
    if rec.get("close_reason"):
        parts.append("CLOSE REASON:\n" + rec["close_reason"])
    return "\n\n".join(parts)


def load_memories() -> list[dict]:
    """Memories aren't in the jsonl export; pull them via the bd CLI when present.
    Degrades to empty — the index still covers all issues."""
    try:
        out = subprocess.run(
            ["bd", "memories", "--json"], capture_output=True, text=True, timeout=30
        )
        if out.returncode != 0:
            return []
        data = json.loads(out.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        return [{"key": k, "content": v if isinstance(v, str) else json.dumps(v)} for k, v in data.items()]
    if isinstance(data, list):
        return [
            {"key": m.get("key", f"mem{i}"), "content": m.get("content", "")}
            for i, m in enumerate(data)
            if isinstance(m, dict)
        ]
    return []


def build_index(store: Path, db_path: Path) -> sqlite3.Connection:
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)

    records: list[dict] = []
    with open(store, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    ids = {r["id"] for r in records}
    id_alt = "|".join(re.escape(i) for i in sorted(ids, key=len, reverse=True))
    mention_re = re.compile(rf"\b({id_alt})\b") if ids else None
    gh_re = re.compile(r"(?:GH |GitHub )?(?:issue |PR )?#(\d{2,5})\b")

    docs, edges = [], set()
    for r in records:
        body = compose_body(r)
        docs.append(
            (
                r["id"], "issue", r.get("title", ""), r.get("status", ""),
                r.get("issue_type", ""), r.get("priority"),
                (r.get("created_at") or "")[:10], (r.get("updated_at") or "")[:10],
                (r.get("closed_at") or "")[:10], body,
            )
        )
        for d in r.get("dependencies") or []:
            kind = d.get("type", "related")
            if kind in DEP_KINDS:
                edges.add((d.get("issue_id", r["id"]), d.get("depends_on_id", ""), kind))
        if mention_re:
            searchable = f"{r.get('title', '')}\n{body}"
            for m in set(mention_re.findall(searchable)):
                if m != r["id"]:
                    edges.add((r["id"], m, "mentions"))
        for gh in set(gh_re.findall(body)):
            edges.add((r["id"], f"#{gh}", "gh-ref"))

    for m in load_memories():
        docs.append(
            (f"mem:{m['key']}", "memory", m["key"], "", "memory", None, "", "", "", m["content"])
        )
        if mention_re:
            for hit in set(mention_re.findall(m["content"])):
                edges.add((f"mem:{m['key']}", hit, "mentions"))

    con.executemany("INSERT OR REPLACE INTO docs VALUES (?,?,?,?,?,?,?,?,?,?)", docs)
    con.executemany("INSERT OR IGNORE INTO edges VALUES (?,?,?)", edges)
    con.executemany(
        "INSERT INTO docs_fts (id, title, body) VALUES (?,?,?)",
        [(d[0], d[2], d[9]) for d in docs],
    )
    st = store.stat()
    con.executemany(
        "INSERT INTO meta VALUES (?,?)",
        [("mtime", str(st.st_mtime_ns)), ("size", str(st.st_size))],
    )
    con.commit()
    return con


def open_index(store: Path, force: bool = False) -> sqlite3.Connection:
    db_path = cache_db_path(store)
    if not force and db_path.exists():
        try:
            con = sqlite3.connect(db_path)
            meta = dict(con.execute("SELECT k, v FROM meta"))
            st = store.stat()
            if meta.get("mtime") == str(st.st_mtime_ns) and meta.get("size") == str(st.st_size):
                return con
            con.close()
        except sqlite3.DatabaseError:
            pass
    return build_index(store, db_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python3 -m unittest tests/test_index.py`  
Expected: OK (all tests pass)

- [ ] **Step 5: Commit**

```bash
git add src/bd_explore/__init__.py src/bd_explore/constants.py src/bd_explore/index.py tests/__init__.py tests/test_index.py
git commit -m "feat(index): implement store discovery, FTS5 schema, and indexing engine"
```

---

### Task 2: Search Engine, BM25 Ranking, Graph & Blast Radius

**Files:**
- Create: `src/bd_explore/search.py`
- Test: `tests/test_search.py`

- [ ] **Step 1: Write tests for query parsing, filtering, ranking, blast radius, and rendering**

Create `tests/test_search.py`:
```python
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bd_explore.index import build_index
from bd_explore.search import (
    blast_data,
    format_output,
    neighborhood,
    parse_query,
    render_header,
    search,
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
                "description": "Auth overhaul with OAuth2",
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
                "description": "Rotate refresh tokens safely OAuth style",
                "dependencies": [
                    {"issue_id": "task-2", "depends_on_id": "task-1", "type": "blocks"},
                    {"issue_id": "task-2", "depends_on_id": "epic-1", "type": "parent-child"}
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

    def test_parse_query(self):
        text, filters = parse_query("OAuth refresh status:open,in_progress type:task priority:1 epic:epic-1")
        self.assertEqual(text, "OAuth refresh")
        self.assertEqual(filters["status"], ["open", "in_progress"])
        self.assertEqual(filters["type"], ["task"])
        self.assertEqual(filters["priority"], ["1"])
        self.assertEqual(filters["epic"], ["epic-1"])

    def test_search_bm25_and_filters(self):
        # Searching 'OAuth' matches task-1 and task-2. Open task-2 should rank ahead of closed task-1
        rows = search(self.con, "OAuth", {"type": ["task"]}, limit=10)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["id"], "task-2")  # open before closed
        self.assertEqual(rows[1]["id"], "task-1")

    def test_neighborhood(self):
        hood = neighborhood(self.con, "task-2")
        # task-2 has parent epic-1, and blocks task-1
        self.assertIn("child of", hood)
        self.assertEqual(hood["child of"][0][0], "epic-1")

    def test_blast_data(self):
        data = blast_data(self.con, "task-1")
        self.assertEqual(data["root"]["id"], "task-1")
        self.assertIn("task-2", data["blocked_by_transitively"])
        self.assertEqual(data["epic_ancestry"], ["epic-1"])

    def test_format_output(self):
        rows = search(self.con, "JWT", {}, limit=5)
        out = format_output(self.con, rows, budget=10000)
        self.assertIn("task-2 [OPEN · P1 · task", out)
        self.assertIn("Rotate refresh tokens", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests/test_search.py`  
Expected: ModuleNotFoundError: No module named 'bd_explore.search'

- [ ] **Step 3: Implement `src/bd_explore/search.py`**

Create `src/bd_explore/search.py`:
```python
"""Search and graph exploration engine."""

from __future__ import annotations

import re
import sqlite3
import textwrap
from typing import Any

from bd_explore.constants import FILTER_KEYS


def parse_query(raw: str) -> tuple[str, dict[str, list[str]]]:
    """codegraph-style field-qualified parsing: `status:open type:bug free text`.
    Unknown prefixes fall through to free text (searching for `PR #NNN:` must work)."""
    filters: dict[str, list[str]] = {}
    text_parts: list[str] = []
    for tok in raw.split():
        if ":" in tok:
            key, _, val = tok.partition(":")
            key_lower = key.lower()
            if key_lower in FILTER_KEYS and val:
                vals = [v.strip() for v in val.split(",") if v.strip()]
                filters.setdefault(key_lower, []).extend(vals)
                continue
        text_parts.append(tok)
    return " ".join(text_parts), filters


def fts_escape(text: str) -> str:
    """Quote every term — user text is a question, not FTS syntax."""
    terms = [t for t in re.findall(r"[\w./#-]+", text) if t]
    return " OR ".join(f'"{t}"' for t in terms)


def status_rank(status: str) -> int:
    return {"in_progress": 0, "open": 1, "deferred": 2, "": 3}.get(status, 4)  # closed last


def search(con: sqlite3.Connection, text: str, filters: dict[str, list[str]], limit: int) -> list[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    where, params = [], []
    statuses = filters.get("status", [])
    if statuses and "all" not in statuses:
        where.append(f"d.status IN ({','.join('?' * len(statuses))})")
        params.extend(statuses)
    if filters.get("type"):
        where.append(f"d.itype IN ({','.join('?' * len(filters['type']))})")
        params.extend(filters["type"])
    if filters.get("priority"):
        where.append(f"d.priority IN ({','.join('?' * len(filters['priority']))})")
        params.extend(int(p) for p in filters["priority"])
    if filters.get("id"):
        where.append("(" + " OR ".join("d.id LIKE ?" for _ in filters["id"]) + ")")
        params.extend(f"%{i}%" for i in filters["id"])
    if filters.get("epic"):
        clauses = []
        for e in filters["epic"]:
            clauses.append(
                "d.id IN (SELECT src FROM edges WHERE kind='parent-child' AND dst LIKE ?)"
            )
            params.append(f"%{e}%")
        where.append("(" + " OR ".join(clauses) + ")")

    if text.strip():
        match = fts_escape(text)
        sql = f"""
          SELECT d.*, bm25(docs_fts) AS score FROM docs_fts f
          JOIN docs d ON d.id = f.id
          WHERE docs_fts MATCH ? {"AND " + " AND ".join(where) if where else ""}
          ORDER BY score LIMIT ?"""
        rows = con.execute(sql, [match, *params, limit * 4]).fetchall()
        # bm25 within a band, open/in_progress before closed across bands.
        rows.sort(key=lambda r: (round(r["score"], 1), status_rank(r["status"])))
        return rows[:limit]
    sql = f"""SELECT d.*, 0.0 AS score FROM docs d
              {"WHERE " + " AND ".join(where) if where else ""}
              ORDER BY d.updated DESC LIMIT ?"""
    return con.execute(sql, [*params, limit]).fetchall()


def neighborhood(con: sqlite3.Connection, bead_id: str) -> dict[str, list[tuple[str, str]]]:
    """1-hop, both directions, grouped for display. Values are (id, title)."""
    con.row_factory = sqlite3.Row
    out: dict[str, list[tuple[str, str]]] = {}

    def title_of(i: str) -> str:
        row = con.execute("SELECT title, status FROM docs WHERE id=?", (i,)).fetchone()
        return f"{row['title']} [{row['status']}]" if row else "(external)"

    labels = {
        ("parent-child", "out"): "child of",
        ("parent-child", "in"): "children",
        ("blocks", "out"): "blocked by",
        ("blocks", "in"): "blocks",
        ("blocked-by", "out"): "blocks",
        ("blocked-by", "in"): "blocked by",
        ("discovered-from", "out"): "discovered from",
        ("discovered-from", "in"): "discoveries from this",
        ("supersedes", "out"): "supersedes",
        ("supersedes", "in"): "superseded by",
        ("mentions", "out"): "mentions",
        ("mentions", "in"): "mentioned by",
        ("gh-ref", "out"): "github refs",
        ("related", "out"): "related",
        ("related", "in"): "related",
        ("relates-to", "out"): "related",
        ("relates-to", "in"): "related",
    }
    for src, dst, kind in con.execute(
        "SELECT src, dst, kind FROM edges WHERE src=? OR dst=?", (bead_id, bead_id)
    ):
        direction = "out" if src == bead_id else "in"
        other = dst if direction == "out" else src
        label = labels.get((kind, direction), kind)
        out.setdefault(label, []).append((other, title_of(other) if kind != "gh-ref" else ""))
    return out


def blast_data(con: sqlite3.Connection, bead_id: str) -> dict[str, Any]:
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM docs WHERE id LIKE ?", (f"%{bead_id}%",)).fetchone()
    if not row:
        raise ValueError(f"bd-explore: no bead matching '{bead_id}'")

    def walk(start: str, forward: bool) -> list[str]:
        seen, frontier, order = {start}, [start], []
        while frontier:
            cur = frontier.pop()
            q = (
                "SELECT dst AS n FROM edges WHERE src=? AND kind='blocks'"
                if forward
                else "SELECT src AS n FROM edges WHERE dst=? AND kind='blocks'"
            )
            for (n,) in con.execute(q, (cur,)):
                if n not in seen:
                    seen.add(n)
                    order.append(n)
                    frontier.append(n)
        return order

    ancestry, cur = [], row["id"]
    while True:
        parent = con.execute(
            "SELECT dst FROM edges WHERE src=? AND kind='parent-child'", (cur,)
        ).fetchone()
        if not parent or parent[0] in ancestry:
            break
        ancestry.append(parent[0])
        cur = parent[0]

    return {
        "root": row,
        "blocked_by_transitively": walk(row["id"], True),
        "blocks_transitively": walk(row["id"], False),
        "epic_ancestry": ancestry,
    }


def render_header(r: sqlite3.Row) -> str:
    if r["kind"] == "memory":
        return f"═══ {r['id']} [MEMORY]"
    prio = f"P{r['priority']}" if r["priority"] is not None else "P?"
    stamp = f"updated {r['updated']}" + (f", closed {r['closed']}" if r["closed"] else "")
    return f"═══ {r['id']} [{r['status'].upper()} · {prio} · {r['itype']} · {stamp}]\n    {r['title']}"


def format_output(con: sqlite3.Connection, rows: list[sqlite3.Row], budget: int) -> str:
    if not rows:
        return "no matches — try fewer terms, or status:all"
    parts: list[str] = []
    per_doc = max(budget // len(rows), 1200)
    for r in rows:
        parts.append(render_header(r))
        body = r["body"] or "(no body)"
        if len(body) > per_doc:
            body = body[:per_doc] + f"\n… [truncated — full body: bd show {r['id']}]"
        parts.append(textwrap.indent(body, "    "))
        hood = neighborhood(con, r["id"])
        if hood:
            parts.append("    ── neighborhood ──")
            for label, items in sorted(hood.items()):
                shown = items[:6]
                extra = f" (+{len(items) - 6} more)" if len(items) > 6 else ""
                names = ", ".join(
                    f"{i}" + (f" — {t}" if t else "") for i, t in shown
                )
                parts.append(f"    {label}: {names}{extra}")
        parts.append("")
    return "\n".join(parts)


def format_blast(con: sqlite3.Connection, data: dict[str, Any]) -> str:
    lines = [render_header(data["root"])]

    def show(label: str, items: list[str]) -> None:
        lines.append(f"\n{label}: {len(items) or 'none'}")
        for i in items:
            r = con.execute("SELECT title, status FROM docs WHERE id=?", (i,)).fetchone()
            lines.append(f"  {i}  {r['title'] if r else ''} [{r['status'] if r else '?'}]")

    show("this bead is blocked by (transitively)", data["blocked_by_transitively"])
    show("beads this blocks (transitively)", data["blocks_transitively"])
    show("epic ancestry", data["epic_ancestry"])
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python3 -m unittest tests/test_search.py`  
Expected: OK (all tests pass)

- [ ] **Step 5: Commit**

```bash
git add src/bd_explore/search.py tests/test_search.py
git commit -m "feat(search): implement BM25 search, field filtering, and blast radius formatting"
```

---

### Task 3: Built-in Stdio MCP Server

**Files:**
- Create: `src/bd_explore/mcp.py`
- Test: `tests/test_mcp.py`

- [ ] **Step 1: Write test for MCP JSON-RPC protocol handling and tool execution**

Create `tests/test_mcp.py`:
```python
import io
import json
import tempfile
import unittest
from pathlib import Path

from bd_explore.index import build_index
from bd_explore.mcp import McpServer


class TestMcpServer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.beads_dir = self.root / ".beads"
        self.beads_dir.mkdir(parents=True)
        self.store_file = self.beads_dir / "issues.jsonl"
        self.db_path = self.root / "cache.db"

        sample_issue = {
            "id": "bd-1",
            "title": "Auth redesign",
            "status": "open",
            "issue_type": "task",
            "priority": 1,
            "description": "Switch from session cookies to JWT auth tokens",
        }
        with open(self.store_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(sample_issue) + "\n")

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_rpc(self, server: McpServer, request: dict) -> dict:
        req_bytes = json.dumps(request).encode("utf-8")
        in_stream = io.BytesIO(req_bytes + b"\n")
        out_stream = io.BytesIO()

        server.handle_stream(in_stream, out_stream)
        out_stream.seek(0)
        lines = [line.strip() for line in out_stream.readlines() if line.strip()]
        self.assertTrue(len(lines) >= 1)
        return json.loads(lines[0])

    def test_initialize_and_ping(self):
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
        self.assertEqual(init_resp["result"]["serverInfo"]["name"], "bd-explore")
        self.assertIn("tools", init_resp["result"]["capabilities"])

        ping_resp = self.run_rpc(server, {"jsonrpc": "2.0", "id": 2, "method": "ping"})
        self.assertEqual(ping_resp["id"], 2)
        self.assertEqual(ping_resp["result"], {})

    def test_tools_list(self):
        server = McpServer(default_store=self.store_file)
        resp = self.run_rpc(server, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        tools = resp["result"]["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "bd_explore")
        self.assertIn("query", tools[0]["inputSchema"]["properties"])

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
        self.assertIn("bd-1 [OPEN · P1 · task", content[0]["text"])
        self.assertIn("Switch from session cookies", content[0]["text"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests/test_mcp.py`  
Expected: ModuleNotFoundError: No module named 'bd_explore.mcp'

- [ ] **Step 3: Implement `src/bd_explore/mcp.py`**

Create `src/bd_explore/mcp.py`:
```python
"""Built-in stdio JSON-RPC 2.0 MCP (Model Context Protocol) server."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import BinaryIO, TextIO

from bd_explore.constants import DEFAULT_BUDGET_CHARS, DEFAULT_SEEDS, VERSION
from bd_explore.index import find_store, open_index
from bd_explore.search import blast_data, format_blast, format_output, parse_query, search

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
    def __init__(self, default_store: Path | None = None) -> None:
        self.default_store = default_store

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
            result_text = self._execute_explore(args)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": result_text}],
                },
            }

        if msg_id is not None:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        return None

    def _execute_explore(self, args: dict) -> str:
        store_arg = args.get("store")
        try:
            store_path = find_store(store_arg) if store_arg else (self.default_store or find_store())
            con = open_index(store_path)
        except Exception as e:
            return f"bd-explore error: {e}"

        blast_id = args.get("blast")
        if blast_id:
            try:
                data = blast_data(con, blast_id)
                return format_blast(con, data)
            except Exception as e:
                return f"bd-explore blast error: {e}"

        query_str = args.get("query") or ""
        limit = int(args.get("limit") or DEFAULT_SEEDS)
        budget = int(args.get("budget") or DEFAULT_BUDGET_CHARS)

        text, filters = parse_query(query_str)
        rows = search(con, text, filters, limit)
        return format_output(con, rows, budget)

    def handle_stream(self, in_stream: BinaryIO, out_stream: BinaryIO) -> None:
        for line in in_stream:
            line_str = line.decode("utf-8").strip()
            if not line_str:
                continue
            try:
                req = json.loads(line_str)
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


def run_mcp_server(default_store: Path | None = None) -> None:
    server = McpServer(default_store=default_store)
    server.handle_stream(sys.stdin.buffer, sys.stdout.buffer)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python3 -m unittest tests/test_mcp.py`  
Expected: OK (all tests pass)

- [ ] **Step 5: Commit**

```bash
git add src/bd_explore/mcp.py tests/test_mcp.py
git commit -m "feat(mcp): implement stdio JSON-RPC MCP server exposing bd_explore tool"
```

---

### Task 4: Multi-Target Installer, Instructions & Memory Injection

**Files:**
- Create: `src/bd_explore/installer/__init__.py`
- Create: `src/bd_explore/installer/shared.py`
- Create: `src/bd_explore/installer/instructions.py`
- Create: `src/bd_explore/installer/memory.py`
- Create: `src/bd_explore/installer/targets/__init__.py`
- Create: `src/bd_explore/installer/targets/claude.py`
- Create: `src/bd_explore/installer/targets/gemini.py`
- Create: `src/bd_explore/installer/targets/antigravity.py`
- Create: `src/bd_explore/installer/targets/codex.py`
- Create: `src/bd_explore/installer/targets/cursor.py`
- Create: `src/bd_explore/installer/targets/agents_md.py`
- Test: `tests/test_installer.py`

- [ ] **Step 1: Write tests for installer helpers, marker idempotency, targets, and memory injection**

Create `tests/test_installer.py`:
```python
import json
import os
import tempfile
import unittest
from pathlib import Path

from bd_explore.installer.instructions import (
    BD_EXPLORE_SECTION_END,
    BD_EXPLORE_SECTION_START,
    remove_marked_section,
    replace_or_append_marked_section,
    upsert_instructions_entry,
)
from bd_explore.installer.memory import get_memory_content, inject_beads_memory, remove_beads_memory
from bd_explore.installer.shared import atomic_write_file, read_json_file, write_json_file
from bd_explore.installer.targets.antigravity import AntigravityTarget
from bd_explore.installer.targets.claude import ClaudeTarget
from bd_explore.installer.targets.codex import CodexTarget
from bd_explore.installer.targets.gemini import GeminiTarget


class TestInstaller(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_atomic_write_and_read_json(self):
        f = self.root / "config.json"
        data = {"mcpServers": {"test": {"command": "echo"}}}
        write_json_file(f, data)
        self.assertTrue(f.exists())
        read_back = read_json_file(f)
        self.assertEqual(read_back, data)

    def test_marker_section_replacement_and_removal(self):
        md = self.root / "CLAUDE.md"
        md.write_text("# Project Notes\n\nExisting user instructions.\n", encoding="utf-8")

        # First upsert: appends block
        res1 = upsert_instructions_entry(md)
        self.assertEqual(res1["action"], "updated")
        content1 = md.read_text(encoding="utf-8")
        self.assertIn(BD_EXPLORE_SECTION_START, content1)
        self.assertIn("Existing user instructions.", content1)

        # Second upsert: unchanged (idempotent)
        res2 = upsert_instructions_entry(md)
        self.assertEqual(res2["action"], "unchanged")

        # Removal
        act = remove_marked_section(md, BD_EXPLORE_SECTION_START, BD_EXPLORE_SECTION_END)
        self.assertEqual(act, "removed")
        content_after = md.read_text(encoding="utf-8")
        self.assertNotIn(BD_EXPLORE_SECTION_START, content_after)
        self.assertIn("Existing user instructions.", content_after)

    def test_claude_target_install_and_uninstall(self):
        target = ClaudeTarget(home_dir=self.root, project_dir=self.root)
        install_res = target.install(location="global")
        self.assertTrue(any(f["action"] in ("created", "updated") for f in install_res["files"]))

        # Verify ~/.claude.json has bd-explore
        claude_json = self.root / ".claude.json"
        self.assertTrue(claude_json.exists())
        cfg = read_json_file(claude_json)
        self.assertIn("bd-explore", cfg["mcpServers"])

        # Uninstall
        un_res = target.uninstall(location="global")
        cfg_after = read_json_file(claude_json)
        self.assertNotIn("bd-explore", cfg_after.get("mcpServers", {}))

    def test_gemini_and_antigravity_targets(self):
        gem = GeminiTarget(home_dir=self.root, project_dir=self.root)
        gem_res = gem.install(location="global")
        settings_file = self.root / ".gemini" / "settings.json"
        self.assertTrue(settings_file.exists())
        self.assertIn("bd-explore", read_json_file(settings_file)["mcpServers"])

        ag = AntigravityTarget(home_dir=self.root, project_dir=self.root)
        ag_res = ag.install(location="global")
        ag_mcp = self.root / ".gemini" / "config" / "mcp_config.json"
        self.assertTrue(ag_mcp.exists())
        # Check no 'type': 'stdio' in Antigravity config
        ag_entry = read_json_file(ag_mcp)["mcpServers"]["bd-explore"]
        self.assertNotIn("type", ag_entry)

    def test_codex_toml_target(self):
        codex = CodexTarget(home_dir=self.root, project_dir=self.root)
        codex.install(location="global")
        toml_file = self.root / ".codex" / "config.toml"
        self.assertTrue(toml_file.exists())
        toml_content = toml_file.read_text(encoding="utf-8")
        self.assertIn("[mcp_servers.bd-explore]", toml_content)

        codex.uninstall(location="global")
        if toml_file.exists():
            self.assertNotIn("[mcp_servers.bd-explore]", toml_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests/test_installer.py`  
Expected: ModuleNotFoundError: No module named 'bd_explore.installer'

- [ ] **Step 3: Implement installer modules**

Create `src/bd_explore/installer/shared.py`:
```python
"""Shared file manipulation and atomic I/O helpers for installer targets."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any


def atomic_write_file(file_path: Path, content: str) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(f"{file_path.name}.tmp.{os.getpid()}")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        tmp_path.replace(file_path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def read_json_file(file_path: Path) -> dict[str, Any]:
    if not file_path.exists():
        return {}
    try:
        with open(file_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        try:
            shutil.copyfile(file_path, file_path.with_suffix(".backup"))
        except OSError:
            pass
        return {}


def write_json_file(file_path: Path, data: dict[str, Any]) -> None:
    atomic_write_file(file_path, json.dumps(data, indent=2) + "\n")
```

Create `src/bd_explore/installer/instructions.py`:
```python
"""Marker-fenced agent instructions injection."""

from __future__ import annotations

from pathlib import Path
from bd_explore.installer.shared import atomic_write_file

BD_EXPLORE_SECTION_START = "<!-- BD_EXPLORE_START -->"
BD_EXPLORE_SECTION_END = "<!-- BD_EXPLORE_END -->"

BD_EXPLORE_INSTRUCTIONS_BLOCK = f"""{BD_EXPLORE_SECTION_START}
## bd-explore

In repositories with a beads store (a `.beads/` directory exists at the repo root), reach for `bd-explore` BEFORE searching raw files or relying only on `bd search`:

- **MCP tool** (when available): `bd_explore` answers questions about beads/issues/decisions/memories verbatim — description, notes, comments, close reason, plus relationship neighborhood under an output budget.
- **Shell** (always works): `bd-explore "<query>"` (e.g. `bd-explore "why did we re-point SYRP status:open"`, `bd-explore --blast <id>`).

If there is no `.beads/` directory, skip bd-explore.
{BD_EXPLORE_SECTION_END}"""


def replace_or_append_marked_section(
    file_path: Path,
    body: str,
    start_marker: str,
    end_marker: str,
) -> str:
    """Returns 'created', 'updated', 'appended', or 'unchanged'."""
    if not file_path.exists():
        atomic_write_file(file_path, body + "\n")
        return "created"

    content = file_path.read_text(encoding="utf-8")
    start_idx = content.indexOf(start_marker) if hasattr(content, "indexOf") else content.find(start_marker)
    end_idx = content.find(end_marker)

    if start_idx != -1 and end_idx > start_idx:
        existing_block = content[start_idx : end_idx + len(end_marker)]
        if existing_block == body:
            return "unchanged"
        before = content[:start_idx]
        after = content[end_idx + len(end_marker) :]
        atomic_write_file(file_path, before + body + after)
        return "updated"

    trimmed = content.rstrip()
    sep = "\n\n" if trimmed else ""
    atomic_write_file(file_path, trimmed + sep + body + "\n")
    return "appended"


def upsert_instructions_entry(file_path: Path) -> dict[str, str]:
    action = replace_or_append_marked_section(
        file_path,
        BD_EXPLORE_INSTRUCTIONS_BLOCK,
        BD_EXPLORE_SECTION_START,
        BD_EXPLORE_SECTION_END,
    )
    return {"path": str(file_path), "action": "updated" if action == "appended" else action}


def remove_marked_section(file_path: Path, start_marker: str, end_marker: str) -> str:
    """Returns 'removed', 'not-found', or 'kept'."""
    if not file_path.exists():
        return "kept"
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        return "kept"

    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker)
    if start_idx == -1 or end_idx <= start_idx:
        return "not-found"

    before = content[:start_idx].rstrip()
    after = content[end_idx + len(end_marker) :].lstrip()
    joined = before + ("\n\n" if before and after else "") + after

    if not joined.strip():
        try:
            file_path.unlink()
        except OSError:
            pass
    else:
        atomic_write_file(file_path, joined.strip() + "\n")
    return "removed"
```

Create `src/bd_explore/installer/memory.py`:
```python
"""Beads persistent memory injector (bd remember / bd forget)."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

MEMORY_KEY = "bd-explore"
MEMORY_BODY = (
    "Use 'bd-explore <query>' or the 'bd_explore' MCP tool to query beads issues, "
    "notes, comments, close reasons, and relationship graphs."
)


def is_bd_available() -> bool:
    return shutil.which("bd") is not None


def get_memory_content() -> str:
    return MEMORY_BODY


def inject_beads_memory() -> dict[str, Any]:
    if not is_bd_available():
        return {"status": "skipped", "reason": "bd CLI not found on PATH"}
    try:
        res = subprocess.run(
            ["bd", "remember", MEMORY_BODY, "--key", MEMORY_KEY],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if res.returncode == 0:
            return {"status": "injected", "key": MEMORY_KEY}
        return {"status": "error", "message": res.stderr.strip()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def remove_beads_memory() -> dict[str, Any]:
    if not is_bd_available():
        return {"status": "skipped", "reason": "bd CLI not found on PATH"}
    try:
        res = subprocess.run(
            ["bd", "forget", MEMORY_KEY],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return {"status": "removed" if res.returncode == 0 else "not-found"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

Create target files:
- `src/bd_explore/installer/targets/__init__.py`
- `src/bd_explore/installer/targets/claude.py`
- `src/bd_explore/installer/targets/gemini.py`
- `src/bd_explore/installer/targets/antigravity.py`
- `src/bd_explore/installer/targets/codex.py`
- `src/bd_explore/installer/targets/cursor.py`
- `src/bd_explore/installer/targets/agents_md.py`
- `src/bd_explore/installer/__init__.py`

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python3 -m unittest tests/test_installer.py`  
Expected: OK (all tests pass)

- [ ] **Step 5: Commit**

```bash
git add src/bd_explore/installer/ tests/test_installer.py
git commit -m "feat(installer): implement multi-target agent installer, marker injection, and beads memory integration"
```

---

### Task 5: Main CLI Entrypoints & Interactive Installer

**Files:**
- Create: `src/bd_explore/cli.py`
- Create: `src/bd_explore/__main__.py`
- Remove legacy: `bd_explore.py` (or replace with compatibility redirect to `src/bd_explore/cli.py`)

- [ ] **Step 1: Implement `src/bd_explore/cli.py` and `__main__.py`**

Create `src/bd_explore/cli.py` with argument parsing for explore, blast, rebuild, serve --mcp, install, uninstall, print-config.

Create `src/bd_explore/__main__.py`:
```python
from bd_explore.cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify CLI commands work**

Run: `PYTHONPATH=src python3 -m bd_explore --help`  
Run: `PYTHONPATH=src python3 -m bd_explore print-config --target claude`  
Expected: Returns formatted help and MCP config snippets.

- [ ] **Step 3: Commit**

```bash
git add src/bd_explore/cli.py src/bd_explore/__main__.py bd_explore.py
git commit -m "feat(cli): wire main CLI subcommands and legacy entrypoint redirect"
```

---

### Task 6: Repository Packaging, Standalone Installer, CI & Agent Rules

**Files:**
- Create: `pyproject.toml`
- Create: `install.sh`
- Create: `.github/workflows/ci.yml`
- Create: `CLAUDE.md`
- Create: `AGENTS.md`
- Create: `GEMINI.md`
- Create: `LICENSE`
- Create: `.gitignore`
- Update: `README.md`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "bd-explore"
version = "0.1.0"
description = "Ask a beads store questions, codegraph-style"
readme = "README.md"
requires-python = ">=3.10"
license = { text = "MIT" }
authors = [{ name = "halaprix" }]
classifiers = [
    "Programming Language :: Python :: 3",
    "License :: OSI Approved :: MIT License",
    "Operating System :: OS Independent",
]

[project.scripts]
bd-explore = "bd_explore.cli:main"
bd_explore = "bd_explore.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Create `install.sh`**

Standalone curlable installer with PATH checking, binary link, and automated `bd-explore install --yes`.

- [ ] **Step 3: Create `.github/workflows/ci.yml`**

GitHub Actions CI running `python3 -m unittest discover tests` across Python 3.10, 3.11, 3.12, 3.13.

- [ ] **Step 4: Create `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `README.md`, `LICENSE`, `.gitignore`**

- [ ] **Step 5: Run full test suite**

Run: `PYTHONPATH=src python3 -m unittest discover tests`  
Expected: OK (all unit tests pass across index, search, mcp, installer)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml install.sh .github/ CLAUDE.md AGENTS.md GEMINI.md LICENSE .gitignore README.md
git commit -m "feat(repo): add pyproject.toml, install.sh, CI workflow, and agent documentation"
```
