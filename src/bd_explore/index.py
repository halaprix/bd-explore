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
