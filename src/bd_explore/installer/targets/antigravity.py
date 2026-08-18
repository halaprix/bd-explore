"""Google Antigravity installer target."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bd_explore.installer.shared import read_json_file, write_json_file

__all__ = ["AntigravityTarget"]


class AntigravityTarget:
    name = "antigravity"
    display_name = "Google Antigravity"

    def __init__(self, home_dir: Path | None = None, project_dir: Path | None = None) -> None:
        self.home_dir = home_dir or Path.home()
        self.project_dir = project_dir or Path.cwd()

    def is_installed(self) -> bool:
        """Check if Antigravity configurations or directories exist."""
        return (
            (self.home_dir / ".gemini" / "config").exists()
            or (self.home_dir / ".gemini" / "antigravity").exists()
            or (self.home_dir / ".gemini" / "antigravity-cli").exists()
            or (self.project_dir / ".gemini" / "config").exists()
        )

    def get_mcp_config(self) -> dict[str, Any]:
        """Return the JSON dictionary for Antigravity's MCP configuration (no type field)."""
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
            # Unified config
            config_path = (
                self.home_dir / ".gemini" / "config" / "mcp_config.json"
                if is_global
                else self.project_dir / ".gemini" / "config" / "mcp_config.json"
            )
            cfg = read_json_file(config_path)
            servers = cfg.setdefault("mcpServers", {})
            servers["bd-explore"] = {"command": "bd-explore", "args": ["serve", "--mcp"]}
            write_json_file(config_path, cfg)
            files.append({"path": str(config_path), "action": "updated"})

            # Legacy fallback in home if present
            if is_global:
                legacy_path = self.home_dir / ".gemini" / "antigravity" / "mcp_config.json"
                if legacy_path.parent.exists() or legacy_path.exists():
                    leg_cfg = read_json_file(legacy_path)
                    leg_servers = leg_cfg.setdefault("mcpServers", {})
                    leg_servers["bd-explore"] = {"command": "bd-explore", "args": ["serve", "--mcp"]}
                    write_json_file(legacy_path, leg_cfg)
                    files.append({"path": str(legacy_path), "action": "updated"})

            return {"target": self.name, "files": files, "status": "ok"}
        except Exception as e:
            return {"target": self.name, "files": files, "status": "error", "message": str(e), "error": str(e)}

    def uninstall(self, location: str = "global") -> dict[str, Any]:
        files: list[dict[str, str]] = []
        is_global = location == "global"

        try:
            config_path = (
                self.home_dir / ".gemini" / "config" / "mcp_config.json"
                if is_global
                else self.project_dir / ".gemini" / "config" / "mcp_config.json"
            )
            if config_path.exists():
                cfg = read_json_file(config_path)
                if "mcpServers" in cfg and "bd-explore" in cfg["mcpServers"]:
                    del cfg["mcpServers"]["bd-explore"]
                    write_json_file(config_path, cfg)
                    files.append({"path": str(config_path), "action": "updated"})

            if is_global:
                legacy_path = self.home_dir / ".gemini" / "antigravity" / "mcp_config.json"
                if legacy_path.exists():
                    leg_cfg = read_json_file(legacy_path)
                    if "mcpServers" in leg_cfg and "bd-explore" in leg_cfg["mcpServers"]:
                        del leg_cfg["mcpServers"]["bd-explore"]
                        write_json_file(legacy_path, leg_cfg)
                        files.append({"path": str(legacy_path), "action": "updated"})

            return {"target": self.name, "files": files, "status": "ok"}
        except Exception as e:
            return {"target": self.name, "files": files, "status": "error", "message": str(e), "error": str(e)}
