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

from bd_explore.constants import DEP_KINDS, SCHEMA_VERSION

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
            if (p / "issues.jsonl").exists():
                p = p / "issues.jsonl"
            elif (p / ".beads" / "issues.jsonl").exists():
                p = p / ".beads" / "issues.jsonl"
            else:
                raise FileNotFoundError(f"bd-explore: no issues.jsonl found in directory: {p}")
        if not p.exists():
            raise FileNotFoundError(f"bd-explore: store export not found: {p}")
        if p.name != "issues.jsonl" and not p.name.endswith(".jsonl"):
            raise ValueError(f"bd-explore: store must be an issues.jsonl file or directory: {p}")
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


def load_memories(cwd: Path | None = None) -> list[dict]:
    """Memories aren't in the jsonl export; pull them via the bd CLI when present.
    Degrades to empty — the index still covers all issues."""
    try:
        out = subprocess.run(
            ["bd", "memories", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
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
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = db_path.with_name(f"{db_path.name}.tmp.{os.getpid()}")
    if tmp_db.exists():
        try:
            tmp_db.unlink()
        except OSError:
            pass

    con = sqlite3.connect(tmp_db)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)

        # Deduplicate records by ID (keep latest occurrence)
        records_map: dict[str, dict] = {}
        with open(store, encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict) and data.get("id"):
                        records_map[data["id"]] = data
                except json.JSONDecodeError:
                    continue

        records = list(records_map.values())
        ids = set(records_map.keys())
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
                if not isinstance(d, dict):
                    continue
                src_id = d.get("issue_id") or r["id"]
                dst_id = d.get("depends_on_id")
                kind = d.get("type") or "related"
                if not dst_id or not src_id:
                    continue
                if kind == "blocked-by":
                    edges.add((dst_id, src_id, "blocks"))
                else:
                    edges.add((src_id, dst_id, kind))

            searchable = f"{r.get('title', '')}\n{body}"
            if mention_re:
                for m in set(mention_re.findall(searchable)):
                    if m != r["id"]:
                        edges.add((r["id"], m, "mentions"))
            for gh in set(gh_re.findall(searchable)):
                edges.add((r["id"], f"#{gh}", "gh-ref"))

        repo_dir = store.parent.parent if store.parent.name == ".beads" else store.parent
        for m in load_memories(cwd=repo_dir):
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
            [
                ("mtime", str(st.st_mtime_ns)),
                ("size", str(st.st_size)),
                ("schema_version", SCHEMA_VERSION),
            ],
        )
        con.commit()
        con.close()
        os.replace(tmp_db, db_path)
        final_con = sqlite3.connect(db_path)
        final_con.row_factory = sqlite3.Row
        return final_con
    except Exception:
        try:
            con.close()
        except Exception:
            pass
        if tmp_db.exists():
            try:
                tmp_db.unlink()
            except OSError:
                pass
        raise


def open_index(store: Path, force: bool = False) -> sqlite3.Connection:
    db_path = cache_db_path(store)
    if not force and db_path.exists():
        con = None
        try:
            con = sqlite3.connect(db_path)
            con.row_factory = sqlite3.Row
            meta = dict(con.execute("SELECT k, v FROM meta"))
            st = store.stat()
            if (
                meta.get("mtime") == str(st.st_mtime_ns)
                and meta.get("size") == str(st.st_size)
                and meta.get("schema_version") == SCHEMA_VERSION
            ):
                return con
            con.close()
        except sqlite3.DatabaseError:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
    return build_index(store, db_path)
