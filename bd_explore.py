#!/usr/bin/env python3
"""bd-explore: Ask a beads store questions, codegraph-style.

Backward-compatible entrypoint shim delegating to bd_explore.cli:main.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure src is at front of sys.path and remove root/cwd to avoid self-import recursion
_root = Path(__file__).resolve().parent
_src_dir = str(_root / "src")
_root_str = str(_root)

for p in ("", ".", _root_str):
    while p in sys.path:
        sys.path.remove(p)

if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# If this standalone file was registered as 'bd_explore' in sys.modules,
# clear it so Python resolves the actual package in src/bd_explore.
if "bd_explore" in sys.modules and not hasattr(sys.modules["bd_explore"], "__path__"):
    del sys.modules["bd_explore"]

from bd_explore.cli import main
from bd_explore.constants import DEFAULT_BUDGET_CHARS, DEFAULT_SEEDS, DEP_KINDS, FILTER_KEYS, VERSION
from bd_explore.index import build_index, cache_db_path, compose_body, find_store, open_index
from bd_explore.mcp import run_mcp_server
from bd_explore.search import blast_data, format_blast, format_output, neighborhood, parse_query, render_header, search

__all__ = [
    "main",
    "find_store",
    "cache_db_path",
    "compose_body",
    "build_index",
    "open_index",
    "parse_query",
    "search",
    "neighborhood",
    "blast_data",
    "render_header",
    "format_output",
    "format_blast",
    "run_mcp_server",
    "VERSION",
    "DEFAULT_BUDGET_CHARS",
    "DEFAULT_SEEDS",
    "DEP_KINDS",
    "FILTER_KEYS",
]

if __name__ == "__main__":
    sys.exit(main())
