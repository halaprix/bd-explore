#!/bin/sh
set -eu

INSTALL_DIR="${BD_EXPLORE_HOME:-$HOME/.bd-explore}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"

# Determine mode: install or uninstall
MODE="install"
for arg in "$@"; do
    case "$arg" in
        --uninstall|-u|uninstall)
            MODE="uninstall"
            ;;
        --help|-h)
            echo "Usage: install.sh [--uninstall]"
            echo ""
            echo "Options:"
            echo "  --uninstall    Uninstall bd-explore binaries, agent configs, and memory"
            echo "  --help         Show this help message"
            exit 0
            ;;
    esac
done

if [ "$MODE" = "uninstall" ]; then
    echo "Uninstalling bd-explore..."

    # Run agent uninstaller if launcher or module exists
    if [ -x "$BIN_DIR/bd-explore" ]; then
        "$BIN_DIR/bd-explore" uninstall --yes || true
    elif [ -d "$INSTALL_DIR/src" ]; then
        PYTHONPATH="$INSTALL_DIR/src" python3 -m bd_explore uninstall --yes || true
    fi

    # Remove launchers
    rm -f "$BIN_DIR/bd-explore" "$BIN_DIR/bd_explore"

    # Remove install dir if present
    if [ -d "$INSTALL_DIR" ]; then
        rm -rf "$INSTALL_DIR"
    fi

    echo "✓ bd-explore successfully uninstalled."
    exit 0
fi

echo "Installing bd-explore..."

# 1. Verify python3 availability
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required but not found in PATH." >&2
    exit 1
fi

# 2. Verify Python version >= 3.10
python3 -c '
import sys
if sys.version_info < (3, 10):
    print(f"Error: Python 3.10+ required, found {sys.version.split()[0]}", file=sys.stderr)
    sys.exit(1)
'

# 3. Verify SQLite FTS5 capability
python3 -c "import sqlite3; sqlite3.connect(':memory:').execute('CREATE VIRTUAL TABLE t USING fts5(x)')" 2>/dev/null || {
    echo "Error: Python sqlite3 module does not have FTS5 virtual table support enabled." >&2
    exit 1
}

# 4. Resolve source files
SCRIPT_DIR=""
if [ -n "${0:-}" ] && [ -f "$0" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
fi

mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"

if [ -n "$SCRIPT_DIR" ] && [ -d "$SCRIPT_DIR/src/bd_explore" ]; then
    # Local source directory
    rm -rf "$INSTALL_DIR/src"
    cp -R "$SCRIPT_DIR/src" "$INSTALL_DIR/"
elif [ -d "./src/bd_explore" ]; then
    rm -rf "$INSTALL_DIR/src"
    cp -R "./src" "$INSTALL_DIR/"
else
    # Remote / standalone installation via git clone if available
    if command -v git >/dev/null 2>&1; then
        TMP_CLONE="$(mktemp -d)"
        git clone --depth 1 https://github.com/gastownhall/bd-explore.git "$TMP_CLONE"
        rm -rf "$INSTALL_DIR/src"
        cp -R "$TMP_CLONE/src" "$INSTALL_DIR/"
        rm -rf "$TMP_CLONE"
    else
        echo "Error: Cannot locate bd-explore source files and git is not installed." >&2
        exit 1
    fi
fi

# 5. Create launcher in BIN_DIR
LAUNCHER="$BIN_DIR/bd-explore"
cat << 'EOF' > "$LAUNCHER"
#!/bin/sh
BD_EXPLORE_HOME="${BD_EXPLORE_HOME:-$HOME/.bd-explore}"
export PYTHONPATH="$BD_EXPLORE_HOME/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m bd_explore "$@"
EOF

chmod +x "$LAUNCHER"

# Link or copy bd_explore to bd-explore
ln -sf "$LAUNCHER" "$BIN_DIR/bd_explore" 2>/dev/null || cp -f "$LAUNCHER" "$BIN_DIR/bd_explore"
chmod +x "$BIN_DIR/bd_explore"

# 6. Run bd-explore install --yes to configure agent platforms and inject beads memory
"$LAUNCHER" install --yes

# 7. Check PATH
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        echo ""
        echo "Note: $BIN_DIR is not in your PATH."
        echo "Add it to your shell configuration (e.g. ~/.bashrc, ~/.zshrc):"
        echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
esac

echo ""
echo "✓ bd-explore installed successfully!"
