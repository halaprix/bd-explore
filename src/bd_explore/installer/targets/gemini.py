"""Gemini Code Assist / CLI installer target."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bd_explore.installer.instructions import (
    BD_EXPLORE_SECTION_END,
    BD_EXPLORE_SECTION_START,
    remove_marked_section,
    upsert_instructions_entry,
)
from bd_explore.installer.shared import read_json_file, write_json_file

__all__ = ["GeminiTarget"]


class GeminiTarget:
    name = "gemini"
    display_name = "Gemini Code Assist / CLI"

    def __init__(self, home_dir: Path | None = None, project_dir: Path | None = None) -> None:
        self.home_dir = home_dir or Path.home()
        self.project_dir = project_dir or Path.cwd()

    def is_installed(self) -> bool:
        """Check if Gemini configurations exist."""
        return (
            (self.home_dir / ".gemini").exists()
            or (self.project_dir / ".gemini").exists()
            or (self.project_dir / "GEMINI.md").exists()
        )

    def get_mcp_config(self) -> dict[str, Any]:
        """Return the JSON dictionary for Gemini's MCP configuration."""
        return {
            "mcpServers": {
                "bd-explore": {
                    "command": "bd-explore",
                    "args": ["serve", "--mcp"],
                }
            }
        }

    def install(self, location: str = "global", auto_allow: bool = False) -> dict[str, Any]:
        files: list[dict[str, str]] = []
        is_global = location == "global"

        try:
            settings_path = (
                self.home_dir / ".gemini" / "settings.json"
                if is_global
                else self.project_dir / ".gemini" / "settings.json"
            )
            cfg = read_json_file(settings_path)
            servers = cfg.setdefault("mcpServers", {})
            servers["bd-explore"] = {"command": "bd-explore", "args": ["serve", "--mcp"]}
            write_json_file(settings_path, cfg)
            files.append({"path": str(settings_path), "action": "updated"})

            gemini_md = (
                self.home_dir / ".gemini" / "GEMINI.md"
                if is_global
                else self.project_dir / "GEMINI.md"
            )
            res = upsert_instructions_entry(gemini_md)
            files.append(res)

            return {"target": self.name, "files": files, "status": "ok"}
        except Exception as e:
            return {"target": self.name, "files": files, "status": "error", "message": str(e), "error": str(e)}

    def uninstall(self, location: str = "global") -> dict[str, Any]:
        files: list[dict[str, str]] = []
        is_global = location == "global"

        try:
            settings_path = (
                self.home_dir / ".gemini" / "settings.json"
                if is_global
                else self.project_dir / ".gemini" / "settings.json"
            )
            if settings_path.exists():
                cfg = read_json_file(settings_path)
                if "mcpServers" in cfg and "bd-explore" in cfg["mcpServers"]:
                    del cfg["mcpServers"]["bd-explore"]
                    write_json_file(settings_path, cfg)
                    files.append({"path": str(settings_path), "action": "updated"})

            gemini_md = (
                self.home_dir / ".gemini" / "GEMINI.md"
                if is_global
                else self.project_dir / "GEMINI.md"
            )
            if gemini_md.exists():
                act = remove_marked_section(gemini_md, BD_EXPLORE_SECTION_START, BD_EXPLORE_SECTION_END)
                files.append({"path": str(gemini_md), "action": act})

            return {"target": self.name, "files": files, "status": "ok"}
        except Exception as e:
            return {"target": self.name, "files": files, "status": "error", "message": str(e), "error": str(e)}
