# bd-explore

Ask a [beads](https://github.com/gastownhall/beads) store questions, the way
`codegraph explore` asks a codebase: one call returns the most relevant beads
**verbatim** — description, notes, comments, close reason — plus each hit's
relationship neighborhood, under an output budget.

Fills the gap the stock `bd` CLI leaves: `bd search` covers titles, `bd query`
is structured-only, and nothing searches **notes, comments, or close reasons**
— which is where a mature store keeps most of its knowledge. `bd memories` is
indexed too (the plain CLI truncates memory bodies; this returns them whole).

## Design rules

- **Derived and disposable.** Reads the store's auto-exported
  `.beads/issues.jsonl` (requires `export.auto: true`) plus `bd memories --json`
  into a SQLite FTS5 index under `~/.cache/bd-explore/`, rebuilt automatically
  whenever the export changes. The beads store stays the sole authority;
  delete the cache freely. Nothing is ever written to the store.
- **Staleness is first-class.** Every hit is stamped
  `[STATUS · P<n> · type · updated YYYY-MM-DD]`. Bead claims age badly — read
  the stamp before trusting the body.
- **Closed beads included by default.** History is most of the value; closed
  hits rank below open ones at equal relevance. `status:open` to narrow,
  `status:all` is the default behavior spelled out.

## Usage

```bash
# free text — porter-stemmed FTS over title/description/notes/comments/close reason
bd_explore.py "why did we re-point SYRP"

# field filters compose with free text (codegraph-style)
bd_explore.py "hash refresh status:open type:task priority:1"
bd_explore.py "swap oracle epic:rpm5"

# blast radius: transitive blocks/blocked-by + epic ancestry
bd_explore.py --blast 9o32

# force reindex; store discovery: walks up from cwd, or --store / BD_EXPLORE_STORE
bd_explore.py --rebuild
bd_explore.py --store ~/Projects/some-repo "query"
```

Filters: `status:` `type:` `priority:` `epic:` `id:`. Unknown `foo:bar` tokens
fall through to free text. `-n` limits hits (default 5), `--budget` caps output
characters (default 24k) — sized for LLM-agent context windows.

## What gets indexed

| Content | Source |
|---|---|
| title, description, design, acceptance, notes, comments, close reason | `.beads/issues.jsonl` |
| memories (full bodies) | `bd memories --json` (optional; degrades gracefully) |
| dependency edges: parent-child, blocks, discovered-from, supersedes, related | `dependencies` in the export |
| **mention edges** — bead ids cited inside other beads' prose | mined at index time |
| GitHub issue/PR references (`#NNN`) | mined at index time |

The mention edges are the quiet win: dated handoff notes routinely cite other
beads by id, and no stock tool follows those references.

## Requirements

Python 3.10+ with SQLite FTS5 (stock CPython builds have it). No dependencies.
