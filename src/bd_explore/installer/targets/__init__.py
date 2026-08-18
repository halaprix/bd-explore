"""Target registry, detection, and orchestration for agent installers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bd_explore.installer.memory import inject_beads_memory, remove_beads_memory
from bd_explore.installer.targets.agents_md import AgentsMdTarget
from bd_explore.installer.targets.antigravity import AntigravityTarget
from bd_explore.installer.targets.claude import ClaudeTarget
from bd_explore.installer.targets.codex import CodexTarget
from bd_explore.installer.targets.cursor import CursorTarget
from bd_explore.installer.targets.gemini import GeminiTarget

__all__ = [
    "TARGET_REGISTRY",
    "TARGET_ALIASES",
    "get_target",
    "detect_installed_targets",
    "print_config",
    "run_installer",
    "run_uninstaller",
]

TARGET_REGISTRY: dict[str, type] = {
    "claude": ClaudeTarget,
    "gemini": GeminiTarget,
    "antigravity": AntigravityTarget,
    "codex": CodexTarget,
    "cursor": CursorTarget,
    "agents_md": AgentsMdTarget,
}

TARGET_ALIASES: dict[str, str] = {
    "agents": "agents_md",
    "agents.md": "agents_md",
    "agy": "antigravity",
}


def normalize_target_name(name: str) -> str:
    """Normalize target names and aliases."""
    cleaned = name.strip().lower()
    return TARGET_ALIASES.get(cleaned, cleaned)


def get_target(name: str, home_dir: Path | None = None, project_dir: Path | None = None) -> Any:
    """Instantiate a target by name."""
    norm = normalize_target_name(name)
    target_cls = TARGET_REGISTRY.get(norm)
    if not target_cls:
        raise ValueError(f"Unknown target: '{name}'. Available: {', '.join(TARGET_REGISTRY.keys())}")
    return target_cls(home_dir=home_dir, project_dir=project_dir)


def detect_installed_targets(home_dir: Path | None = None, project_dir: Path | None = None) -> list[str]:
    """Auto-detect which agent targets exist in the environment."""
    detected = []
    for name, cls in TARGET_REGISTRY.items():
        t = cls(home_dir=home_dir, project_dir=project_dir)
        if t.is_installed():
            detected.append(name)
    return detected


def print_config(target_name: str) -> str:
    """Return the configuration snippet for a given target."""
    t = get_target(target_name)
    cfg = t.get_mcp_config()
    if isinstance(cfg, dict):
        return json.dumps(cfg, indent=2)
    return str(cfg).strip()


def run_installer(
    targets: list[str] | None = None,
    location: str = "global",
    auto_allow: bool = False,
    yes: bool = False,
    home_dir: Path | None = None,
    project_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute installation across target agents and inject beads memory."""
    if targets and "all" in [t.lower() for t in targets]:
        target_names = list(TARGET_REGISTRY.keys())
    elif targets:
        target_names = targets
    else:
        target_names = detect_installed_targets(home_dir=home_dir, project_dir=project_dir)

    if not target_names:
        return {
            "status": "no_targets_detected",
            "location": location,
            "targets": [],
            "memory": {"action": "skipped", "message": "No agent platforms detected"},
            "message": "No supported agent platforms detected in environment. Use -t <target> (e.g. -t claude) or -t all to install.",
        }

    results = []
    for t_name in target_names:
        try:
            target = get_target(t_name, home_dir=home_dir, project_dir=project_dir)
            res = target.install(location=location, auto_allow=auto_allow)
            results.append(res)
        except Exception as e:
            results.append({"target": t_name, "status": "error", "message": str(e), "files": []})

    mem_res = inject_beads_memory()

    return {
        "status": "ok",
        "location": location,
        "targets": results,
        "memory": mem_res,
    }


def run_uninstaller(
    targets: list[str] | None = None,
    location: str = "global",
    home_dir: Path | None = None,
    project_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute uninstallation across target agents and remove beads memory."""
    target_names = targets or list(TARGET_REGISTRY.keys())

    results = []
    for t_name in target_names:
        try:
            target = get_target(t_name, home_dir=home_dir, project_dir=project_dir)
            res = target.uninstall(location=location)
            results.append(res)
        except Exception as e:
            results.append({"target": t_name, "status": "error", "message": str(e), "files": []})

    mem_res = remove_beads_memory()

    return {
        "status": "ok",
        "location": location,
        "targets": results,
        "memory": mem_res,
    }
