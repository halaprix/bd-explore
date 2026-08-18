# GEMINI.md - Gemini / Antigravity Guide for bd-explore

## Overview

`bd-explore` is a zero-dependency CLI tool and MCP server enabling fast queries across [beads](https://github.com/gastownhall/beads) issue stores. It acts like `codegraph explore` for issues: retrieving verbatim prose, author comments, close reasons, and relationship neighborhood graphs.

## Context & Guidelines

## Running Verification Tests

Run the full test suite with Python's built-in `unittest`:

```bash
PYTHONPATH=src python3 -m unittest discover tests -v
```

To run individual test modules:

```bash
PYTHONPATH=src python3 -m unittest tests.test_index
PYTHONPATH=src python3 -m unittest tests.test_search
PYTHONPATH=src python3 -m unittest tests.test_mcp
PYTHONPATH=src python3 -m unittest tests.test_installer
PYTHONPATH=src python3 -m unittest tests.test_cli
```

## Structure

- `src/bd_explore/constants.py`: Constants & defaults.
- `src/bd_explore/index.py`: Store resolution, SQLite FTS5 indexing, mention graph extraction, cache management.
- `src/bd_explore/search.py`: Query parsing, BM25 ranking, 1-hop neighborhood, transitive blast radius, output budget enforcement.
- `src/bd_explore/mcp.py`: Stdio JSON-RPC 2.0 MCP server.
- `src/bd_explore/installer/`: Multi-target platform configuration and beads memory injection.
- `src/bd_explore/cli.py`: Command routing and entrypoint.
