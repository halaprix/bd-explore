# CONTEXT.md — Domain glossary for bd-explore

- **Explorer** — the deep module behind the explore pipeline (`src/bd_explore/explorer.py`).
  Interface: `explore(query, store=None, limit=None, budget=None, rebuild=False) → str` and
  `blast(bead_id, store=None, budget=None, rebuild=False) → str`, plus `ExploreError`, whose
  `str()` is the user-facing message. Owns store discovery, index freshness, connection
  lifetime, limit/budget defaulting and clamping, and canonical error text. `cli.py` and
  `mcp.py` are thin adapters at this seam: they parse arguments / frame JSON-RPC and present
  the Explorer's strings.
- **Bead** — one issue record in the beads store (`.beads/issues.jsonl`).
- **Store** — the resolved `issues.jsonl` export a query runs against (explicit path, `BD_EXPLORE_STORE`, or discovered by walking up from cwd).
- **Blast radius** — the transitive dependency closure of one bead: blocked-by/blocks chains plus epic ancestry.
- **Neighborhood** — a bead's 1-hop relationship edges, both directions, grouped by display label.
- **Budget** — the strict output character cap every explore response must respect (default 24 000, clamped to a minimum of 100).
