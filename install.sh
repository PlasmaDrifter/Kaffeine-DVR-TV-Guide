#!/usr/bin/env bash
set -e

# ==============================================================================
# Kaffeine DVR & TV Guide - Automated Installer
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EDITABLE_INSTALL=false

# Parse flags
for arg in "$@"; do
    case "$arg" in
        -e|--editable)
            EDITABLE_INSTALL=true
            ;;
        -h|--help)
            echo "Usage: ./install.sh [options]"
            echo ""
            echo "Options:"
            echo "  -e, --editable    Install in editable/development mode (pip install -e .)"
            echo "  -h, --help        Show this help message"
            exit 0
            ;;
    esac
done

echo "============================================================"
echo "Installing Kaffeine DVR & TV Guide"
echo "============================================================"

# 1. Check Python 3
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is not installed. Please install Python 3 (>= 3.9) first." >&2
    exit 1
fi

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="$(python3 -c 'import sys; print(sys.version_info.major)')"
PY_MINOR="$(python3 -c 'import sys; print(sys.version_info.minor)')"

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]; }; then
    echo "Error: Python 3.9 or newer is required. Found Python $PY_VER." >&2
    exit 1
fi

echo "Found Python $PY_VER"

# 2. Check pip
if ! python3 -m pip --version >/dev/null 2>&1; then
    echo "Error: pip is not available for python3. Please install python3-pip." >&2
    exit 1
fi

# Detect PEP 668 (--break-system-packages) support
PIP_FLAGS="--user"
if python3 -m pip install --help 2>&1 | grep -q -- '--break-system-packages'; then
    PIP_FLAGS="--user --break-system-packages"
fi

# 3. Install Python package
echo "Installing Python package..."
if [ "$EDITABLE_INSTALL" = true ]; then
    echo "Running: python3 -m pip install $PIP_FLAGS -e \"$SCRIPT_DIR\""
    python3 -m pip install $PIP_FLAGS -e "$SCRIPT_DIR"
else
    echo "Running: python3 -m pip install $PIP_FLAGS \"$SCRIPT_DIR\""
    python3 -m pip install $PIP_FLAGS "$SCRIPT_DIR"
fi

# 4. Ensure destination directories exist
USER_BIN_DIR="$HOME/.local/bin"
USER_APPS_DIR="$HOME/.local/share/applications"
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"

mkdir -p "$USER_BIN_DIR"
mkdir -p "$USER_APPS_DIR"
mkdir -p "$USER_SYSTEMD_DIR"

# 5. Install Desktop Launcher
echo "Installing desktop launcher..."
DESKTOP_SRC="$SCRIPT_DIR/desktop/kaffeine-dvr.desktop"
if [ -f "$DESKTOP_SRC" ]; then
    cp "$DESKTOP_SRC" "$USER_APPS_DIR/kaffeine-dvr.desktop"
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$USER_APPS_DIR" >/dev/null 2>&1 || true
    fi
    echo "Desktop launcher installed to $USER_APPS_DIR/kaffeine-dvr.desktop"
else
    echo "Warning: desktop/kaffeine-dvr.desktop not found, skipping desktop entry."
fi

# 6. Install Systemd Background Watcher Service
echo "Configuring systemd background watcher service..."
SERVICE_SRC="$SCRIPT_DIR/systemd/kaffeine-dvr-watcher.service"
if [ -f "$SERVICE_SRC" ]; then
    cp "$SERVICE_SRC" "$USER_SYSTEMD_DIR/kaffeine-dvr-watcher.service"
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user daemon-reload || true
        systemctl --user enable --now kaffeine-dvr-watcher.service || true
        echo "Background watcher service enabled and started."
    fi
else
    echo "Warning: systemd/kaffeine-dvr-watcher.service not found, skipping service installation."
fi

# 7. Check user PATH
echo ""
echo "============================================================"
echo "Installation Complete!"
echo "============================================================"
if [[ ":$PATH:" != *":$USER_BIN_DIR:"* ]]; then
    echo "Notice: $USER_BIN_DIR is not currently in your PATH."
    echo "Add the following line to your ~/.bashrc or ~/.zshrc:"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
fi

echo "To launch Kaffeine DVR:"
echo "  - Command line:  kaffeine-dvr"
echo "  - Desktop menu:  Search for 'Kaffeine DVR & TV Guide'"
echo ""
