"""Codex CLI installer target."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from bd_explore.installer.instructions import (
    BD_EXPLORE_SECTION_END,
    BD_EXPLORE_SECTION_START,
    remove_marked_section,
    upsert_instructions_entry,
)
from bd_explore.installer.shared import atomic_write_file

__all__ = ["CodexTarget"]

CODEX_TOML_BLOCK = """[mcp_servers.bd-explore]
command = "bd-explore"
args = ["serve", "--mcp"]
"""


class CodexTarget:
    name = "codex"
    display_name = "Codex CLI"

    def __init__(self, home_dir: Path | None = None, project_dir: Path | None = None) -> None:
        self.home_dir = home_dir or Path.home()
        self.project_dir = project_dir or Path.cwd()

    def is_installed(self) -> bool:
        """Check if Codex configurations exist."""
        return (
            (self.home_dir / ".codex").exists()
            or (self.project_dir / ".codex").exists()
            or (self.project_dir / "AGENTS.md").exists()
        )

    def get_mcp_config(self) -> str:
        """Return the TOML configuration block for Codex."""
        return CODEX_TOML_BLOCK

    def install(self, location: str = "global", auto_allow: bool = False) -> dict[str, Any]:
        files: list[dict[str, str]] = []
        is_global = location == "global"

        try:
            config_path = (
                self.home_dir / ".codex" / "config.toml"
                if is_global
                else self.project_dir / ".codex" / "config.toml"
            )
            existing_content = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
            pattern = re.compile(r"\[mcp_servers\.bd-explore\](?:\n(?!\s*\[).*)*", re.MULTILINE)

            if pattern.search(existing_content):
                new_content = pattern.sub(CODEX_TOML_BLOCK.strip(), existing_content)
            else:
                trimmed = existing_content.rstrip()
                sep = "\n\n" if trimmed else ""
                new_content = trimmed + sep + CODEX_TOML_BLOCK

            atomic_write_file(config_path, new_content.strip() + "\n")
            files.append({"path": str(config_path), "action": "updated"})

            # Instructions in AGENTS.md
            agents_md = (
                self.home_dir / ".codex" / "AGENTS.md"
                if is_global
                else self.project_dir / "AGENTS.md"
            )
            res = upsert_instructions_entry(agents_md)
            files.append(res)

            return {"target": self.name, "files": files, "status": "ok"}
        except Exception as e:
            return {"target": self.name, "files": files, "status": "error", "error": str(e)}

    def uninstall(self, location: str = "global") -> dict[str, Any]:
        files: list[dict[str, str]] = []
        is_global = location == "global"

        try:
            config_path = (
                self.home_dir / ".codex" / "config.toml"
                if is_global
                else self.project_dir / ".codex" / "config.toml"
            )
            if config_path.exists():
                content = config_path.read_text(encoding="utf-8")
                pattern = re.compile(r"\[mcp_servers\.bd-explore\](?:\n(?!\s*\[).*)*", re.MULTILINE)
                cleaned = pattern.sub("", content).strip()
                if not cleaned:
                    try:
                        config_path.unlink()
                    except OSError:
                        pass
                    files.append({"path": str(config_path), "action": "removed"})
                else:
                    atomic_write_file(config_path, cleaned + "\n")
                    files.append({"path": str(config_path), "action": "updated"})

            agents_md = (
                self.home_dir / ".codex" / "AGENTS.md"
                if is_global
                else self.project_dir / "AGENTS.md"
            )
            if agents_md.exists():
                act = remove_marked_section(agents_md, BD_EXPLORE_SECTION_START, BD_EXPLORE_SECTION_END)
                files.append({"path": str(agents_md), "action": act})

            return {"target": self.name, "files": files, "status": "ok"}
        except Exception as e:
            return {"target": self.name, "files": files, "status": "error", "error": str(e)}
