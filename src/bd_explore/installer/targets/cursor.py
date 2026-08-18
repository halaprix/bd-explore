"""Cursor Editor installer target."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bd_explore.installer.instructions import (
    BD_EXPLORE_INSTRUCTIONS_BLOCK,
    BD_EXPLORE_SECTION_END,
    BD_EXPLORE_SECTION_START,
    remove_marked_section,
)
from bd_explore.installer.shared import atomic_write_file, read_json_file, write_json_file

__all__ = ["CursorTarget"]

CURSOR_MDC_RULE = f"""---
description: bd-explore Beads Store Assistant
globs: *
alwaysApply: true
---

{BD_EXPLORE_INSTRUCTIONS_BLOCK}
"""


class CursorTarget:
    name = "cursor"
    display_name = "Cursor Editor"

    def __init__(self, home_dir: Path | None = None, project_dir: Path | None = None) -> None:
        self.home_dir = home_dir or Path.home()
        self.project_dir = project_dir or Path.cwd()

    def is_installed(self) -> bool:
        """Check if Cursor configurations exist."""
        return (
            (self.home_dir / ".cursor").exists()
            or (self.project_dir / ".cursor").exists()
        )

    def get_mcp_config(self) -> dict[str, Any]:
        """Return the JSON dictionary for Cursor's MCP configuration."""
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
            config_path = (
                self.home_dir / ".cursor" / "mcp.json"
                if is_global
                else self.project_dir / ".cursor" / "mcp.json"
            )
            cfg = read_json_file(config_path)
            servers = cfg.setdefault("mcpServers", {})
            servers["bd-explore"] = {"command": "bd-explore", "args": ["serve", "--mcp"]}
            write_json_file(config_path, cfg)
            files.append({"path": str(config_path), "action": "updated"})

            if not is_global or (self.project_dir / ".cursor").exists():
                rule_path = self.project_dir / ".cursor" / "rules" / "bd-explore.mdc"
                atomic_write_file(rule_path, CURSOR_MDC_RULE)
                files.append({"path": str(rule_path), "action": "updated"})

            return {"target": self.name, "files": files, "status": "ok"}
        except Exception as e:
            return {"target": self.name, "files": files, "status": "error", "message": str(e), "error": str(e)}

    def uninstall(self, location: str = "global") -> dict[str, Any]:
        files: list[dict[str, str]] = []
        is_global = location == "global"

        try:
            config_path = (
                self.home_dir / ".cursor" / "mcp.json"
                if is_global
                else self.project_dir / ".cursor" / "mcp.json"
            )
            if config_path.exists():
                cfg = read_json_file(config_path)
                if "mcpServers" in cfg and "bd-explore" in cfg["mcpServers"]:
                    del cfg["mcpServers"]["bd-explore"]
                    write_json_file(config_path, cfg)
                    files.append({"path": str(config_path), "action": "updated"})

            rule_path = self.project_dir / ".cursor" / "rules" / "bd-explore.mdc"
            if rule_path.exists():
                try:
                    rule_path.unlink()
                    files.append({"path": str(rule_path), "action": "removed"})
                except OSError:
                    pass

            cursorrules = self.project_dir / ".cursorrules"
            if cursorrules.exists():
                act = remove_marked_section(cursorrules, BD_EXPLORE_SECTION_START, BD_EXPLORE_SECTION_END)
                files.append({"path": str(cursorrules), "action": act})

            return {"target": self.name, "files": files, "status": "ok"}
        except Exception as e:
            return {"target": self.name, "files": files, "status": "error", "message": str(e), "error": str(e)}
