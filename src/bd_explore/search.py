"""Search and graph exploration engine."""

from __future__ import annotations

import re
import sqlite3
import textwrap
from typing import Any

from bd_explore.constants import FILTER_KEYS

__all__ = [
    "parse_query",
    "fts_escape",
    "status_rank",
    "search",
    "neighborhood",
    "blast_data",
    "render_header",
    "format_output",
    "format_blast",
]


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
                if vals:
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


def search(
    con: sqlite3.Connection, text: str, filters: dict[str, list[str]], limit: int
) -> list[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    where: list[str] = []
    params: list[Any] = []
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
        if match:
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
        ("gh-ref", "in"): "github refs",
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


def render_header(r: sqlite3.Row | dict[str, Any]) -> str:
    if r["kind"] == "memory":
        return f"═══ {r['id']} [MEMORY]"
    prio = f"P{r['priority']}" if r["priority"] is not None else "P?"
    stamp = f"updated {r['updated']}" + (f", closed {r['closed']}" if r["closed"] else "")
    return f"═══ {r['id']} [{r['status'].upper()} · {prio} · {r['itype']} · {stamp}]\n    {r['title']}"


def format_output(con: sqlite3.Connection, rows: list[sqlite3.Row], budget: int) -> str:
    if not rows:
        return "no matches — try fewer terms, or status:all"
    con.row_factory = sqlite3.Row
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
    con.row_factory = sqlite3.Row
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
