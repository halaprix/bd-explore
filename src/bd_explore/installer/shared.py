"""Shared file manipulation and atomic I/O helpers for installer targets."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

__all__ = [
    "atomic_write_file",
    "read_json_file",
    "write_json_file",
    "json_deep_equal",
]


def atomic_write_file(file_path: Path, content: str) -> None:
    """Atomically write content to file_path using a temporary file in the same directory."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(f"{file_path.name}.tmp.{os.getpid()}")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        tmp_path.replace(file_path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def read_json_file(file_path: Path) -> dict[str, Any]:
    """Read JSON from file_path, returning empty dict if file does not exist.
    If the file exists but contains invalid JSON, creates a .backup copy and raises ValueError."""
    if not file_path.exists():
        return {}
    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(f"Expected JSON object in {file_path}, found {type(data).__name__}")
            return data
    except Exception as e:
        try:
            backup_path = file_path.with_name(f"{file_path.name}.backup")
            shutil.copyfile(file_path, backup_path)
        except OSError:
            pass
        raise ValueError(f"Could not parse JSON in {file_path}: {e}")


def write_json_file(file_path: Path, data: dict[str, Any]) -> None:
    """Atomically write formatted JSON data to file_path."""
    atomic_write_file(file_path, json.dumps(data, indent=2) + "\n")


def json_deep_equal(a: Any, b: Any) -> bool:
    """Check structural equality between two JSON structures ignoring dict key ordering."""
    return a == b
