"""Main CLI entrypoints and command routing for bd-explore."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from bd_explore.constants import DEFAULT_BUDGET_CHARS, DEFAULT_SEEDS, VERSION
from bd_explore.index import find_store, open_index
from bd_explore.installer import (
    TARGET_REGISTRY,
    detect_installed_targets,
    print_config,
    run_installer,
    run_uninstaller,
)
from bd_explore.mcp import run_mcp_server
from bd_explore.search import blast_data, format_blast, format_output, parse_query, search

__all__ = ["main"]

SUBCOMMANDS = {"serve", "install", "uninstall", "print-config", "print_config", "config"}


def _error(msg: str) -> None:
    """Print an error message to stderr and exit with non-zero status."""
    print(msg, file=sys.stderr)
    sys.exit(1)


def _split_targets(raw_targets: list[str] | None) -> list[str]:
    """Normalize a list of target names, splitting comma-separated items."""
    if not raw_targets:
        return []
    result = []
    for item in raw_targets:
        for part in str(item).split(","):
            part = part.strip()
            if part:
                result.append(part)
    return result


def _normalize_location(loc: str) -> str:
    """Normalize location string to 'global' or 'project'."""
    loc_clean = loc.strip().lower()
    return "project" if loc_clean in ("local", "project") else "global"


def _handle_serve(args: argparse.Namespace) -> int:
    """Run the stdio MCP server."""
    store_path = None
    if getattr(args, "store", None):
        try:
            store_path = find_store(args.store)
        except (FileNotFoundError, ValueError) as e:
            _error(f"bd-explore: {e}")
    run_mcp_server(default_store=store_path)
    return 0


def _handle_print_config(args: argparse.Namespace) -> int:
    """Print the MCP configuration snippet for a given target."""
    target_name = getattr(args, "target_flag", None) or getattr(args, "target", None)
    if not target_name:
        _error("bd-explore: error: target name required for print-config (e.g. 'bd-explore print-config claude')")
    try:
        snippet = print_config(target_name)
        print(snippet)
        return 0
    except Exception as e:
        _error(f"bd-explore: error: {e}")


def _handle_install(args: argparse.Namespace) -> int:
    """Run the interactive or batch installer."""
    raw_targets = getattr(args, "targets", None)
    clean_targets = _split_targets(raw_targets)
    location = _normalize_location(getattr(args, "location", "global"))
    auto_allow = getattr(args, "auto_allow", False)
    yes = getattr(args, "yes", False)

    # Interactive mode when stdin is a terminal and not in batch mode
    if not yes and sys.stdin.isatty():
        print("═" * 50)
        print("  bd-explore Agent Platform Installer")
        print("═" * 50)

        detected = detect_installed_targets()
        if detected:
            print(f"Detected agent platforms: {', '.join(detected)}")
        else:
            print("No existing agent configurations detected.")

        if not clean_targets:
            if detected:
                prompt_str = f"Install targets [{', '.join(detected)}] (press Enter to accept, or enter comma-separated names): "
            else:
                prompt_str = f"Install targets [{', '.join(TARGET_REGISTRY.keys())}] (press Enter for all, or enter comma-separated names): "
            user_input = input(prompt_str).strip()
            if user_input:
                clean_targets = _split_targets([user_input])
            elif detected:
                clean_targets = detected
            else:
                clean_targets = list(TARGET_REGISTRY.keys())

        if not getattr(args, "location_explicit", False):
            loc_input = input(f"Installation location [global/project] (default: {location}): ").strip()
            if loc_input:
                location = _normalize_location(loc_input)

        targets_disp = ", ".join(clean_targets) if clean_targets else "all"
        confirm = input(f"Install bd-explore for {targets_disp} ({location})? [Y/n]: ").strip().lower()
        if confirm and confirm not in ("y", "yes"):
            print("Installation cancelled.")
            return 0

    res = run_installer(
        targets=clean_targets if clean_targets else None,
        location=location,
        auto_allow=auto_allow,
        yes=True,
    )

    print("\nInstallation results:")
    for r in res.get("targets", []):
        t_name = r.get("target")
        status = r.get("status")
        if status == "ok":
            files = r.get("files", [])
            files_str = f" -> {', '.join(files)}" if files else ""
            print(f"  ✓ {t_name}: configured ({location}){files_str}")
        elif status == "skipped":
            print(f"  - {t_name}: skipped ({r.get('message', '')})")
        else:
            print(f"  ✗ {t_name}: error ({r.get('message', '')})")

    mem = res.get("memory")
    if mem:
        mem_status = mem.get("status")
        if mem_status == "injected":
            print(f"  ✓ beads memory: injected ({mem.get('command', '')})")
        elif mem_status == "skipped":
            print(f"  - beads memory: skipped ({mem.get('message', '')})")
        else:
            print(f"  ✗ beads memory: {mem.get('message', '')}")

    print("\nInstallation complete.")
    return 0


def _handle_uninstall(args: argparse.Namespace) -> int:
    """Run the uninstaller across agent targets."""
    raw_targets = getattr(args, "targets", None)
    clean_targets = _split_targets(raw_targets)
    location = _normalize_location(getattr(args, "location", "global"))
    yes = getattr(args, "yes", False)

    if not yes and sys.stdin.isatty():
        targets_disp = ", ".join(clean_targets) if clean_targets else "all detected targets"
        confirm = input(f"Uninstall bd-explore from {targets_disp} ({location})? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Uninstallation cancelled.")
            return 0

    res = run_uninstaller(
        targets=clean_targets if clean_targets else None,
        location=location,
    )

    print("\nUninstallation results:")
    for r in res.get("targets", []):
        t_name = r.get("target")
        status = r.get("status")
        if status == "ok":
            print(f"  ✓ {t_name}: uninstalled")
        else:
            print(f"  ✗ {t_name}: error ({r.get('message', '')})")

    mem = res.get("memory")
    if mem:
        mem_status = mem.get("status")
        if mem_status == "removed":
            print("  ✓ beads memory: removed")
        elif mem_status == "skipped":
            print(f"  - beads memory: skipped ({mem.get('message', '')})")
        else:
            print(f"  ✗ beads memory: {mem.get('message', '')}")

    print("\nUninstallation complete.")
    return 0


def _build_explore_parser() -> argparse.ArgumentParser:
    """Build the query/explore argument parser."""
    p = argparse.ArgumentParser(
        prog="bd-explore",
        description="Ask a beads store questions, codegraph-style.",
        epilog=(
            "Filters:\n"
            "  status:open|closed|in_progress|deferred|all\n"
            "  type:bug|feature|task|epic|chore\n"
            "  priority:0..4\n"
            "  epic:<id-or-suffix>\n"
            "  id:<prefix>\n\n"
            "Subcommands:\n"
            "  serve         Run stdio MCP server\n"
            "  install       Install MCP server and instructions into agent platforms\n"
            "  uninstall     Uninstall MCP server from agent platforms\n"
            "  print-config  Print MCP configuration snippet for a target platform\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("query", nargs="*", help="free text + field filters (status: type: priority: epic: id:)")
    p.add_argument("--store", help="path to repo, .beads dir, or issues.jsonl")
    p.add_argument("--blast", metavar="ID", help="blast radius for one bead id (or suffix)")
    p.add_argument("--rebuild", action="store_true", help="force reindex")
    p.add_argument("-n", "--limit", type=int, default=DEFAULT_SEEDS, help=f"max seeds (default: {DEFAULT_SEEDS})")
    p.add_argument("--budget", type=int, default=DEFAULT_BUDGET_CHARS, help=f"output char budget (default: {DEFAULT_BUDGET_CHARS})")
    p.add_argument("--version", "-V", action="version", version=f"bd-explore {VERSION}")
    p.add_argument("--mcp", action="store_true", help="run stdio JSON-RPC MCP server")
    return p


def _build_subcommand_parser(cmd: str) -> argparse.ArgumentParser:
    """Build argument parser for a specific subcommand."""
    if cmd == "serve":
        p = argparse.ArgumentParser(prog="bd-explore serve", description="Run stdio JSON-RPC MCP server.")
        p.add_argument("--store", help="path to repo, .beads dir, or issues.jsonl")
        return p
    if cmd == "install":
        p = argparse.ArgumentParser(prog="bd-explore install", description="Install bd-explore MCP server & instructions into agent platforms.")
        p.add_argument("-t", "--targets", nargs="*", help="target platforms (claude, gemini, antigravity, codex, cursor, agents_md)")
        p.add_argument("-l", "--location", choices=["global", "project", "local"], default="global", help="installation location")
        p.add_argument("--auto-allow", action="store_true", help="auto-approve permissions for MCP tools where supported")
        p.add_argument("-y", "--yes", action="store_true", help="skip interactive confirmation prompts")
        return p
    if cmd == "uninstall":
        p = argparse.ArgumentParser(prog="bd-explore uninstall", description="Uninstall bd-explore from agent platforms.")
        p.add_argument("-t", "--targets", nargs="*", help="target platforms to uninstall from")
        p.add_argument("-l", "--location", choices=["global", "project", "local"], default="global", help="target location")
        p.add_argument("-y", "--yes", action="store_true", help="skip interactive confirmation prompts")
        return p
    if cmd in ("print-config", "print_config", "config"):
        p = argparse.ArgumentParser(prog="bd-explore print-config", description="Print MCP configuration snippet for an agent platform.")
        p.add_argument("target", nargs="?", help="target agent platform name (e.g. claude, cursor, codex)")
        p.add_argument("-t", "--target", dest="target_flag", help="target agent platform name")
        p.add_argument("-l", "--location", choices=["global", "project", "local"], default="global", help="configuration location")
        return p
    raise ValueError(f"Unknown subcommand: {cmd}")


def main(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint for bd-explore."""
    if argv is None:
        argv = sys.argv[1:]

    # Check if a subcommand is specified as the first non-option argument
    cmd_idx = -1
    for i, arg in enumerate(argv):
        if not arg.startswith("-"):
            if arg in SUBCOMMANDS:
                cmd_idx = i
            break

    if cmd_idx != -1:
        cmd_name = argv[cmd_idx]
        sub_argv = argv[:cmd_idx] + argv[cmd_idx + 1:]
        sub_parser = _build_subcommand_parser(cmd_name)
        sub_args = sub_parser.parse_args(sub_argv)

        # Track if --location was explicitly set
        if "-l" in sub_argv or "--location" in sub_argv:
            setattr(sub_args, "location_explicit", True)

        if cmd_name == "serve":
            return _handle_serve(sub_args)
        if cmd_name == "install":
            return _handle_install(sub_args)
        if cmd_name == "uninstall":
            return _handle_uninstall(sub_args)
        if cmd_name in ("print-config", "print_config", "config"):
            return _handle_print_config(sub_args)

    # Otherwise, handle explore/query/blast/rebuild/mcp options
    parser = _build_explore_parser()
    args = parser.parse_args(argv)

    if args.mcp:
        return _handle_serve(args)

    if not args.query and not args.blast and not args.rebuild:
        _error("bd-explore: error: give a query, --blast <id>, or --rebuild")

    try:
        store = find_store(args.store)
    except (FileNotFoundError, ValueError) as e:
        _error(str(e))

    try:
        con = open_index(store, force=args.rebuild)
    except Exception as e:
        _error(f"bd-explore: index error: {e}")

    try:
        if args.blast:
            try:
                data = blast_data(con, args.blast)
                print(format_blast(con, data))
                return 0
            except ValueError as e:
                _error(str(e))

        if not args.query:
            if args.rebuild:
                n = con.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
                print(f"rebuilt: {n} docs from {store}")
                return 0
            _error("bd-explore: error: give a query, --blast <id>, or --rebuild")

        text, filters = parse_query(" ".join(args.query))
        rows = search(con, text, filters, args.limit)
        print(format_output(con, rows, args.budget))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
