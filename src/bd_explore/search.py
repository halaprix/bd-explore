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
    "hydrate",
    "hydrate_blast",
    "render",
    "render_blast",
    "render_header",
    "format_output",
    "format_blast",
]

_EDGE_LABELS = {
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


def escape_like(val: str) -> str:
    """Escape special characters in SQLite LIKE queries."""
    return val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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
        priorities: list[int] = []
        for p in filters["priority"]:
            cleaned = str(p).lstrip("pP")
            if cleaned.isdigit():
                priorities.append(int(cleaned))
        if priorities:
            where.append(f"d.priority IN ({','.join('?' * len(priorities))})")
            params.extend(priorities)
    if filters.get("id"):
        where.append("(" + " OR ".join("d.id LIKE ? ESCAPE '\\'" for _ in filters["id"]) + ")")
        params.extend(f"%{escape_like(i)}%" for i in filters["id"])
    if filters.get("epic"):
        clauses = []
        for e in filters["epic"]:
            clauses.append(
                "d.id IN (SELECT src FROM edges WHERE kind='parent-child' AND dst LIKE ? ESCAPE '\\')"
            )
            params.append(f"%{escape_like(e)}%")
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

    labels = _EDGE_LABELS
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
    row = con.execute(
        "SELECT * FROM docs WHERE id LIKE ? ESCAPE '\\' ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END LIMIT 1",
        (f"%{escape_like(bead_id)}%", bead_id),
    ).fetchone()
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


def hydrate(con: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Fetch everything render() needs in two batched queries: the rows' full
    edge set and the titles of every endpoint. Fixes the per-row/per-edge N+1."""
    con.row_factory = sqlite3.Row
    records = [dict(r) | {"neighborhood": {}} for r in rows]
    if not records:
        return []
    by_id = {rec["id"]: rec for rec in records}
    ids = list(by_id)
    ph = ",".join("?" * len(ids))
    edges = con.execute(
        f"SELECT src, dst, kind FROM edges WHERE src IN ({ph}) OR dst IN ({ph})",
        [*ids, *ids],
    ).fetchall()

    endpoints = sorted({e for edge in edges for e in (edge["src"], edge["dst"])})
    titles: dict[str, str] = {}
    if endpoints:
        ph2 = ",".join("?" * len(endpoints))
        for t in con.execute(f"SELECT id, title, status FROM docs WHERE id IN ({ph2})", endpoints):
            titles[t["id"]] = f"{t['title']} [{t['status']}]"

    for edge in edges:
        for bead_id in dict.fromkeys((edge["src"], edge["dst"])):
            rec = by_id.get(bead_id)
            if rec is None:
                continue
            direction = "out" if edge["src"] == bead_id else "in"
            other = edge["dst"] if direction == "out" else edge["src"]
            label = _EDGE_LABELS.get((edge["kind"], direction), edge["kind"])
            title = "" if edge["kind"] == "gh-ref" else titles.get(other, "(external)")
            rec["neighborhood"].setdefault(label, []).append((other, title))
    return records


def hydrate_blast(con: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    """Attach a `labels` map ("title [status]" per id) so render_blast is pure."""
    con.row_factory = sqlite3.Row
    ids = sorted(
        {*data["blocked_by_transitively"], *data["blocks_transitively"], *data["epic_ancestry"]}
    )
    labels: dict[str, str] = {}
    if ids:
        ph = ",".join("?" * len(ids))
        for t in con.execute(f"SELECT id, title, status FROM docs WHERE id IN ({ph})", ids):
            labels[t["id"]] = f"{t['title']} [{t['status']}]"
    return {**data, "labels": labels}


def render_header(r: sqlite3.Row | dict[str, Any]) -> str:
    if r["kind"] == "memory":
        return f"═══ {r['id']} [MEMORY]"
    prio = f"P{r['priority']}" if r["priority"] is not None else "P?"
    stamp = f"updated {r['updated']}" + (f", closed {r['closed']}" if r["closed"] else "")
    status_str = (r["status"] or "").upper()
    return f"═══ {r['id']} [{status_str} · {prio} · {r['itype']} · {stamp}]\n    {r['title']}"


def render(records: list[dict[str, Any]], budget: int) -> str:
    """Pure: hydrated records + budget in, formatted text out. All budget and
    truncation logic lives here, testable without an index."""
    if budget <= 0:
        return ""
    if not records:
        msg = "no matches — try fewer terms, or status:all"
        return msg if len(msg) <= budget else msg[:budget]

    output_blocks: list[str] = []
    current_len = 0
    num_rows = len(records)
    target_per_doc = max(budget // num_rows, 1)

    for r in records:
        sep_len = 2 if output_blocks else 0
        remaining_total = budget - current_len - sep_len
        if remaining_total <= 0:
            break

        header = render_header(r)
        hood = r["neighborhood"]
        hood_lines = []
        if hood:
            hood_lines.append("    ── neighborhood ──")
            for label, items in sorted(hood.items()):
                shown = items[:6]
                extra = f" (+{len(items) - 6} more)" if len(items) > 6 else ""
                names = ", ".join(f"{i}" + (f" — {t}" if t else "") for i, t in shown)
                hood_lines.append(f"    {label}: {names}{extra}")
        hood_text = "\n".join(hood_lines)

        # Allocate budget for this doc
        available_for_doc = min(max(target_per_doc, 120), remaining_total)
        body = r["body"] or "(no body)"
        indented_body = textwrap.indent(body, "    ")

        # Check full block size
        block_parts = [header, indented_body]
        if hood_text:
            block_parts.append(hood_text)
        block_text = "\n".join(block_parts)

        # If block_text exceeds available_for_doc, truncate body
        if len(block_text) > available_for_doc:
            overhead = len(header) + 1 + (len(hood_text) + 1 if hood_text else 0)
            notice = f"… [truncated — full body: bd show {r['id']}]"
            indented_notice = f"    {notice}"

            space_for_body = available_for_doc - overhead - len(indented_notice) - 1
            if space_for_body > 10:
                raw_slice_len = max(space_for_body - 4, 1)
                shortened_body = body[:raw_slice_len].rstrip()
                indented_body = textwrap.indent(shortened_body, "    ") + "\n" + indented_notice
            else:
                indented_body = indented_notice

            block_parts = [header, indented_body]
            if hood_text:
                block_parts.append(hood_text)
            block_text = "\n".join(block_parts)

        # Final check if block_text fits in remaining_total
        if len(block_text) > remaining_total:
            block_text = block_text[:remaining_total]

        if not block_text:
            break

        output_blocks.append(block_text)
        current_len += len(block_text) + sep_len

    rendered = "\n\n".join(output_blocks)
    shown_count = len(output_blocks)
    if shown_count < num_rows:
        omitted = num_rows - shown_count
        if shown_count == 0:
            notice = f"… [output capped at {budget} chars; all {num_rows} hit(s) omitted. Use higher --budget]"
        else:
            notice = f"\n… [output capped at {budget} chars; {omitted} additional hit(s) omitted. Use 'bd show <id>' or higher --budget]"

        if len(rendered) + len(notice) <= budget:
            rendered = rendered + notice
        elif len(notice) <= budget:
            trim_point = budget - len(notice)
            rendered = rendered[:trim_point].rstrip() + notice
        else:
            rendered = notice[:budget]

    return rendered[:budget]


def format_output(con: sqlite3.Connection, rows: list[sqlite3.Row], budget: int) -> str:
    return render(hydrate(con, rows), budget)


def render_blast(data: dict[str, Any], budget: int = 24_000) -> str:
    """Pure counterpart of format_blast: expects hydrate_blast()-style data."""
    if budget <= 0:
        return ""
    labels = data.get("labels", {})
    lines = [render_header(data["root"])]

    def show(label: str, items: list[str]) -> None:
        lines.append(f"\n{label}: {len(items) or 'none'}")
        for i in items:
            lines.append(f"  {i}  {labels[i]}" if i in labels else f"  {i}   [?]")

    show("this bead is blocked by (transitively)", data["blocked_by_transitively"])
    show("beads this blocks (transitively)", data["blocks_transitively"])
    show("epic ancestry", data["epic_ancestry"])

    full_text = "\n".join(lines)
    if len(full_text) > budget:
        notice = f"\n… [blast output capped at {budget} chars]"
        if len(notice) <= budget:
            return full_text[:budget - len(notice)].rstrip() + notice
        return full_text[:budget]
    return full_text


def format_blast(con: sqlite3.Connection, data: dict[str, Any], budget: int = 24_000) -> str:
    return render_blast(hydrate_blast(con, data), budget)
