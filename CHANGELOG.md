# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added
- `explorer.py`: the explore pipeline behind one deep interface — `explore()` / `blast()` plus a typed `ExploreError`. The CLI and MCP server are now thin adapters over it.
- `hydrate()` / `render()` (and `hydrate_blast()` / `render_blast()`) split in `search.py`: batched fetching (two queries, no N+1) and pure, connection-free formatting.
- `CONTEXT.md` domain glossary.
- GitHub Pages documentation site.

### Changed
- Unified error messages across CLI and MCP: canonical `bd-explore: …` text, no per-transport wrappers.
- CLI `--blast` now honors `--budget` (previously ignored).
- CLI and MCP share limit/budget coercion; budget clamps to a 100-char minimum.
- CI matrix extended to Python 3.14.

## [0.1.0] — 2026-08-18

### Added
- FTS5 full-text search over beads issues: title, description, design, acceptance criteria, notes, dated comments, close reasons, and `bd memories`.
- Field filters (`status:`, `type:`, `priority:`, `epic:`, `id:`) composable with free text.
- Relationship neighborhood per hit: dependency edges, mined mention edges, GitHub `#NNN` refs.
- Transitive blast radius (`--blast <id>`): upstream blockers, downstream dependents, epic ancestry.
- Strict output character budgeting for LLM context windows.
- Zero-dependency stdio JSON-RPC 2.0 MCP server (`bd-explore serve`), NDJSON and `Content-Length` framing.
- Multi-target agent installer (`bd-explore install`): Claude Code, Gemini CLI, Antigravity, Codex, Cursor, `AGENTS.md`; marker-fenced instructions and beads memory injection.
- Derived, disposable SQLite cache under `~/.cache/bd-explore/`, rebuilt automatically when the export changes.
