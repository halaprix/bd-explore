"""Beads persistent memory injector (bd remember / bd forget)."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

__all__ = [
    "MEMORY_KEY",
    "MEMORY_BODY",
    "is_bd_available",
    "get_memory_content",
    "inject_beads_memory",
    "remove_beads_memory",
]

MEMORY_KEY = "bd-explore"
MEMORY_BODY = (
    "Use 'bd-explore <query>' or the 'bd_explore' MCP tool to query beads issues, "
    "notes, comments, close reasons, and relationship graphs."
)


def is_bd_available() -> bool:
    """Check if the bd CLI binary is available on PATH."""
    return shutil.which("bd") is not None


def get_memory_content() -> str:
    """Return the memory prompt injected into beads."""
    return MEMORY_BODY


def inject_beads_memory(cwd: Any = None) -> dict[str, Any]:
    """Inject bd-explore guidance into beads memory using bd remember."""
    if not is_bd_available():
        return {"status": "skipped", "reason": "bd CLI not found on PATH", "message": "bd CLI not found on PATH"}
    try:
        res = subprocess.run(
            ["bd", "remember", MEMORY_BODY, "--key", MEMORY_KEY],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=cwd,
        )
        if res.returncode == 0:
            return {"status": "injected", "key": MEMORY_KEY, "message": "injected"}
        return {"status": "error", "message": res.stderr.strip() or "failed to execute bd remember"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def remove_beads_memory(cwd: Any = None) -> dict[str, Any]:
    """Remove bd-explore guidance from beads memory using bd forget."""
    if not is_bd_available():
        return {"status": "skipped", "reason": "bd CLI not found on PATH", "message": "bd CLI not found on PATH"}
    try:
        res = subprocess.run(
            ["bd", "forget", MEMORY_KEY],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=cwd,
        )
        if res.returncode == 0:
            return {"status": "removed", "message": "removed"}
        return {"status": "not-found", "message": res.stderr.strip() or "memory key not found"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
