# Design Specification: bd-explore Repository Structure, MCP Server & Multi-Target Installer

**Date:** 2026-08-18  
**Status:** Approved  
**Author:** AI Agent (Pair Programming with User)

---

## 1. Overview & Goals

`bd-explore` enables AI coding agents and human developers to ask questions against a [beads](https://github.com/gastownhall/beads) issue store in the exact same manner that `codegraph explore` queries codebases. One call returns verbatim content (titles, descriptions, designs, acceptance criteria, notes, author comments, close reasons) along with relationship neighborhood graphs (blocks, blocked-by, epic hierarchy, prose mention edges, GitHub references), stamped with staleness metadata under a character budget.

This specification details transforming `bd-explore` into a first-class repository featuring:
1. **Modular Zero-Dependency Python Architecture**: High performance, zero 3rd-party dependencies (CPython stdlib 3.10+ only).
2. **Built-in Stdio JSON-RPC MCP Server**: Exposes the `bd_explore` tool to MCP clients (Claude Code, Cursor, Codex, Gemini/Antigravity).
3. **Multi-Target Agent Installer**: Automatically discovers and configures MCP clients, injects marker-fenced instructions (`<!-- BD_EXPLORE_START --> ... <!-- BD_EXPLORE_END -->`), and supports clean uninstallation.
4. **Beads Memory Injection**: Automatically injects guidance into Beads persistent memory (`bd remember --key bd-explore`) so every `bd prime` session loads `bd-explore` context.
5. **Standard Distribution & Packaging**: `pyproject.toml`, curlable `install.sh`, full `unittest` test suite, GitHub Actions CI, and developer documentation (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`).

---

## 2. Repository Layout

```
bd-explore/
├── .github/
│   └── workflows/
│       └── ci.yml
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-08-18-bd-explore-repo-and-installer-design.md
├── src/
│   └── bd_explore/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── constants.py
│       ├── index.py
│       ├── search.py
│       ├── mcp.py
│       └── installer/
│           ├── __init__.py
│           ├── instructions.py
│           ├── memory.py
│           ├── shared.py
│           └── targets/
│               ├── __init__.py
│               ├── claude.py
│               ├── gemini.py
│               ├── antigravity.py
│               ├── codex.py
│               ├── cursor.py
│               └── agents_md.py
├── tests/
│   ├── __init__.py
│   ├── test_index.py
│   ├── test_search.py
│   ├── test_mcp.py
│   └── test_installer.py
├── .gitignore
├── AGENTS.md
├── CLAUDE.md
├── GEMINI.md
├── LICENSE
├── README.md
├── install.sh
└── pyproject.toml
```

---

## 3. Core Engine Architecture

### 3.1 Constants & Types (`constants.py`)
- `VERSION = "0.1.0"`
- `DEFAULT_BUDGET_CHARS = 24_000`
- `DEFAULT_SEEDS = 5`
- `DEP_KINDS = {"parent-child", "discovered-from", "blocks", "blocked-by", "related", "relates-to", "supersedes"}`
- `FILTER_KEYS = {"status", "type", "priority", "epic", "id"}`

### 3.2 Indexing Engine (`index.py`)
- **Store Discovery (`find_store`)**:
  - Checks `--store` flag / function argument.
  - Checks `BD_EXPLORE_STORE` environment variable.
  - Recursively searches upward from `Path.cwd()` for `.beads/issues.jsonl` or `issues.jsonl`.
- **Cache Storage (`cache_db_path`)**:
  - Locates database in `${XDG_CACHE_HOME:-~/.cache}/bd-explore/<sha1_hash>.db`.
- **SQLite FTS5 Schema**:
  ```sql
  CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
  CREATE TABLE docs (
    id TEXT PRIMARY KEY, kind TEXT, title TEXT, status TEXT, itype TEXT,
    priority INTEGER, created TEXT, updated TEXT, closed TEXT, body TEXT
  );
  CREATE TABLE edges (src TEXT, dst TEXT, kind TEXT, PRIMARY KEY (src, dst, kind));
  CREATE INDEX edges_dst ON edges (dst);
  CREATE VIRTUAL TABLE docs_fts USING fts5(id, title, body, tokenize='porter unicode61');
  ```
- **Prose Extraction (`compose_body`)**:
  - Extracts and formats `description`, `design`, `acceptance_criteria`, `notes`, `comments` (with author + date stamp), and `close_reason`.
- **Relationship & Mention Mining**:
  - Dependency edges: parses `dependencies` array (`blocks`, `parent-child`, `supersedes`, `discovered-from`, `related`).
  - Text-mention edges: compiles a unified regex of all known bead IDs and finds cross-references inside titles and prose (`mentions`).
  - GitHub references: extracts `#\d{2,5}` patterns into `gh-ref` edges.
- **Memory Integration (`load_memories`)**:
  - Calls `bd memories --json` if `bd` is present, indexing memories as `mem:<key>` records with `mentions` edges.
- **Cache Invalidation (`open_index`)**:
  - Checks `mtime` and `size` in `meta` against `issues.jsonl`. Rebuilds only when changes occur or `--rebuild` is passed.

### 3.3 Search & Graph Engine (`search.py`)
- **Query Parser (`parse_query`)**:
  - Extracts field filters: `status:`, `type:`, `priority:`, `epic:`, `id:`.
  - Non-filter tokens fall through to free-text matching.
- **BM25 Search (`search`)**:
  - Escapes query terms into Porter-stemmed FTS `OR` matches.
  - Applies SQL filters.
  - Ranks by `bm25` score and promotes `in_progress` / `open` before `closed` issues.
- **1-Hop Neighborhood Graph (`neighborhood`)**:
  - Resolves incoming and outgoing edges for `parent-child`, `blocks`, `blocked-by`, `discovered-from`, `supersedes`, `mentions`, and `gh-ref`.
- **Transitive Blast Radius (`blast`)**:
  - Computes transitive closures for `blocks` (forward) and `blocked-by` (backward), plus full epic parent chain.
- **Renderer (`render`, `render_header`)**:
  - Formats output with status/staleness stamp `[STATUS · P<n> · <type> · updated YYYY-MM-DD]`.
  - Enforces character budget cap (`budget` / `len(rows)`), displaying clear truncation notices and neighborhood listings.

---

## 4. Built-in Stdio MCP Server (`mcp.py`)

A pure-Python JSON-RPC 2.0 stdio server providing standard MCP communication for AI agent hosts.

### 4.1 MCP Endpoints Handled
- `initialize`: Returns protocol version `2024-11-05`, server metadata (`name: "bd-explore"`, `version: "0.1.0"`), capabilities (`tools: {}`), and system instructions.
- `notifications/initialized`: Notification acknowledgement.
- `tools/list`: Declares `bd_explore` tool with complete JSON schema.
- `tools/call`: Executes search query or blast radius calculation and returns `{ "content": [{ "type": "text", "text": "..." }] }`.
- `ping`: Returns empty response `{}`.

### 4.2 Tool Schema: `bd_explore`
- `query` (string, optional): Free-text query with optional field filters (`status:open type:task`).
- `blast` (string, optional): Bead ID to calculate transitive blast radius.
- `limit` (integer, optional, default: 5): Max seeds to return.
- `budget` (integer, optional, default: 24000): Character output budget.
- `store` (string, optional): Path to repository or `.beads` store.

---

## 5. Multi-Target Installer & Memory Injection (`installer/`)

### 5.1 Marker-Fenced Agent Instructions (`instructions.py`)
```markdown
<!-- BD_EXPLORE_START -->
## bd-explore

In repositories with a beads store (a `.beads/` directory exists at the repo root), reach for `bd-explore` BEFORE searching raw files or relying only on `bd search`:

- **MCP tool** (when available): `bd_explore` answers questions about beads/issues/decisions/memories verbatim — description, notes, comments, close reason, plus relationship neighborhood under an output budget.
- **Shell** (always works): `bd-explore "<query>"` (e.g. `bd-explore "why did we re-point SYRP status:open"`, `bd-explore --blast <id>`).

If there is no `.beads/` directory, skip bd-explore.
<!-- BD_EXPLORE_END -->
```
- Helper functions: `replace_or_append_marked_section()`, `remove_marked_section()`.

### 5.2 Agent Targets (`installer/targets/`)
- **Claude Code (`claude.py`)**:
  - MCP Config: `~/.claude.json` (global) or `./.mcp.json` (local).
  - Instructions: `~/.claude/CLAUDE.md` or `./CLAUDE.md`.
  - Permissions: `~/.claude/settings.json` (pre-approves `mcp__bd-explore__*` and `mcp__bd_explore__*`).
- **Gemini CLI / Antigravity CLI (`gemini.py`)**:
  - MCP Config: `~/.gemini/settings.json` (global) or `./.gemini/settings.json` (local).
  - Instructions: `~/.gemini/GEMINI.md` or `./GEMINI.md`.
- **Antigravity IDE (`antigravity.py`)**:
  - MCP Config: `~/.gemini/config/mcp_config.json` (with legacy fallback).
  - Note: Omits `type: stdio` property as required by Antigravity IDE.
- **OpenAI Codex (`codex.py`)**:
  - Config: `~/.codex/config.toml` (TOML table `[mcp_servers.bd-explore]`).
  - Instructions: `~/.codex/AGENTS.md`.
- **Cursor (`cursor.py`)**:
  - MCP Config: `~/.cursor/mcp.json` or `./.cursor/mcp.json`.
  - Rules: `.cursor/rules/bd-explore.mdc` or `.cursorrules`.
- **Generic AGENTS.md (`agents_md.py`)**:
  - Project `./AGENTS.md` and user `~/.config/AGENTS.md`.

### 5.3 Beads Persistent Memory Injection (`memory.py`)
- Executes:
  ```bash
  bd remember "Use 'bd-explore <query>' or the 'bd_explore' MCP tool to query beads issues, notes, comments, close reasons, and relationship graphs." --key bd-explore
  ```
- On uninstall: executes `bd forget bd-explore`.

### 5.4 CLI Commands & Flags
- `bd-explore install [--target <targets>] [--location global|local] [--auto-allow] [--yes]`
- `bd-explore uninstall [--target <targets>] [--location global|local] [--yes]`
- `bd-explore print-config [--target <target>] [--location global|local]`

---

## 6. Packaging & Installation

### 6.1 `pyproject.toml`
- Modern PEP 517/621 packaging.
- Entrypoints:
  ```toml
  [project.scripts]
  bd-explore = "bd_explore.cli:main"
  bd_explore = "bd_explore.cli:main"
  ```

### 6.2 Standalone `install.sh`
- Verifies Python 3.10+ and SQLite FTS5.
- Links executable to `~/.local/bin/bd-explore` and `~/.local/bin/bd_explore`.
- Runs `bd-explore install --yes`.
- Warns if `~/.local/bin` is not in `$PATH`.
- Supports `--uninstall`.

---

## 7. Testing Strategy

Using Python standard library `unittest`:
- `tests/test_index.py`: Full parsing of JSONL store, memories, mention graph creation, cache invalidation.
- `tests/test_search.py`: Filter parsing, BM25 scoring, status rank priority, blast radius, output budget enforcement.
- `tests/test_mcp.py`: JSON-RPC message handling, tool schema reflection, query execution via MCP.
- `tests/test_installer.py`: Atomic writes, marker insertion & removal idempotency, target configs, beads memory commands.
