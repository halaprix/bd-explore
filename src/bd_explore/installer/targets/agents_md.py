"""Generic AGENTS.md installer target."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bd_explore.installer.instructions import (
    BD_EXPLORE_SECTION_END,
    BD_EXPLORE_SECTION_START,
    remove_marked_section,
    upsert_instructions_entry,
)

__all__ = ["AgentsMdTarget"]


class AgentsMdTarget:
    name = "agents_md"
    display_name = "AGENTS.md (Generic Agent Standard)"

    def __init__(self, home_dir: Path | None = None, project_dir: Path | None = None) -> None:
        self.home_dir = home_dir or Path.home()
        self.project_dir = project_dir or Path.cwd()

    def is_installed(self) -> bool:
        """Check if AGENTS.md files exist in home or project."""
        return (
            (self.home_dir / ".config" / "AGENTS.md").exists()
            or (self.project_dir / "AGENTS.md").exists()
        )

    def get_mcp_config(self) -> str:
        """Return the markdown instructions representation for AGENTS.md."""
        return "## bd-explore Agent Instructions\n(See AGENTS.md)"

    def install(self, location: str = "global", auto_allow: bool = False) -> dict[str, Any]:
        is_global = location == "global"
        try:
            target_path = self.home_dir / ".config" / "AGENTS.md" if is_global else self.project_dir / "AGENTS.md"
            res = upsert_instructions_entry(target_path)
            return {"target": self.name, "files": [res], "status": "ok"}
        except Exception as e:
            return {"target": self.name, "files": [], "status": "error", "message": str(e), "error": str(e)}

    def uninstall(self, location: str = "global") -> dict[str, Any]:
        is_global = location == "global"
        try:
            target_path = self.home_dir / ".config" / "AGENTS.md" if is_global else self.project_dir / "AGENTS.md"
            if target_path.exists():
                act = remove_marked_section(target_path, BD_EXPLORE_SECTION_START, BD_EXPLORE_SECTION_END)
                return {"target": self.name, "files": [{"path": str(target_path), "action": act}], "status": "ok"}
            return {"target": self.name, "files": [], "status": "ok"}
        except Exception as e:
            return {"target": self.name, "files": [], "status": "error", "message": str(e), "error": str(e)}
