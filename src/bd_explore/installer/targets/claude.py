"""Claude Desktop and Claude Code installer target."""

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

__all__ = ["ClaudeTarget"]


class ClaudeTarget:
    name = "claude"
    display_name = "Anthropic Claude (Desktop & Code)"

    def __init__(self, home_dir: Path | None = None, project_dir: Path | None = None) -> None:
        self.home_dir = home_dir or Path.home()
        self.project_dir = project_dir or Path.cwd()

    def is_installed(self) -> bool:
        """Check if Claude configurations exist."""
        return (
            (self.home_dir / ".claude.json").exists()
            or (self.home_dir / ".claude").exists()
            or (self.project_dir / ".mcp.json").exists()
            or (self.project_dir / "CLAUDE.md").exists()
        )

    def get_mcp_config(self) -> dict[str, Any]:
        """Return the JSON dictionary for Claude's MCP configuration."""
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
            config_path = self.home_dir / ".claude.json" if is_global else self.project_dir / ".mcp.json"
            cfg = read_json_file(config_path)
            servers = cfg.setdefault("mcpServers", {})
            servers["bd-explore"] = {"command": "bd-explore", "args": ["serve", "--mcp"]}
            write_json_file(config_path, cfg)
            files.append({"path": str(config_path), "action": "updated"})

            if auto_allow:
                settings_path = (
                    self.home_dir / ".claude" / "settings.json"
                    if is_global
                    else self.project_dir / ".claude" / "settings.json"
                )
                sett = read_json_file(settings_path)
                perms = sett.setdefault("permissions", {})
                allow = perms.setdefault("allow", [])
                if "mcp__bd-explore__*" not in allow:
                    allow.append("mcp__bd-explore__*")
                auto = sett.setdefault("autoApprove", [])
                if "mcp__bd-explore__*" not in auto:
                    auto.append("mcp__bd-explore__*")
                write_json_file(settings_path, sett)
                files.append({"path": str(settings_path), "action": "updated"})

            # Instructions in CLAUDE.md
            claude_md = (
                self.home_dir / ".claude" / "CLAUDE.md"
                if is_global
                else self.project_dir / "CLAUDE.md"
            )
            res = upsert_instructions_entry(claude_md)
            files.append(res)

            return {"target": self.name, "files": files, "status": "ok"}
        except Exception as e:
            return {"target": self.name, "files": files, "status": "error", "error": str(e)}

    def uninstall(self, location: str = "global") -> dict[str, Any]:
        files: list[dict[str, str]] = []
        is_global = location == "global"

        try:
            config_path = self.home_dir / ".claude.json" if is_global else self.project_dir / ".mcp.json"
            if config_path.exists():
                cfg = read_json_file(config_path)
                if "mcpServers" in cfg and "bd-explore" in cfg["mcpServers"]:
                    del cfg["mcpServers"]["bd-explore"]
                    write_json_file(config_path, cfg)
                    files.append({"path": str(config_path), "action": "updated"})

            settings_path = (
                self.home_dir / ".claude" / "settings.json"
                if is_global
                else self.project_dir / ".claude" / "settings.json"
            )
            if settings_path.exists():
                sett = read_json_file(settings_path)
                changed = False
                if "permissions" in sett and "allow" in sett["permissions"]:
                    if "mcp__bd-explore__*" in sett["permissions"]["allow"]:
                        sett["permissions"]["allow"].remove("mcp__bd-explore__*")
                        changed = True
                if "autoApprove" in sett and "mcp__bd-explore__*" in sett["autoApprove"]:
                    sett["autoApprove"].remove("mcp__bd-explore__*")
                    changed = True
                if changed:
                    write_json_file(settings_path, sett)
                    files.append({"path": str(settings_path), "action": "updated"})

            claude_md = (
                self.home_dir / ".claude" / "CLAUDE.md"
                if is_global
                else self.project_dir / "CLAUDE.md"
            )
            if claude_md.exists():
                act = remove_marked_section(claude_md, BD_EXPLORE_SECTION_START, BD_EXPLORE_SECTION_END)
                files.append({"path": str(claude_md), "action": act})

            return {"target": self.name, "files": files, "status": "ok"}
        except Exception as e:
            return {"target": self.name, "files": files, "status": "error", "error": str(e)}
