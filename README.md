# bd-explore

Ask a [beads](https://github.com/gastownhall/beads) store questions, the way `codegraph explore` asks a codebase: one call returns the most relevant beads **verbatim** — description, notes, comments, close reason — plus each hit's relationship neighborhood, under an output budget.

Fills the gap the stock `bd` CLI leaves: `bd search` covers titles, `bd query` is structured-only, and nothing searches **notes, comments, or close reasons** — which is where a mature store keeps most of its knowledge. `bd memories` is indexed too (the plain CLI truncates memory bodies; this returns them whole).

---

## Key Features

- **Deep Verbatim Search**: Full Porter-stemmed FTS5 search across title, description, design, acceptance criteria, notes, dated author comments, close reasons, and memories.
- **Relational Neighborhood Graphs**: Surfaces 1-hop dependencies (`blocks`, `blocked-by`, `parent-child`, `supersedes`, `discovered-from`, `related`), cross-prose mention references, and GitHub issue/PR links (`#NNN`).
- **Transitive Blast Radius**: Query transitive dependency chains (`--blast <id>`) to see blockers, downstream dependents, and epic hierarchy before touching code.
- **Built-in Stdio MCP Server**: Zero-dependency JSON-RPC 2.0 stdio Model Context Protocol (MCP) server providing the `bd_explore` tool to modern AI coding assistants.
- **Multi-Target Platform Installer**: Automated discovery and setup for Claude Code, Gemini CLI, Antigravity IDE, OpenAI Codex, Cursor, and `AGENTS.md`.
- **Beads Persistent Memory Injection**: Automatically sets beads memory (`bd remember --key bd-explore`) so every `bd prime` session primes agents with `bd-explore` context.
- **Strict Output Budgeting**: Output character budget (`--budget 24000`) prevents context-window blowout in LLM workflows.
- **Zero Runtime Dependencies**: Pure Python 3.10+ standard library (`sqlite3`, `json`, `argparse`).

---

## Installation

### Standalone Shell Installer

Install `bd-explore` into `~/.local/bin` and automatically configure detected agent platforms:

```bash
# From repository clone
./install.sh

# Standalone uninstall
./install.sh --uninstall
```

### Python Package Installation

```bash
# Standard pip install
pip install .

# Editable install for development
pip install -e .
```

---

## Usage

### CLI Search

```bash
# Free text search across all fields (porter-stemmed FTS)
bd-explore "why did we re-point SYRP"

# Compose field filters with free text (codegraph-style)
bd-explore "hash refresh status:open type:task priority:1"
bd-explore "swap oracle epic:rpm5"

# Target specific store or force reindex
bd-explore --store ~/Projects/my-project "auth refactor"
bd-explore --rebuild

# Control limits and output budget
bd-explore -n 3 --budget 16000 "database migration"
```

### Supported Filters

| Filter | Syntax / Values | Description |
|---|---|---|
| `status:` | `open`, `in_progress`, `closed`, `deferred`, `all` | Filter by status (`all` searches closed beads with lower rank) |
| `type:` | `bug`, `feature`, `task`, `epic`, `chore` | Filter by issue type |
| `priority:` | `0`, `1`, `2`, `3`, `4` (or `P0`..`P4`) | Filter by priority level |
| `epic:` | `<id-or-suffix>` | Filter issues belonging to an epic |
| `id:` | `<id-or-substring>` | Match issues by ID (substring / prefix) |

> Non-filter tokens (e.g. `foo:bar`) automatically fall through to free-text search.

---

## Transitive Blast Radius

Compute the full transitive dependency graph for any bead:

```bash
bd-explore --blast 9o32
```

Outputs:
- **Upstream Blockers**: All issues directly or transitively blocking this bead.
- **Downstream Blocked**: All issues directly or transitively waiting on this bead.
- **Epic Ancestry**: Direct and ancestor epics.

---

## Stdio MCP Server

`bd-explore` includes a built-in JSON-RPC 2.0 stdio MCP server for agent integration. It supports both newline-delimited JSON (NDJSON) and HTTP-style `Content-Length:` header framing.

Run server directly:
```bash
bd-explore serve --mcp
# Or with explicit store:
bd-explore serve --mcp --store ~/Projects/my-project
```

### MCP Tool: `bd_explore`

Exposes the `bd_explore` tool with schema:
- `query` *(string)*: Search query string with optional field filters (`status:open type:task`).
- `blast` *(string)*: Bead ID to calculate transitive blast radius.
- `limit` *(integer, default 5)*: Maximum number of seed beads.
- `budget` *(integer, default 24000)*: Output character budget cap.
- `store` *(string, optional)*: Explicit store path or repository directory.

---

## Multi-Target Agent Installer

`bd-explore install` discovers installed AI developer tools, adds MCP configuration, injects marker-fenced agent guidelines, and injects beads persistent memory.

```bash
# Interactive setup (prompts for targets and location)
bd-explore install

# Automated non-interactive batch install
bd-explore install --yes

# Install for specific targets and location
bd-explore install --targets claude,gemini,cursor --location global --auto-allow --yes

# Uninstall configurations
bd-explore uninstall --yes

# Print MCP configuration snippet without modifying files
bd-explore print-config claude
bd-explore print-config cursor
```

### Supported Platforms

| Platform | MCP Configuration | Instructions & Rules |
|---|---|---|
| **Claude Code** | `~/.claude.json` / `.mcp.json` | `~/.claude/CLAUDE.md` / `CLAUDE.md` |
| **Gemini CLI / Antigravity CLI** | `~/.gemini/settings.json` / `.gemini/settings.json` | `~/.gemini/GEMINI.md` / `GEMINI.md` |
| **Antigravity IDE** | `~/.gemini/config/mcp_config.json` | IDE instructions / workspace rules |
| **OpenAI Codex** | `~/.codex/config.toml` | `~/.codex/AGENTS.md` |
| **Cursor** | `~/.cursor/mcp.json` / `.cursor/mcp.json` | `.cursor/rules/bd-explore.mdc` |
| **Generic Agent Rules** | — | `~/.config/AGENTS.md` / `AGENTS.md` |

### Marker-Fenced Instructions

Instructions are safely injected with marker fences for clean updates and uninstalls:

```markdown
<!-- BD_EXPLORE_START -->
## bd-explore

In repositories with a beads store (a `.beads/` directory exists at the repo root), reach for `bd-explore` BEFORE searching raw files or relying only on `bd search`:

- **MCP tool** (when available): `bd_explore` answers questions about beads/issues/decisions/memories verbatim — description, notes, comments, close reason, plus relationship neighborhood under an output budget.
- **Shell** (always works): `bd-explore "<query>"` (e.g. `bd-explore "why did we re-point SYRP status:open"`, `bd-explore --blast <id>`).

If there is no `.beads/` directory, skip bd-explore.
<!-- BD_EXPLORE_END -->
```

---

## What Gets Indexed

| Content | Source | Notes |
|---|---|---|
| Title, description, design, acceptance criteria | `.beads/issues.jsonl` | Primary issue content |
| Notes, close reason | `.beads/issues.jsonl` | Critical context and postmortems |
| Author comments | `.beads/issues.jsonl` | Timestamped conversation history |
| Full memory bodies | `bd memories --json` | Persistent memory records |
| Explicit dependency edges | `dependencies` array | `blocks`, `parent-child`, `supersedes`, `related`, etc. |
| **Mention edges** | Prose cross-references | Mined regex matches of bead IDs cited across issue prose |
| **GitHub references** | Prose cross-references | Mined `#NNN` issue and pull request references |

---

## Design Principles

1. **Derived and disposable.** Reads `.beads/issues.jsonl` (requires `export.auto: true`) into a SQLite FTS5 index under `~/.cache/bd-explore/`, rebuilt automatically when the export changes. The beads store remains the sole source of truth; delete the cache freely.
2. **Staleness is first-class.** Every hit is stamped `[STATUS · P<n> · type · updated YYYY-MM-DD]`.
3. **Closed beads included by default.** History is most of the value; closed hits rank below open ones at equal relevance. Use `status:open` to narrow.
4. **Context window friendly.** Strictly enforces output character budgets to fit comfortably into agent conversations.

---

## Testing

Run the full test suite using Python's standard library `unittest`:

```bash
PYTHONPATH=src python3 -m unittest discover tests -v
```

---

## Requirements

- Python 3.10+
- SQLite with FTS5 virtual table support (standard in official CPython distributions)

---

## License

MIT License. See [LICENSE](LICENSE) for details.
