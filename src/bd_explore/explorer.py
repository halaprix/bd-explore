"""The explore pipeline behind one interface: primitives in, formatted text out.

Owns store discovery, index freshness, connection lifetime, defaulting, and
canonical error text. cli.py and mcp.py are thin adapters over this module.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from bd_explore.constants import DEFAULT_BUDGET_CHARS, DEFAULT_SEEDS, MIN_BUDGET_CHARS
from bd_explore.index import find_store, open_index
from bd_explore.search import blast_data, format_blast, format_output, parse_query, search

__all__ = ["ExploreError", "explore", "blast"]


class ExploreError(Exception):
    """A failure the caller should show verbatim: str(exc) is the user-facing message."""


def _coerce_int(val: Any, default: int, min_val: int) -> int:
    if val is None or isinstance(val, bool):
        return default
    try:
        parsed = int(val)
    except (ValueError, TypeError):
        return default
    return max(parsed, min_val) if parsed > 0 else default


def _open(store: str | Path | None, rebuild: bool) -> tuple[Path, sqlite3.Connection]:
    try:
        store_path = find_store(str(store) if store else None)
    except (FileNotFoundError, ValueError) as e:
        raise ExploreError(str(e)) from e
    try:
        return store_path, open_index(store_path, force=rebuild)
    except Exception as e:
        raise ExploreError(f"bd-explore: index error: {e}") from e


def explore(
    query: str = "",
    *,
    store: str | Path | None = None,
    limit: Any = None,
    budget: Any = None,
    rebuild: bool = False,
) -> str:
    """Search the store and return formatted hits. An empty query lists recent
    docs; rebuild=True with an empty query returns a rebuild summary instead."""
    limit = _coerce_int(limit, DEFAULT_SEEDS, min_val=1)
    budget = _coerce_int(budget, DEFAULT_BUDGET_CHARS, min_val=MIN_BUDGET_CHARS)
    store_path, con = _open(store, rebuild)
    try:
        if rebuild and not query.strip():
            n = con.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
            return f"rebuilt: {n} docs from {store_path}"
        text, filters = parse_query(query)
        rows = search(con, text, filters, limit)
        return format_output(con, rows, budget)
    finally:
        con.close()


def blast(
    bead_id: str,
    *,
    store: str | Path | None = None,
    budget: Any = None,
    rebuild: bool = False,
) -> str:
    """Return the transitive dependency closure of one bead, formatted."""
    budget = _coerce_int(budget, DEFAULT_BUDGET_CHARS, min_val=MIN_BUDGET_CHARS)
    _, con = _open(store, rebuild)
    try:
        try:
            data = blast_data(con, bead_id)
        except ValueError as e:
            raise ExploreError(str(e)) from e
        return format_blast(con, data, budget=budget)
    finally:
        con.close()
