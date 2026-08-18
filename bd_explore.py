#!/usr/bin/env python3
"""bd-explore — ask a beads store questions, the way codegraph_explore asks a codebase.

One call: a free-text query (with optional field filters) returns the most relevant
beads VERBATIM — title, description, notes, comments, close reason — plus each hit's
relationship neighborhood (epic ancestry, blocks/blocked-by, discovered-from, and
text-mention edges mined from notes), under an output budget.

Derived and disposable: reads the store's auto-exported `.beads/issues.jsonl`
(plus `bd memories --json` when the bd CLI is available) into a SQLite FTS5 index
under ~/.cache/bd-explore/, rebuilt automatically whenever the export changes.
The beads store remains the sole authority; delete the cache freely.

Usage:
  bd_explore.py "why did we re-point SYRP"          # ask
  bd_explore.py "stale hash status:open type:bug"   # ask with filters
  bd_explore.py --blast <id>                        # blast radius for one bead
  bd_explore.py --rebuild                           # force reindex

Filters: status:open|closed|in_progress|deferred|all   type:bug|feature|task|epic|chore
         priority:0..4   epic:<id-or-suffix>   id:<prefix>
Closed beads are INCLUDED by default (history is most of the value), ranked below
open ones at equal text relevance. Every hit is stamped [STATUS · P<n> · updated
YYYY-MM-DD] — bead claims age badly, so read the stamp before trusting the body.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

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
DEFAULT_BUDGET_CHARS = 24_000
DEFAULT_SEEDS = 5


# ── store discovery ──────────────────────────────────────────────────────────

def find_store(explicit: str | None) -> Path:
    """Resolve the issues.jsonl export: --store flag, BD_EXPLORE_STORE env, or
    walk up from cwd looking for .beads/issues.jsonl."""
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_dir():
            p = p / "issues.jsonl" if (p / "issues.jsonl").exists() else p / ".beads" / "issues.jsonl"
        if not p.exists():
            sys.exit(f"bd-explore: store export not found: {p}")
        return p
    env = os.environ.get("BD_EXPLORE_STORE")
    if env:
        return find_store(env)
    cur = Path.cwd()
    for d in [cur, *cur.parents]:
        cand = d / ".beads" / "issues.jsonl"
        if cand.exists():
            return cand
    sys.exit(
        "bd-explore: no .beads/issues.jsonl found from cwd upward. "
        "Run inside a beads repo, or pass --store / set BD_EXPLORE_STORE. "
        "(The export requires the store's export.auto: true.)"
    )


def cache_db_path(store: Path) -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "bd-explore"
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(str(store.resolve()).encode()).hexdigest()[:16]
    return root / f"{key}.db"


# ── indexing ─────────────────────────────────────────────────────────────────

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
    # One compiled pattern for text-mention mining: any known id appearing in any
    # bead's prose becomes a `mentions` edge. Sorted longest-first so `x.10`
    # wins over `x.1` prefix overlap.
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


# ── query ────────────────────────────────────────────────────────────────────

def parse_query(raw: str) -> tuple[str, dict[str, list[str]]]:
    """codegraph-style field-qualified parsing: `status:open type:bug free text`.
    Unknown prefixes fall through to free text (searching for `PR #NNN:` must work)."""
    filters: dict[str, list[str]] = {}
    text_parts: list[str] = []
    for tok in raw.split():
        if ":" in tok:
            key, _, val = tok.partition(":")
            if key.lower() in FILTER_KEYS and val:
                filters.setdefault(key.lower(), []).append(val)
                continue
        text_parts.append(tok)
    return " ".join(text_parts), filters


def fts_escape(text: str) -> str:
    """Quote every term — user text is a question, not FTS syntax."""
    terms = [t for t in re.findall(r"[\w./#-]+", text) if t]
    return " OR ".join(f'"{t}"' for t in terms)


def status_rank(status: str) -> int:
    return {"in_progress": 0, "open": 1, "deferred": 2, "": 3}.get(status, 4)  # closed last


def search(con: sqlite3.Connection, text: str, filters: dict, limit: int) -> list[sqlite3.Row]:
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


def blast(con: sqlite3.Connection, bead_id: str) -> None:
    """Transitive blocked-by/blocks closure + epic ancestry for one bead."""
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM docs WHERE id LIKE ?", (f"%{bead_id}%",)).fetchone()
    if not row:
        sys.exit(f"bd-explore: no bead matching '{bead_id}'")
    print(render_header(row))

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

    def show(label: str, items: list[str]) -> None:
        print(f"\n{label}: {len(items) or 'none'}")
        for i in items:
            r = con.execute("SELECT title, status FROM docs WHERE id=?", (i,)).fetchone()
            print(f"  {i}  {r['title'] if r else ''} [{r['status'] if r else '?'}]")

    show("this bead is blocked by (transitively)", walk(row["id"], True))
    show("beads this blocks (transitively)", walk(row["id"], False))
    ancestry, cur = [], row["id"]
    while True:
        parent = con.execute(
            "SELECT dst FROM edges WHERE src=? AND kind='parent-child'", (cur,)
        ).fetchone()
        if not parent or parent[0] in ancestry:
            break
        ancestry.append(parent[0])
        cur = parent[0]
    show("epic ancestry", ancestry)


# ── rendering ────────────────────────────────────────────────────────────────

def render_header(r: sqlite3.Row) -> str:
    if r["kind"] == "memory":
        return f"═══ {r['id']} [MEMORY]"
    prio = f"P{r['priority']}" if r["priority"] is not None else "P?"
    stamp = f"updated {r['updated']}" + (f", closed {r['closed']}" if r["closed"] else "")
    return f"═══ {r['id']} [{r['status'].upper()} · {prio} · {r['itype']} · {stamp}]\n    {r['title']}"


def render(con: sqlite3.Connection, rows: list[sqlite3.Row], budget: int) -> None:
    if not rows:
        print("no matches — try fewer terms, or status:all")
        return
    per_doc = max(budget // len(rows), 1200)
    for r in rows:
        print(render_header(r))
        body = r["body"] or "(no body)"
        if len(body) > per_doc:
            body = body[:per_doc] + f"\n… [truncated — full body: bd show {r['id']}]"
        print(textwrap.indent(body, "    "))
        hood = neighborhood(con, r["id"])
        if hood:
            print("    ── neighborhood ──")
            for label, items in sorted(hood.items()):
                shown = items[:6]
                extra = f" (+{len(items) - 6} more)" if len(items) > 6 else ""
                names = ", ".join(
                    f"{i}" + (f" — {t}" if t else "") for i, t in shown
                )
                print(f"    {label}: {names}{extra}")
        print()


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ask a beads store questions, codegraph-style.",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("query", nargs="*", help="free text + field filters (status: type: priority: epic: id:)")
    ap.add_argument("--store", help="path to repo, .beads dir, or issues.jsonl")
    ap.add_argument("--blast", metavar="ID", help="blast radius for one bead id (or suffix)")
    ap.add_argument("--rebuild", action="store_true", help="force reindex")
    ap.add_argument("-n", "--limit", type=int, default=DEFAULT_SEEDS)
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET_CHARS, help="output char budget")
    args = ap.parse_args()

    store = find_store(args.store)
    con = open_index(store, force=args.rebuild)

    if args.blast:
        blast(con, args.blast)
        return
    if not args.query:
        if args.rebuild:
            n = con.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
            print(f"rebuilt: {n} docs from {store}")
            return
        ap.error("give a query, --blast <id>, or --rebuild")

    text, filters = parse_query(" ".join(args.query))
    rows = search(con, text, filters, args.limit)
    render(con, rows, args.budget)


if __name__ == "__main__":
    main()
