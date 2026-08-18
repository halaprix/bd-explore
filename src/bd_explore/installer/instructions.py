"""Marker-fenced agent instructions injection and removal."""

from __future__ import annotations

from pathlib import Path
from bd_explore.installer.shared import atomic_write_file

__all__ = [
    "BD_EXPLORE_SECTION_START",
    "BD_EXPLORE_SECTION_END",
    "BD_EXPLORE_INSTRUCTIONS_BLOCK",
    "replace_or_append_marked_section",
    "upsert_instructions_entry",
    "remove_marked_section",
]

BD_EXPLORE_SECTION_START = "<!-- BD_EXPLORE_START -->"
BD_EXPLORE_SECTION_END = "<!-- BD_EXPLORE_END -->"

BD_EXPLORE_INSTRUCTIONS_BLOCK = f"""{BD_EXPLORE_SECTION_START}
## bd-explore

In repositories with a beads store (a `.beads/` directory exists at the repo root), reach for `bd-explore` BEFORE searching raw files or relying only on `bd search`:

- **MCP tool** (when available): `bd_explore` answers questions about beads/issues/decisions/memories verbatim — description, notes, comments, close reason, plus relationship neighborhood under an output budget.
- **Shell** (always works): `bd-explore "<query>"` (e.g. `bd-explore "why did we re-point SYRP status:open"`, `bd-explore --blast <id>`).

If there is no `.beads/` directory, skip bd-explore.
{BD_EXPLORE_SECTION_END}"""


def replace_or_append_marked_section(
    file_path: Path,
    body: str,
    start_marker: str,
    end_marker: str,
) -> str:
    """Insert or update a marked section in file_path.
    Returns 'created', 'updated', 'appended', or 'unchanged'.
    """
    if not file_path.exists():
        atomic_write_file(file_path, body + "\n")
        return "created"

    content = file_path.read_text(encoding="utf-8")
    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker)

    if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
        full_end = end_idx + len(end_marker)
        existing_block = content[start_idx:full_end]
        if existing_block == body:
            return "unchanged"
        before = content[:start_idx]
        after = content[full_end:]
        atomic_write_file(file_path, before + body + after)
        return "updated"

    trimmed = content.rstrip()
    sep = "\n\n" if trimmed else ""
    atomic_write_file(file_path, trimmed + sep + body + "\n")
    return "appended"


def upsert_instructions_entry(file_path: Path) -> dict[str, str]:
    """Upsert standard bd-explore instructions into target file."""
    action = replace_or_append_marked_section(
        file_path,
        BD_EXPLORE_INSTRUCTIONS_BLOCK,
        BD_EXPLORE_SECTION_START,
        BD_EXPLORE_SECTION_END,
    )
    return {"path": str(file_path), "action": "updated" if action == "appended" else action}


def remove_marked_section(file_path: Path, start_marker: str, end_marker: str) -> str:
    """Remove a marked section from file_path, deleting the file if it becomes empty.
    Returns 'removed', 'not-found', or 'kept'.
    """
    if not file_path.exists():
        return "kept"
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        return "kept"

    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return "not-found"

    before = content[:start_idx].rstrip()
    after = content[end_idx + len(end_marker):].lstrip()
    joined = before + ("\n\n" if before and after else "") + after

    if not joined.strip():
        try:
            file_path.unlink()
        except OSError:
            pass
    else:
        atomic_write_file(file_path, joined.strip() + "\n")
    return "removed"
