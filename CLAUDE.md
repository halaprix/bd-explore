# CLAUDE.md - Development & Repository Guide for bd-explore

## Overview

`bd-explore` is a zero-dependency Python tool and MCP server that enables AI agents and developers to query a [beads](https://github.com/gastownhall/beads) issue store codegraph-style. One query returns verbatim issue content (descriptions, notes, comments, close reasons, memories) along with relationship graphs (blocks, blocked-by, parent-child, mentions, GitHub refs) under a strict token/character budget.

## Repository Architecture

```
src/bd_explore/
├── __init__.py         # Package root
├── __main__.py         # python -m bd_explore entrypoint
├── constants.py        # Shared constants, defaults (budget, limits, dependency kinds)
├── index.py            # SQLite FTS5 indexing, mention mining, store discovery, caching
├── search.py           # BM25 search, query parsing, neighborhood graph, blast radius, formatting
├── mcp.py              # Pure Python stdio JSON-RPC 2.0 MCP server
├── cli.py              # CLI parsing, subcommand dispatch (serve, install, uninstall, print-config)
└── installer/          # Multi-target agent platform installer & memory injector
    ├── instructions.py # Marker-fenced instruction template management
    ├── memory.py       # Beads persistent memory integration (`bd remember` / `bd forget`)
    ├── shared.py       # Atomic file operations, JSON/TOML merging helpers
    └── targets/        # Platform adapters (claude, gemini, antigravity, codex, cursor, agents_md)
```

## Running Tests

All tests use Python's built-in `unittest` module. No external test runners or packages are required.

```bash
# Run the entire test suite
PYTHONPATH=src python3 -m unittest discover tests

# Run specific test modules
PYTHONPATH=src python3 -m unittest tests.test_index
PYTHONPATH=src python3 -m unittest tests.test_search
PYTHONPATH=src python3 -m unittest tests.test_mcp
PYTHONPATH=src python3 -m unittest tests.test_installer
PYTHONPATH=src python3 -m unittest tests.test_cli

# Run a single test case
PYTHONPATH=src python3 -m unittest tests.test_search.TestSearchEngine.test_bm25_search_scoring
```

## Development & Code Style Guidelines

- **Zero Runtime Dependencies**: The core package, CLI, and MCP server must rely exclusively on Python 3.10+ standard library modules (`sqlite3`, `argparse`, `json`, `pathlib`, `re`, `subprocess`, `urllib`, `dataclasses`, etc.).
- **Typing & Modern Python**: Use `from __future__ import annotations` in every Python module. Use modern type annotations (`str | None`, `list[str]`, `dict[str, Any]`).
- **Atomic Operations**: All configuration updates and cache writes should write to temporary files and rename atomically (`replace` / `tempfile`).
- **Idempotent Instructions**: Rule and configuration injections must use marker fences (`

`) to allow clean updates and uninstalls.
- **Output Budgeting**: All explore/query responses must strictly respect the character budget parameter to prevent overflowing LLM context windows.

## CLI Commands

```bash
# Query / search
bd-explore "why did we refactor parser status:open"
bd-explore --blast <id>
bd-explore --rebuild

# Stdio MCP Server
bd-explore serve

# Multi-target installer
bd-explore install [--targets claude,gemini] [--location global|project] [--yes]
bd-explore uninstall [--targets claude] [--yes]
bd-explore print-config claude
```
