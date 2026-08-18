"""bd-explore installer package for configuring agent platforms, instructions, and memory."""

from bd_explore.installer.instructions import (
    BD_EXPLORE_INSTRUCTIONS_BLOCK,
    BD_EXPLORE_SECTION_END,
    BD_EXPLORE_SECTION_START,
    remove_marked_section,
    replace_or_append_marked_section,
    upsert_instructions_entry,
)
from bd_explore.installer.memory import (
    inject_beads_memory,
    is_bd_available,
    remove_beads_memory,
)
from bd_explore.installer.shared import (
    atomic_write_file,
    json_deep_equal,
    read_json_file,
    write_json_file,
)
from bd_explore.installer.targets import (
    TARGET_ALIASES,
    TARGET_REGISTRY,
    detect_installed_targets,
    get_target,
    print_config,
    run_installer,
    run_uninstaller,
)

__all__ = [
    "atomic_write_file",
    "read_json_file",
    "write_json_file",
    "json_deep_equal",
    "BD_EXPLORE_SECTION_START",
    "BD_EXPLORE_SECTION_END",
    "BD_EXPLORE_INSTRUCTIONS_BLOCK",
    "replace_or_append_marked_section",
    "upsert_instructions_entry",
    "remove_marked_section",
    "is_bd_available",
    "inject_beads_memory",
    "remove_beads_memory",
    "TARGET_REGISTRY",
    "TARGET_ALIASES",
    "get_target",
    "detect_installed_targets",
    "print_config",
    "run_installer",
    "run_uninstaller",
]
