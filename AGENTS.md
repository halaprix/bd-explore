# AGENTS.md - Agent Guide for bd-explore

## Project Overview

`bd-explore` is a zero-dependency CLI tool and MCP server that provides fast, deep full-text and relational search across [beads](https://github.com/gastownhall/beads) issue stores. It surfaces complete issue prose (descriptions, designs, notes, comments, close reasons, memories) and relational graphs (blocks, parent-child, mentions, GitHub issues).

## Agent Guidelines & Rules

## Testing Commands

All unit tests run via Python stdlib `unittest`:

```bash
# Run all tests
PYTHONPATH=src python3 -m unittest discover tests -v

# Run individual test files
PYTHONPATH=src python3 -m unittest tests/test_index.py
PYTHONPATH=src python3 -m unittest tests/test_search.py
PYTHONPATH=src python3 -m unittest tests/test_mcp.py
PYTHONPATH=src python3 -m unittest tests/test_installer.py
PYTHONPATH=src python3 -m unittest tests/test_cli.py
```

## Architecture & Code Map

- `src/bd_explore/constants.py`: Constants (`VERSION`, `DEFAULT_BUDGET_CHARS`, `DEFAULT_SEEDS`, `DEP_KINDS`, `FILTER_KEYS`).
- `src/bd_explore/index.py`: Store resolution, SQLite FTS5 database management, mention mining, GitHub `#NNN` ref extraction, `bd memories` indexing, cache invalidation.
- `src/bd_explore/search.py`: Query parser (filters + free text), BM25 ranking, 1-hop relationship neighborhoods, transitive blast radius calculations, character budget formatting.
- `src/bd_explore/mcp.py`: Stdio JSON-RPC 2.0 MCP server exposing `bd_explore`.
- `src/bd_explore/cli.py`: CLI dispatcher for search, `serve`, `install`, `uninstall`, `print-config`.
- `src/bd_explore/installer/`: Multi-target platform configuration engine (Claude Code, Gemini CLI, Antigravity IDE, Codex, Cursor, `AGENTS.md`) and beads persistent memory injection.

## Code Style Requirements

- Zero runtime dependencies outside Python 3.10+ standard library.
- Type annotations across all public functions and methods.
- Atomic file writes for all configuration files.
- Fenced marker tags (`<!-- BD_EXPLORE_START -->` / `<!-- BD_EXPLORE_END -->`) for agent rule injections.
